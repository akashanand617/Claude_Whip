"""Bounded continuous battery test on the original, fingerprinted 25 Hz image.

    python -m probe.batterycheck --address <ring> --optical-stop

One A1 04 session, one UART notification subscription, no flashing. The LED-off
workaround uses only audited volatile mode 3 and the fixed VC30F STOP command.
Darkness still requires visual confirmation. Code reads are critical-site
fingerprints, not full-image attestation; unsupported reads abort before start.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
import json
import math
import os
from pathlib import Path
import signal
import time

from probe.ledcheck import accel_freshness, motion_control_packet, optical_stop_packet
from whip import capture, fwidentity, fwoptical, protocol

BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"
WINDOW_S = 10.0
WARMUP_S = 2.0
RAM_READS = {"motion_control": (0x20BFC0, 3), "accel_state": (0x20BDC4, 2)}


def stream_health(records, begin: float, end: float) -> dict:
    """Rolling delivery and exact-XYZ freshness; does not demand hand motion."""
    start = max(begin + WARMUP_S, end - WINDOW_S)
    samples = [(t, p) for t, p in records if start <= t <= end]
    duration = max(0.0, end - start)
    valid = [(t, p) for t, p in samples
             if len(p) == 16 and protocol.checksum(p[:-1]) == p[-1]]
    gaps = ([valid[0][0] - start, end - valid[-1][0]] +
            [b[0] - a[0] for a, b in zip(valid, valid[1:])]) if valid else [duration]
    freshness = accel_freshness(valid, start)
    rate = len(valid) / duration if duration else 0.0
    distinct = len({p[2:8] for _, p in valid})
    ready = duration >= WINDOW_S - 0.001
    passed = (ready and 24 <= rate <= 26 and max(gaps) <= 0.5
              and len(valid) == len(samples) and distinct >= 3
              and freshness["max_identical_accel_s"] is not None
              and freshness["max_identical_accel_s"] <= 1.0)
    return {"observed_s": duration, "hz": rate, "samples": len(valid),
            "invalid_packets": len(samples) - len(valid), "max_gap_s": max(gaps),
            "distinct_xyz": distinct, **freshness, "ready": ready, "passed": passed}


class Session:
    """Single subscriber and serialized, fail-closed request/reply owner."""

    def __init__(self, client, log):
        self.client, self.log = client, log
        self.origin = time.perf_counter()
        self.phase = "preflight"
        self.pending = deque()
        self.accel = deque(maxlen=1000)
        self.replies = {command: asyncio.Queue() for command in (0x03, 0xCD, 0xCE, 0x3B)}
        self.poisoned = False
        self.busy = False

    def now(self):
        return time.perf_counter() - self.origin

    def notify(self, _sender, data):
        packet = bytes(data)
        record = (self.now(), time.time(), self.phase, packet)
        self.pending.append(record)
        if packet[:2] == b"\xa1\x03":
            self.accel.append((record[0], packet))
        if packet and packet[0] in self.replies:
            self.replies[packet[0]].put_nowait(record)

    def flush(self, durable=False):
        while self.pending:
            t, wall, phase, packet = self.pending.popleft()
            self.log.write(json.dumps({"kind": "packet", "phase": phase,
                                       "t": t, "wall": wall, "p": packet.hex()}) + "\n")
        self.log.flush()
        if durable:
            # StringIO is used by offline tests; real logs always have a fileno.
            try:
                fd = self.log.fileno()
            except (AttributeError, OSError):
                return
            os.fsync(fd)

    def emit(self, kind, **values):
        self.flush()
        record = {"kind": kind, "phase": self.phase, "t": self.now(),
                  "wall": time.time(), **values}
        self.log.write(json.dumps(record) + "\n")
        self.flush(durable=True)
        print(json.dumps(record), flush=True)

    async def send(self, packet):
        self.emit("command", packet=bytes(packet).hex())
        await asyncio.wait_for(self.client.write_gatt_char(
            protocol.UART_RX_CHAR_UUID, packet, response=False), 3.0)

    async def exchange(self, packet, timeout=3.0):
        if self.poisoned or self.busy or any(not q.empty() for q in self.replies.values()):
            self.poisoned = True
            raise RuntimeError("Reply correlation lost; aborting the whole diagnostic sequence")
        self.busy = True
        try:
            async def request():
                await self.send(packet)
                return await self.replies[packet[0]].get()
            record = await asyncio.wait_for(request(), timeout)
            reply = record[3]
            if len(reply) != 16 or reply[0] != packet[0] or protocol.checksum(reply[:-1]) != reply[-1]:
                raise RuntimeError("Invalid reply; aborting diagnostics")
            return record
        except BaseException:
            # CD/CE have no address echo. Never retry or reuse a late response.
            self.poisoned = True
            raise
        finally:
            self.busy = False

    async def read_ram(self, name):
        address, length = RAM_READS[name]
        packet = protocol.make_packet(0xCD, bytes([1, length]) + address.to_bytes(4, "big"))
        t, wall, _, reply = await self.exchange(packet)
        value = reply[1:1 + length]
        self.emit("ram_read", name=name, t=t, wall=wall, value=value.hex())
        return value

    async def identify(self, base):
        samples = {}
        for site in fwidentity.read_sites():
            t, wall, _, reply = await self.exchange(fwidentity.read_packet(site))
            samples[site.name] = fwidentity.decode_reply(site, reply)
            self.emit("code_read", name=site.name, t=t, wall=wall, value=samples[site.name].hex())
        classification = fwidentity.classify(base, samples)
        self.emit("identity", classification=classification, scope="critical_sites_not_full_image")
        if classification != fwidentity.ORIGINAL_25HZ:
            raise RuntimeError("Battery workaround requires the original25Hz fingerprint; no start sent")

    async def battery(self):
        requested_at = self.now()
        t, wall, _, reply = await self.exchange(protocol.BATTERY_PACKET)
        level, charging = protocol.parse_battery(reply)
        if not 0 <= level <= 100 or reply[2] not in (0, 1):
            raise RuntimeError("Invalid battery reading")
        self.emit("battery", t=t, wall=wall, requested_t=requested_at,
                  percent=level, charging=charging)
        if charging:
            raise RuntimeError("Charging detected; battery test invalid")
        return level

    async def pause(self, seconds):
        deadline = self.now() + seconds
        while self.now() < deadline:
            if not self.client.is_connected:
                raise RuntimeError("Ring disconnected")
            await asyncio.sleep(min(1.0, max(0.0, deadline - self.now())))
            self.flush(durable=True)

    async def cleanup(self, raw_attempted, motion_attempted):
        self.phase = "cleanup"
        packets = list(protocol.STOP_RAW_SENSOR_PACKETS) if raw_attempted else []
        if motion_attempted:
            packets.append(motion_control_packet(False))
        errors = []
        restoration = "not_needed" if not motion_attempted else "unverified"
        for packet in packets:
            try:
                if (packet[0] == 0x3B and not self.poisoned
                        and not any(not q.empty() for q in self.replies.values())):
                    _, _, _, reply = await self.exchange(packet)
                    if reply != bytes(packet):
                        self.poisoned = True
                        raise RuntimeError("Unexpected motion-disable echo")
                    if await self.read_ram("motion_control") != b"\0\1\0":
                        raise RuntimeError("Motion-control restoration readback failed")
                    restoration = "verified_000100"
                else:
                    await self.send(packet)
                await asyncio.sleep(0.2)
            except Exception as exc:
                errors.append({"packet": bytes(packet).hex(), "error": str(exc)})
        self.emit("cleanup", errors=errors, restoration=restoration)
        return not errors


async def exercise(client, log, base, *, duration=600.0, poll_seconds=60.0,
                   stop_at=40, optical_stop=True):
    session = Session(client, log)
    raw_attempted = motion_attempted = subscribed = False
    reason = "error"
    try:
        await client.start_notify(protocol.UART_TX_CHAR_UUID, session.notify)
        subscribed = True
        await session.identify(base)
        if await session.read_ram("motion_control") != b"\0\1\0":
            raise RuntimeError("Motion-control state is not 000100; refusing to replace existing settings")
        if await session.battery() <= stop_at:
            raise RuntimeError("Battery already at/below safety floor; no start sent")
        session.phase = "setup_raw_and_mode3"
        raw_attempted = True
        await session.send(protocol.ENABLE_RAW_SENSOR)
        motion_attempted = True
        command = motion_control_packet(True)
        _, _, _, reply = await session.exchange(command)
        if reply[1:4] != command[1:4]:
            raise RuntimeError("Unexpected motion-control echo")
        await session.pause(5.0)
        if (await session.read_ram("accel_state"))[1] != 1:
            raise RuntimeError("Accelerometer FIFO consumer did not wake")
        if optical_stop:
            _, _, _, reply = await session.exchange(optical_stop_packet())
            # The audited CE02 STOP reply is CE followed by zeroes, not an
            # address echo or proof that the I2C write physically succeeded.
            if reply != bytes(protocol.make_packet(0xCE)):
                session.poisoned = True
                raise RuntimeError("Unexpected optical STOP reply")
        session.phase = "optical_stop_mode3" if optical_stop else "optical_on_mode3"
        begin = session.now()
        session.emit("phase", mode3=True, optical_stop=optical_stop,
                     led_darkness="human_observation_required", duration=duration,
                     stop_at=stop_at, poll_seconds=poll_seconds)
        deadline = begin + duration
        next_poll = begin  # timestamp the starting battery in the measured phase
        next_report = begin + WARMUP_S + WINDOW_S
        while True:
            now = session.now()
            if not client.is_connected:
                raise RuntimeError("Ring disconnected")
            health = stream_health(session.accel, begin, now)
            if health["ready"] and not health["passed"]:
                session.emit("stream_health", **health)
                raise RuntimeError("Stream rate/freshness check failed")
            if now >= next_report:
                session.emit("stream_health", **health)
                next_report = now + poll_seconds
            if now >= deadline:
                level = await session.battery()
                reason = "battery_floor" if level <= stop_at else "time_limit"
                break
            if now >= next_poll:
                level = await session.battery()
                if level <= stop_at:
                    reason = "battery_floor"
                    break
                if (await session.read_ram("accel_state"))[1] != 1:
                    raise RuntimeError("Accelerometer FIFO consumer became inactive")
                next_poll = session.now() + poll_seconds
            await session.pause(min(1.0, max(0.0, deadline - session.now())))
        session.emit("result", reason=reason, elapsed_s=session.now() - begin)
        return reason
    except BaseException as exc:
        session.emit("error", error=type(exc).__name__ + ": " + str(exc))
        raise
    finally:
        try:
            cleanup_ok = await session.cleanup(raw_attempted, motion_attempted)
            if not cleanup_ok and reason != "error":
                raise RuntimeError("Cleanup failed; log records attempted stop/restore commands")
        finally:
            if subscribed:
                try:
                    await asyncio.wait_for(client.stop_notify(protocol.UART_TX_CHAR_UUID), 3.0)
                finally:
                    session.flush(durable=True)


async def run(args):
    base = BASE.read_bytes()
    fwidentity.validate_images(base)  # Validate local references before any BLE.
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    interrupted = False

    def interrupt():
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            task.cancel()  # Finally blocks perform bounded, independent cleanup.

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, interrupt)
    path = Path(args.output) if args.output else Path("data/batterycheck") / f"battery_{time.time_ns()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x") as log:
            log.write(json.dumps({"kind": "header", "started_wall": time.time(),
                                  "arguments": vars(args), "flashing": False,
                                  "mode3": True, "freshness_window_s": WINDOW_S,
                                  "note": "Optical STOP is temporary; darkness needs observation"}) + "\n")
            log.flush()
            os.fsync(log.fileno())
            device = await capture.find_ring(address=args.address)
            async with capture.connected(device) as client:
                info = await capture.read_device_info(client, device)
                log.write(json.dumps({"kind": "device", "wall": time.time(), "device": info.as_dict()}) + "\n")
                log.flush()
                if (info.hardware != fwoptical.HARDWARE or
                        info.firmware != "RT02CR_3.12.07_260514"):
                    raise RuntimeError("Unexpected hardware/firmware family; no diagnostics sent")
                await exercise(client, log, base, duration=args.duration,
                               poll_seconds=args.poll_seconds, stop_at=args.stop_at,
                               optical_stop=args.optical_stop)
        return 0
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        print(f"Saved {path}. No flash performed.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--optical-stop", action="store_true", help="use audited temporary LED-off workaround")
    parser.add_argument("--duration", type=float, default=600.0, help="seconds; default 10 minutes, maximum 3 hours")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--stop-at", type=int, default=40, help="battery safety floor, at least 40 percent")
    parser.add_argument("--output", help="new JSONL path; existing files are never overwritten")
    args = parser.parse_args(argv)
    if (not math.isfinite(args.duration) or not 15 <= args.duration <= 10800
            or not math.isfinite(args.poll_seconds) or not 1 <= args.poll_seconds <= 60
            or not 40 <= args.stop_at < 100):
        parser.error("require finite 15 <= duration <= 10800, 1 <= poll-seconds <= 60, and 40 <= stop-at < 100")
    try:
        return asyncio.run(run(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 130
    except Exception as exc:
        print(f"Battery test stopped: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
