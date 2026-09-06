"""
Probe the sub-data bytes of the raw sensor enable command.

probe/sweep.py varied byte 1 of `A1 <param>` and found nothing above 1 Hz. But a
16 byte packet has 14 bytes of sub-data and only the first was ever tried. If the
sample rate is a second parameter -- `A1 04 <rate>` -- it has been sitting in
plain sight the whole time.

    python -m probe.subdata                    # sweep byte 2 with the known enable
    python -m probe.subdata --position 3       # sweep byte 3 instead
    python -m probe.subdata --param 0x06       # use a different byte-1 value

Every probe is bracketed by the known disable command, so the ring is never left
streaming in an unknown configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

from whip import analyze, capture, protocol

DATA_DIR = Path("data/subdata")
SETTLE_S = 1.5

# Values chosen to cover plausible encodings of a rate: small dividers, powers of
# two, and literal Hz values.
DEFAULT_VALUES = [0x00, 0x01, 0x02, 0x04, 0x08, 0x0A, 0x10, 0x19, 0x20, 0x32, 0x64, 0xFF]


def parse_values(spec: str) -> list[int]:
    values: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk[1:]:
            idx = chunk.index("-", 1)
            values.extend(range(int(chunk[:idx], 0), int(chunk[idx + 1 :], 0) + 1))
        else:
            values.append(int(chunk, 0))
    return values


def build(param: int, position: int, value: int) -> bytearray:
    """`A1 <param> ... <value at `position`> ...` as a well formed packet."""
    sub = bytearray(protocol.PACKET_SIZE - 2)
    sub[0] = param
    sub[position - 1] = value
    return protocol.make_packet(protocol.CMD_RAW_SENSOR, sub)


async def run(args: argparse.Namespace) -> int:
    values = parse_values(args.values) if args.values else DEFAULT_VALUES
    device = await capture.find_ring(address=args.address, timeout=args.timeout)

    baseline: float | None = None
    results: list[tuple[int, analyze.StreamStats]] = []

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"device   {info.name}  fw {info.firmware}")
        print(f"sweeping byte {args.position} of A1 {args.param:#04x}, {len(values)} values at {args.dwell:.0f}s\n")
        print(f"  {'packet':<26} {'accel Hz':>9}  {'total':>6}  channels")
        print(f"  {'-' * 26} {'-' * 9}  {'-' * 6}  {'-' * 30}")

        for value in values:
            packet = build(args.param, args.position, value)
            records: list[tuple[float, bytes]] = []
            t0 = time.perf_counter()

            def on_notify(_s, data: bytearray) -> None:
                records.append((time.perf_counter() - t0, bytes(data)))

            await client.start_notify(protocol.UART_TX_CHAR_UUID, on_notify)
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
            await asyncio.sleep(args.dwell)
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, protocol.DISABLE_RAW_SENSOR, response=False)
            await client.stop_notify(protocol.UART_TX_CHAR_UUID)

            stats = analyze.analyze(records, duration_s=args.dwell)
            results.append((value, stats))
            if value == 0x00:
                baseline = stats.accel_rate_hz

            channels = ", ".join(f"{s.name}:{s.count}" for s in stats.subtypes) or "(silence)"
            label = f"A1 {args.param:02x} .. {value:02x}"
            print(f"  {label:<26} {stats.accel_rate_hz:9.2f}  {stats.total_packets:6d}  {channels}")

            await asyncio.sleep(SETTLE_S)

    print()
    best = max(results, key=lambda r: r[1].accel_rate_hz)
    print(f"best: value {best[0]:#04x} at {best[1].accel_rate_hz:.2f} Hz")

    if baseline and best[1].accel_rate_hz > baseline * 1.5:
        print(f"\n  *** {best[1].accel_rate_hz / baseline:.1f}x over baseline -- confirm with a longer run:")
        print(f"      python -m probe.stream --duration 120 --label subdata_win")
    else:
        print("nothing beats the baseline. Byte", args.position, "does not set the rate.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep sub-data bytes of the raw sensor enable command")
    parser.add_argument("--position", type=int, default=2, help="which sub-data byte to vary (2 = the byte after param)")
    parser.add_argument("--param", type=lambda v: int(v, 0), default=protocol.RAW_ENABLE_ALL)
    parser.add_argument("--values", help="e.g. '0x00-0x0f' or '0x01,0x32'")
    parser.add_argument("--dwell", type=float, default=8.0)
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
