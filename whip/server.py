"""
The local web app: live gesture tracking, settings, and firmware flashing.

One process owns everything, because bleak and aiohttp must share an event
loop: the `RingManager` holds the BLE connection, the aiohttp app holds the
sockets, and every browser tab watches the same ring through one websocket
fan-out.

**The state machine is the safety mechanism.** IDLE -> CONNECTED -> STREAMING
or FLASHING, never both: flashing while notifications stream would interleave
DFU frames with sensor traffic on a link with no recovery path. Every mutation
goes through the manager under one lock, so two browser tabs cannot race a
flash against a stream.

Flashing keeps every refuse-by-default gate from `whip.flashing` (they live in
the library precisely so no frontend can skip one) and adds the interaction
gate the library deliberately leaves to callers: the request must carry the
typed confirmation word, and a dry run must have passed first in the same
connection.

Binds to 127.0.0.1 only. This controls a wearable and reflashes firmware; it
has no business on a network interface.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from whip import capture, protocol
from whip.flashing import (
    FLASH_TARGETS,
    FlashAborted,
    detect_mode,
    dry_run,
    flash_connected,
    load_catalogue_entry,
    preflight,
)
from whip import fwimage
from whip.realtime import DEFAULT_CONFIG_PATH, Engine, EventLog, RouterConfig

logger = logging.getLogger(__name__)

MANAGER_KEY = web.AppKey("manager", object)

HOST = "127.0.0.1"
PORT = 8642
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

CONFIRM_WORD = "FLASH"

# How many recent samples the UI waveform gets on each push, and how often.
UI_PUSH_INTERVAL_S = 0.15


class RingManager:
    """All ring state, mutated only under its lock."""

    def __init__(self, checkpoint: Path = Path("data/model.pt")):
        self.checkpoint = checkpoint
        self.state = "idle"                # idle | connected | streaming | flashing
        self.device = None
        self.client = None
        self.info = None
        self.battery = None
        self._client_ctx = None
        self._lock = asyncio.Lock()
        self._stop_stream: asyncio.Event | None = None
        self._stream_task: asyncio.Task | None = None
        self._queue: collections.deque = collections.deque()
        self._sockets: set[web.WebSocketResponse] = set()
        self._dry_run_ok: set[str] = set()   # targets validated this connection
        self.engine: Engine | None = None
        self.config = RouterConfig.load()
        self._event_log: EventLog | None = None

    # ------------------------------------------------------------ broadcast

    def attach(self, ws: web.WebSocketResponse) -> None:
        self._sockets.add(ws)

    def detach(self, ws: web.WebSocketResponse) -> None:
        self._sockets.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in self._sockets:
            try:
                await ws.send_json(payload)
            except (ConnectionResetError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            self._sockets.discard(ws)

    async def _set_state(self, state: str) -> None:
        self.state = state
        await self.broadcast({"type": "state", "state": state, **self.status()})

    # ------------------------------------------------------------ status

    def status(self) -> dict:
        return {
            "state": self.state,
            "device": self.info.as_dict() if self.info else None,
            "battery": self.battery,
            "mode": detect_mode(self.info.firmware) if self.info else "unknown",
            "checkpoint": str(self.checkpoint),
            "threshold": self.config.threshold,
        }

    def model_info(self) -> dict:
        if not self.checkpoint.exists():
            return {"available": False, "reason": f"no checkpoint at {self.checkpoint}"}
        from whip import model as gm
        import torch  # noqa: F401 - gm.load needs it importable

        try:
            _, provenance = gm.load(self.checkpoint)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not hidden
            return {"available": False, "reason": str(exc)}
        return {
            "available": True,
            "labels": provenance.get("labels"),
            "channels": provenance.get("channels"),
            "direction_names": provenance.get("direction_names"),
            "trained_on": provenance.get("trained_on"),
            "held_out": provenance.get("held_out"),
        }

    # ------------------------------------------------------------ connection

    async def connect(self, address: str | None = None, timeout: float = 25.0) -> dict:
        async with self._lock:
            if self.state != "idle":
                raise web.HTTPConflict(text=f"cannot connect while {self.state}")
            await self._set_state("connecting")
            try:
                self.device = await capture.find_ring(address=address, timeout=timeout)
                self._client_ctx = capture.connected(self.device)
                self.client = await self._client_ctx.__aenter__()
                self.info = await capture.read_device_info(self.client, self.device)
                got = await capture.read_battery(self.client)
                self.battery = got[0] if got else None
                self._dry_run_ok = set()
                await self._set_state("connected")
                return self.status()
            except Exception as exc:
                await self._teardown()
                await self._set_state("idle")
                raise web.HTTPBadGateway(text=str(exc)) from exc

    async def disconnect(self) -> dict:
        async with self._lock:
            if self.state == "flashing":
                raise web.HTTPConflict(text="cannot disconnect mid-flash")
            await self._stop_streaming_locked()
            await self._teardown()
            await self._set_state("idle")
            return self.status()

    async def _teardown(self) -> None:
        if self._client_ctx is not None:
            try:
                await self._client_ctx.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001 - teardown only
                logger.warning("disconnect error: %s", exc)
        self.client = None
        self._client_ctx = None
        self.device = None
        self.info = None
        self.battery = None
        self._dry_run_ok = set()

    # ------------------------------------------------------------ streaming

    async def start_streaming(self) -> dict:
        async with self._lock:
            if self.state != "connected":
                raise web.HTTPConflict(text=f"cannot stream while {self.state}")
            if not self.checkpoint.exists():
                raise web.HTTPFailedDependency(
                    text=f"no model checkpoint at {self.checkpoint}; train one first")
            self.config = RouterConfig.load()
            self.engine = Engine.from_checkpoint(self.checkpoint,
                                                 threshold=self.config.threshold)
            self._event_log = EventLog()
            self._queue.clear()
            self._stop_stream = asyncio.Event()
            self._stream_task = asyncio.create_task(self._stream_loop())
            await self._set_state("streaming")
            return self.status()

    async def stop_streaming(self) -> dict:
        async with self._lock:
            await self._stop_streaming_locked()
            if self.state == "streaming":
                await self._set_state("connected")
            return self.status()

    async def _stop_streaming_locked(self) -> None:
        if self._stop_stream is not None:
            self._stop_stream.set()
        if self._stream_task is not None:
            try:
                await self._stream_task
            except Exception as exc:  # noqa: BLE001 - the loop reports its own errors
                logger.warning("stream task ended with: %s", exc)
        self._stream_task = None
        self._stop_stream = None

    async def _stream_loop(self) -> None:
        """BLE stream + engine drain + UI push, until stopped."""
        stop = self._stop_stream
        engine, config, log = self.engine, self.config, self._event_log
        recent: collections.deque = collections.deque(maxlen=100)

        async def consume() -> None:
            last_push = 0.0
            while not stop.is_set():
                drained = False
                while self._queue:
                    t, payload = self._queue.popleft()
                    drained = True
                    if len(payload) >= 8 and payload[0] == protocol.CMD_RAW_SENSOR \
                            and payload[1] == protocol.SUBTYPE_ACCEL:
                        from whip import accel
                        s = accel.decode(payload)
                        recent.append((round(t, 3), s.x, s.y, s.z))
                    for event in engine.feed(t, payload):
                        action = config.action_for(event)
                        log.write(event, action)
                        await self.broadcast({"type": "event",
                                              **event.as_dict(), "action": action})
                if not drained:
                    await asyncio.sleep(0.03)
                now = asyncio.get_running_loop().time()
                if now - last_push >= UI_PUSH_INTERVAL_S and recent:
                    last_push = now
                    await self.broadcast({
                        "type": "live",
                        "samples": list(recent),
                        "probabilities": engine.last_probabilities,
                        "frame": engine.frame_name,
                    })
                    recent.clear()

        consumer = asyncio.create_task(consume())
        try:
            await capture.stream(self.client, duration=0, stop=stop,
                                 param=protocol.RAW_ENABLE_ALL,
                                 on_record=self._queue.append)
        except Exception as exc:  # noqa: BLE001 - surface, then settle state
            logger.warning("stream ended: %s", exc)
            await self.broadcast({"type": "error", "message": f"stream ended: {exc}"})
        finally:
            stop.set()
            await consumer
            for event in engine.finish():
                log.write(event, config.action_for(event))
            log.close()

    # ------------------------------------------------------------ flashing

    async def flash(self, target: str, confirm: str) -> dict:
        if target not in FLASH_TARGETS:
            raise web.HTTPBadRequest(text=f"unknown target {target!r}")
        if confirm != CONFIRM_WORD:
            raise web.HTTPBadRequest(
                text=f"confirmation must be the word {CONFIRM_WORD!r}")
        async with self._lock:
            if self.state != "connected":
                raise web.HTTPConflict(
                    text=f"flashing requires state 'connected' (streaming stopped); now {self.state}")
            if target not in self._dry_run_ok:
                raise web.HTTPPreconditionFailed(
                    text="run the dry-run validation for this target first")
            spec = FLASH_TARGETS[target]
            await self._set_state("flashing")

            async def progress_async(payload: dict) -> None:
                await self.broadcast({"type": "flash", **payload})

            loop = asyncio.get_running_loop()

            def progress(payload: dict) -> None:
                loop.create_task(progress_async(payload))

            try:
                await flash_connected(self.client, self.info, spec["image"],
                                      spec["init_type"], progress=progress)
                await self.broadcast({"type": "flash", "stage": "done",
                                      "message": "transfer complete -- the ring reboots "
                                                 "to apply the image"})
            except FlashAborted as exc:
                await self.broadcast({"type": "flash", "stage": "aborted",
                                      "message": str(exc)})
                raise web.HTTPUnprocessableEntity(text=str(exc)) from exc
            finally:
                # The ring reboots after a flash; the old connection is dead
                # either way. Settle to idle so the UI prompts a reconnect.
                await self._teardown()
                await self._set_state("idle")
            return {"ok": True}

    def validate_target(self, target: str) -> dict:
        """Preflight + dry run, no radio. Success arms the real flash button."""
        if target not in FLASH_TARGETS:
            raise web.HTTPBadRequest(text=f"unknown target {target!r}")
        spec = FLASH_TARGETS[target]
        facts: list[dict] = []

        def collect(payload: dict) -> None:
            facts.append(payload)

        image = fwimage.inspect(spec["image"])
        entry = load_catalogue_entry(image)
        try:
            preflight(image, entry, allow_unpinned=False, progress=collect)
            stats = dry_run(image, progress=collect)
        except FlashAborted as exc:
            raise web.HTTPUnprocessableEntity(text=str(exc)) from exc
        if self.state == "connected":
            self._dry_run_ok.add(target)
        return {"ok": True, "facts": facts, **stats,
                "armed": target in self._dry_run_ok,
                "note": None if self.state == "connected"
                else "connect to the ring to arm the flash button"}


# ---------------------------------------------------------------- HTTP layer

def build_app(manager: RingManager) -> web.Application:
    app = web.Application()
    app[MANAGER_KEY] = manager

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(WEB_DIR / "index.html")

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(manager.status())

    async def model_info(_request: web.Request) -> web.Response:
        return web.json_response(manager.model_info())

    async def targets(_request: web.Request) -> web.Response:
        return web.json_response({
            name: {"title": spec["title"], "description": spec["description"],
                   "image": spec["image"].name}
            for name, spec in FLASH_TARGETS.items()})

    async def connect(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        return web.json_response(await manager.connect(address=body.get("address")))

    async def disconnect(_request: web.Request) -> web.Response:
        return web.json_response(await manager.disconnect())

    async def stream_start(_request: web.Request) -> web.Response:
        return web.json_response(await manager.start_streaming())

    async def stream_stop(_request: web.Request) -> web.Response:
        return web.json_response(await manager.stop_streaming())

    async def flash_validate(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(manager.validate_target(body.get("target", "")))

    async def flash(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(await manager.flash(
            body.get("target", ""), body.get("confirm", "")))

    async def get_config(_request: web.Request) -> web.Response:
        config = RouterConfig.load()
        return web.json_response({"mappings": config.mappings,
                                  "threshold": config.threshold})

    async def put_config(request: web.Request) -> web.Response:
        body = await request.json()
        config = RouterConfig(
            mappings={str(k): str(v) for k, v in body.get("mappings", {}).items()},
            threshold=float(body.get("threshold", RouterConfig().threshold)))
        config.save(DEFAULT_CONFIG_PATH)
        manager.config = config
        if manager.engine is not None:
            manager.engine.threshold = config.threshold
        return web.json_response({"ok": True})

    async def websocket(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        manager.attach(ws)
        try:
            await ws.send_json({"type": "state", **manager.status()})
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            manager.detach(ws)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/model", model_info)
    app.router.add_get("/api/flash/targets", targets)
    app.router.add_post("/api/connect", connect)
    app.router.add_post("/api/disconnect", disconnect)
    app.router.add_post("/api/stream/start", stream_start)
    app.router.add_post("/api/stream/stop", stream_stop)
    app.router.add_post("/api/flash/validate", flash_validate)
    app.router.add_post("/api/flash", flash)
    app.router.add_get("/api/config", get_config)
    app.router.add_put("/api/config", put_config)
    app.router.add_get("/ws", websocket)
    app.router.add_static("/static", WEB_DIR)
    return app


def main(checkpoint: Path = Path("data/model.pt"), port: int = PORT) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    manager = RingManager(checkpoint=checkpoint)
    app = build_app(manager)
    print(f"Whip ring console: http://{HOST}:{port}")
    print("  Live gesture tracking, settings, and stock <-> gesture firmware flashing.")
    web.run_app(app, host=HOST, port=port, print=None)
