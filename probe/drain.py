"""
Measure battery life under continuous streaming.

The ring carries a 17 mAh cell. Continuous BLE notification traffic plus a live
accelerometer is the worst case load it will ever see, and the runtime it gives
decides what the ring can be used for:

  - a one hour calibration session (Phase A) needs about 90 minutes of headroom
  - all-day passive capture (Phase B, v2) needs eight hours and probably will
    not get them

    python -m probe.drain                     # run until the ring dies
    python -m probe.drain --max-hours 2

Battery is polled between capture chunks rather than during them, because a
battery request shares the notification channel with the sensor stream and would
otherwise show up as a stall in the rate measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import time
from pathlib import Path

from whip import analyze, capture

DATA_DIR = Path("data/drain")


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, name=args.name, timeout=args.timeout)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = DATA_DIR / f"drain_{stamp}.csv"

    started = time.time()
    deadline = started + args.max_hours * 3600 if args.max_hours else None
    first_level: int | None = None

    with log_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["elapsed_s", "battery_pct", "charging", "accel_hz", "implied_loss"])

        async with capture.connected(device) as client:
            info = await capture.read_device_info(client, device)
            print(f"device   {info.name}  fw {info.firmware}")
            print(f"logging  {log_path}")
            print(f"chunk    {args.chunk:.0f}s of streaming between battery polls\n")
            print(f"  {'elapsed':>9}  {'battery':>7}  {'accel Hz':>9}  {'loss':>6}")
            print(f"  {'-' * 9}  {'-' * 7}  {'-' * 9}  {'-' * 6}")

            while True:
                battery = await capture.read_battery(client)
                if battery is None:
                    print("  battery poll failed, stopping")
                    break

                level, charging = battery
                if charging:
                    print("  ring is charging -- take it off the charger for a valid measurement")
                    return 1
                if first_level is None:
                    first_level = level

                records = await capture.stream(client, args.chunk)
                stats = analyze.analyze(records, duration_s=args.chunk)

                elapsed = time.time() - started
                writer.writerow(
                    [round(elapsed, 1), level, int(charging), round(stats.accel_rate_hz, 2), round(stats.implied_loss, 4)]
                )
                f.flush()

                print(
                    f"  {elapsed / 60:7.1f}m  {level:6d}%  {stats.accel_rate_hz:9.2f}  {stats.implied_loss * 100:5.1f}%"
                )

                if level <= args.stop_at:
                    print(f"\nreached {args.stop_at}%, stopping")
                    break
                if deadline and time.time() >= deadline:
                    print("\nreached time limit")
                    break

    elapsed_h = (time.time() - started) / 3600
    print(f"\nran {elapsed_h:.2f} h")
    if first_level is not None and battery is not None:
        used = first_level - battery[0]
        print(f"used {used}% of battery")
        if used > 0:
            print(f"projected full-charge runtime: {elapsed_h / used * 100:.1f} h")
            print(f"\nA one hour calibration session needs ~1.5 h of runtime.")
            print(f"All-day passive capture needs ~8 h and is the thing most likely to fail here.")
    print(f"log: {log_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure ring battery life under continuous streaming")
    parser.add_argument("--chunk", type=float, default=120.0, help="seconds of streaming between battery polls")
    parser.add_argument("--max-hours", type=float, default=0.0, help="stop after this long, 0 for no limit")
    parser.add_argument("--stop-at", type=int, default=5, help="stop when battery reaches this percent")
    parser.add_argument("--address", help="connect directly instead of scanning")
    parser.add_argument("--name", help="match on advertised name")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted -- partial log is on disk")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
