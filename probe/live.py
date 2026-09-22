"""
Live gesture tracking, headless.

    python -m probe.live
    python -m probe.live --threshold 0.5 --checkpoint data/model.pt

Connects to the ring, streams, and prints every detected gesture with its
resolved action. Events are appended to data/live/events_<stamp>.jsonl -- the
artifact the preference-labeling loop consumes. Ctrl-C stops cleanly.

This is the web frontend minus the browser: if this works, the server's job is
only transport.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import logging
import time
from pathlib import Path

from whip import capture, protocol
from whip.realtime import Engine, EventLog, RouterConfig


async def run(args: argparse.Namespace) -> int:
    config = RouterConfig.load()
    threshold = args.threshold if args.threshold is not None else config.threshold
    engine = Engine.from_checkpoint(args.checkpoint, threshold=threshold)
    log = EventLog()

    print(f"model       {args.checkpoint}  classes {', '.join(engine.labels)}")
    print(f"threshold   {threshold:.2f}")
    print(f"mappings    {config.mappings or '(none)'}")
    print(f"event log   {log.path}")

    device = await capture.find_ring(address=args.address, timeout=args.timeout)
    stop = asyncio.Event()
    # The callback only appends; the engine drains from here in its own task.
    queue: collections.deque = collections.deque()

    async def consume() -> None:
        packets = 0
        started = time.perf_counter()
        while not stop.is_set():
            drained = False
            while queue:
                t, payload = queue.popleft()
                drained = True
                packets += 1
                before = engine.frame_name
                for event in engine.feed(t, payload):
                    action = config.action_for(event)
                    log.write(event, action)
                    tag = f" -> {action.upper()}" if action else ""
                    print(f"  [{event.t_s:8.2f}s] {event.name:<13} "
                          f"dir={event.direction:<6} conf={event.confidence:.2f}{tag}",
                          flush=True)
                if engine.frame_name != before:
                    print(f"  [{t:8.2f}s] ring frame -> {engine.frame_name} (fingers-down pose seen)", flush=True)
            if not drained:
                await asyncio.sleep(0.05)
            if packets and packets % 1500 == 0:
                rate = packets / (time.perf_counter() - started)
                print(f"  ... {packets} packets, {rate:.1f}/s", flush=True)

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        battery = await capture.read_battery(client)
        print(f"connected   {info.name}  fw {info.firmware}"
              + (f"  battery {battery[0]}%" if battery else ""))
        print("streaming -- let the arm hang (fingers at the floor) for 2 s once so the ring frame is known; then gestures; Ctrl-C to stop\n")

        consumer = asyncio.create_task(consume())
        try:
            await capture.stream(client, duration=0, stop=stop,
                                 param=protocol.RAW_ENABLE_ALL,
                                 on_record=queue.append)
        finally:
            stop.set()
            await consumer
            for event in engine.finish():
                log.write(event, config.action_for(event))
            log.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live gesture tracking without the browser")
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--threshold", type=float, default=None,
                        help="detection threshold; default from data/app_config.json")
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nstopped -- events are on disk")
        return 0
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
