"""
Probe the 0xA1 parameter byte space for an accelerometer-only streaming mode.

This is the highest value experiment available before touching firmware.

The one known-working enable command, 0xA1 0x04, turns on all three raw streams:
SpO2, PPG and accelerometer. They share a single notification channel, so if
accel is only a third of the traffic, roughly two thirds of the available
bandwidth is being spent on sensors this project does not use. If some other
parameter byte enables accel alone, the accelerometer rate could rise by a large
multiple with no firmware change and no new hardware.

0x04 starts and 0x02 stops. Every other value is unexplored.

    python -m probe.sweep                      # the safe default set
    python -m probe.sweep --params 0x00-0x0f   # a wider range
    python -m probe.sweep --dwell 15           # longer listen per parameter

Safety: after every probe the sweep sends the known disable command and waits,
so the ring is never left in an unknown streaming state. Unknown command
parameters are still unknown -- if the ring stops responding, take it off the
charger, let it idle, and reconnect. Nothing here writes flash.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from whip import analyze, capture, protocol

DATA_DIR = Path("data/sweep")

# Values worth trying first: the immediate neighbourhood of the known enable,
# on the theory that the parameter is an enum of stream selections.
DEFAULT_PARAMS = [0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]

SETTLE_S = 2.0


def parse_params(spec: str) -> list[int]:
    """Accept '0x01,0x03' or '0x00-0x0f' or a mix."""
    values: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk[1:]:
            idx = chunk.index("-", 1)
            lo, hi = int(chunk[:idx], 0), int(chunk[idx + 1 :], 0)
            values.extend(range(lo, hi + 1))
        else:
            values.append(int(chunk, 0))
    return values


async def probe_one(client, param: int, dwell: float, sink: Path | None) -> analyze.StreamStats:
    """Enable with `param`, listen for `dwell` seconds, disable, return stats."""
    records = await capture.stream(client, dwell, param=param, sink=sink)
    return analyze.analyze(records, duration_s=dwell)


async def run(args: argparse.Namespace) -> int:
    params = parse_params(args.params) if args.params else DEFAULT_PARAMS
    device = await capture.find_ring(address=args.address, name=args.name, timeout=args.timeout)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    results: list[tuple[int, analyze.StreamStats]] = []

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"device   {info.name}  fw {info.firmware}")
        print(f"probing  {len(params)} parameters at {args.dwell:.0f}s each")
        print(f"         about {len(params) * (args.dwell + SETTLE_S) / 60:.1f} minutes total\n")

        print(f"  {'param':>6}  {'packets':>8}  {'accel Hz':>9}  {'accel %':>8}  channels")
        print(f"  {'-' * 6}  {'-' * 8}  {'-' * 9}  {'-' * 8}  {'-' * 24}")

        for param in params:
            sink = DATA_DIR / f"sweep_{stamp}_p{param:02x}.jsonl" if args.save else None
            try:
                stats = await probe_one(client, param, args.dwell, sink)
            except Exception as exc:  # noqa: BLE001 - a dud parameter must not end the sweep
                print(f"  0x{param:02x}    error: {exc}")
                await asyncio.sleep(SETTLE_S)
                continue

            results.append((param, stats))
            channels = ", ".join(f"{s.name}:{s.count}" for s in stats.subtypes) or "(silence)"
            accel_share = next((s.share for s in stats.subtypes if s.subtype == protocol.SUBTYPE_ACCEL), 0.0)
            print(
                f"  0x{param:02x}    {stats.total_packets:8d}  {stats.accel_rate_hz:9.2f}"
                f"  {accel_share * 100:7.1f}%  {channels}"
            )

            # Make sure the ring is quiet before the next parameter, so traffic
            # from one probe cannot be attributed to the next.
            await asyncio.sleep(SETTLE_S)

    print()
    if not results:
        print("no parameter produced a response.")
        return 1

    baseline = next((s for p, s in results if p == protocol.RAW_ENABLE_ALL), None)
    best = max(results, key=lambda r: r[1].accel_rate_hz)

    print(f"best accel rate: 0x{best[0]:02x} at {best[1].accel_rate_hz:.2f} Hz")
    if baseline and best[0] != protocol.RAW_ENABLE_ALL and baseline.accel_rate_hz > 0:
        gain = best[1].accel_rate_hz / baseline.accel_rate_hz
        print(f"that is {gain:.2f}x the known enable command (0x04 at {baseline.accel_rate_hz:.2f} Hz)")
        if gain > 1.2:
            print(f"\nWorth a longer confirmation run:")
            print(f"  python -m probe.stream --duration 600 --label typing --param 0x{best[0]:02x}")
    elif baseline:
        print("no parameter beat the known enable command. If the rate is still")
        print("under 25 Hz, the next lever is the modified firmware.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the 0xA1 parameter space for an accel-only mode")
    parser.add_argument("--params", help="e.g. '0x01,0x03,0x05' or '0x00-0x0f'")
    parser.add_argument("--dwell", type=float, default=10.0, help="seconds to listen per parameter")
    parser.add_argument("--address", help="connect directly instead of scanning")
    parser.add_argument("--name", help="match on advertised name")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--save", action="store_true", help="keep the raw capture for each parameter")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
