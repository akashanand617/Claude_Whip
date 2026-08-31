"""
Capture a raw accelerometer stream and decide the M0 gate.

    python -m probe.stream --duration 60  --label idle
    python -m probe.stream --duration 600 --label typing    # the real gate: 10 min

For the "idle" capture, leave the ring flat and still on the desk. That capture
is what lets us verify the 12 bit unpacking, because a stationary ring measures
only gravity and the correct decode is the one that holds magnitude constant.

For the gate itself, wear the ring and type normally for 10 minutes. A rate
measured on a motionless ring is not the rate you get in use.

Captures are written to data/raw/ as JSONL and can be re-analysed at any time
with probe/report.py -- no need to recapture to try a new idea.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from whip import analyze, capture, protocol

DATA_DIR = Path("data/raw")


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, name=args.name, timeout=args.timeout)

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        battery_before = await capture.read_battery(client)

        stamp = time.strftime("%Y%m%d_%H%M%S")
        sink = Path(args.out) if args.out else DATA_DIR / f"{args.label}_{stamp}.jsonl"

        rec = capture.Capture(
            device=info,
            started_wall=time.time(),
            param=args.param,
            label=args.label,
            notes={"battery_before": battery_before[0] if battery_before else None},
        )

        print(f"device      {info.name}  fw {info.firmware}")
        if battery_before:
            print(f"battery     {battery_before[0]}%")
        print(f"param       0x{args.param:02x}")
        print(f"capturing   {args.duration:.0f}s -> {sink}")
        print()

        progress = asyncio.create_task(_progress(rec.records, args.duration))
        try:
            await capture.stream(client, args.duration, param=args.param, sink=sink, capture=rec)
        finally:
            progress.cancel()

        battery_after = await capture.read_battery(client)
        if battery_before and battery_after:
            print(f"\nbattery     {battery_before[0]}% -> {battery_after[0]}%")

    print()
    stats = analyze.analyze(rec.records, duration_s=args.duration)

    payloads = None
    if args.stationary:
        payloads = [p for _, p in rec.records if len(p) >= 8 and p[0] == protocol.CMD_RAW_SENSOR and p[1] == protocol.SUBTYPE_ACCEL]

    print(analyze.format_report(stats, header=rec.header(), payloads=payloads))
    print(f"\ncapture saved to {sink}")
    return 0 if stats.passes_gate else 2


async def _progress(records: list, duration: float) -> None:
    """Live rate readout so a ten minute capture is not a blank screen."""
    start = time.perf_counter()
    last_count = 0
    while True:
        await asyncio.sleep(5.0)
        elapsed = time.perf_counter() - start
        count = len(records)
        recent = (count - last_count) / 5.0
        last_count = count
        remaining = max(0.0, duration - elapsed)
        print(f"  [{elapsed:6.0f}s] {count:7d} packets   {recent:6.1f}/s now   {remaining:.0f}s left")


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture raw sensor stream from a Colmi ring")
    parser.add_argument("--duration", type=float, default=60.0, help="capture length in seconds")
    parser.add_argument("--label", default="capture", help="short name for this capture, used in the filename")
    parser.add_argument("--address", help="connect directly instead of scanning")
    parser.add_argument("--name", help="match on advertised name")
    parser.add_argument("--timeout", type=float, default=10.0, help="scan duration")
    parser.add_argument(
        "--param",
        type=lambda v: int(v, 0),
        default=protocol.RAW_ENABLE_ALL,
        help="0xA1 parameter byte. 0x04 is the known enable-everything value.",
    )
    parser.add_argument("--out", help="explicit output path")
    parser.add_argument(
        "--stationary",
        action="store_true",
        help="ring was motionless: also rank the candidate 12 bit unpackers",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted -- partial capture is on disk")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
