"""
Find an `A1` parameter that streams the accelerometer without lighting the LEDs.

`A1 04` powers the whole sensor front end. On the low-latency firmware the PPG
and SpO2 notifications are suppressed but their emitters still run, so every
capture burns a 17 mAh cell lighting LEDs whose data is discarded. The realtime
stop commands do not clear it on this firmware, and a charger tap only fixes it
after the fact.

If some other parameter starts motion alone, that fixes it permanently and makes
the battery figure honest.

The LED state cannot be read over BLE, so this needs a human watching. Each
parameter is announced, held long enough to observe, then stopped with a dark
gap before the next one.

    python -m probe.ledsweep

Note which parameters leave the ring dark, then confirm the winner with:

    python -m probe.stream --duration 60 --label accel_only --param 0xNN
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from whip import analyze, capture, protocol

# 0x01, 0x04 and 0x06 all streamed on stock firmware. The rest is unexplored.
DEFAULT_PARAMS = [0x01, 0x04, 0x06, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F]


def parse_params(spec: str) -> list[int]:
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


async def run(args: argparse.Namespace) -> int:
    params = parse_params(args.params) if args.params else DEFAULT_PARAMS
    device = await capture.find_ring(address=args.address, timeout=args.timeout)

    results: list[tuple[int, float, int]] = []

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        battery = await capture.read_battery(client)
        print(f"device   {info.name}  fw {info.firmware}")
        if battery:
            print(f"battery  {battery[0]}%")
        print(f"\n{len(params)} parameters, {args.dwell:.0f}s each with a {args.gap:.0f}s dark gap between.")
        print(f"About {len(params) * (args.dwell + args.gap) / 60:.1f} minutes.\n")
        print("WATCH THE RING. Note which parameters leave it DARK.\n")
        await asyncio.sleep(3)

        for param in params:
            print(f"  >>> PARAM 0x{param:02x}  --  WATCH NOW", flush=True)
            records: list[tuple[float, bytes]] = []
            t0 = time.perf_counter()

            def on_notify(_s, data: bytearray) -> None:
                records.append((time.perf_counter() - t0, bytes(data)))

            await client.start_notify(protocol.UART_TX_CHAR_UUID, on_notify)
            await client.write_gatt_char(
                protocol.UART_RX_CHAR_UUID, protocol.raw_sensor_packet(param), response=False
            )
            await asyncio.sleep(args.dwell)
            for stop in protocol.STOP_RAW_SENSOR_PACKETS:
                await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, stop, response=False)
                await asyncio.sleep(0.15)
            await client.stop_notify(protocol.UART_TX_CHAR_UUID)

            stats = analyze.analyze(records, duration_s=args.dwell)
            results.append((param, stats.accel_rate_hz, stats.total_packets))
            print(f"      stopped. accel {stats.accel_rate_hz:6.2f} Hz, {stats.total_packets} packets")
            print(f"      ...dark gap {args.gap:.0f}s...\n", flush=True)
            await asyncio.sleep(args.gap)

    print("=" * 58)
    print("  RESULTS -- pair these with what you saw")
    print("=" * 58)
    print(f"  {'param':>6}  {'accel Hz':>9}  {'packets':>8}  usable?")
    for param, rate, packets in results:
        usable = "yes" if rate >= 25 else ("slow" if rate > 0 else "no data")
        print(f"  0x{param:02x}    {rate:9.2f}  {packets:8d}  {usable}")

    print("\n  A parameter that is both usable and left the ring dark is the win.")
    print("  Confirm it with a longer capture, then use it everywhere:")
    print("    python -m probe.stream --duration 60 --label accel_only --param 0xNN")
    print("\n  If every usable parameter lit the LEDs, the emitters are tied to the")
    print("  raw-sensor path in firmware and a charger tap stays the only remedy.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Find an A1 parameter that streams motion without the LEDs")
    parser.add_argument("--params", help="e.g. '0x01,0x04' or '0x00-0x0f'")
    parser.add_argument("--dwell", type=float, default=6.0, help="seconds to hold each parameter")
    parser.add_argument("--gap", type=float, default=4.0, help="dark seconds between parameters")
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
