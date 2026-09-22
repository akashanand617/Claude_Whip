"""
Hunt for gesture events and for a rate parameter hiding in the sub-data.

Two questions, both unanswered by the raw-streaming work:

1. Does the ring emit tap/flick events on its own? The STK8321 has hardware tap
   detection, Gadgetbridge's notes imply the protocol has "tap and wave" commands
   nobody has wired up, and this repo's upstream README lists "gestures
   (maybe...?)". If the ring detects a flick itself, the 25 Hz streaming
   requirement disappears -- we would not need raw samples at all.

2. Is the sample rate a *second* parameter? probe/sweep.py varied byte 1 of
   `A1 <param>`. A packet has 14 sub-data bytes and only the first was tried.

    python -m probe.gestures

Deliberately not done here: sweeping the whole command byte space. Command bytes
have destructive semantics in this protocol -- reboot and factory reset live in
there -- and firing blind at 256 opcodes to see what answers is not worth
wiping the ring. Everything below is either passive or confined to the 0xA1
family, whose behaviour is understood.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections import Counter
from pathlib import Path

from whip import analyze, capture, protocol

DATA_DIR = Path("data/gestures")

# Second GATT service on the ring, seen in the GATT dump. Unexplored.
TENCENT_NOTIFY = "0000fea1-0000-1000-8000-00805f9b34fb"

RATE_VALUES = [0x00, 0x01, 0x02, 0x04, 0x05, 0x08, 0x0A, 0x20, 0x32, 0x64]


async def listen_for_gestures(client, seconds: float) -> list[tuple[float, str, bytes]]:
    """Subscribe to every notify characteristic and record unsolicited traffic."""
    events: list[tuple[float, str, bytes]] = []
    t0 = time.perf_counter()

    def make_handler(source: str):
        def handler(_s, data: bytearray) -> None:
            events.append((time.perf_counter() - t0, source, bytes(data)))

        return handler

    subscribed = []
    for uuid, label in ((protocol.UART_TX_CHAR_UUID, "uart"), (TENCENT_NOTIFY, "fee7")):
        try:
            await client.start_notify(uuid, make_handler(label))
            subscribed.append(uuid)
        except Exception as exc:  # noqa: BLE001 - the second service may not notify
            print(f"    (could not subscribe to {label}: {exc})")

    print(f"    subscribed to {len(subscribed)} characteristic(s), sending no commands\n")
    print("    >>> TAP the ring hard. Double-tap. Flick your wrist. Keep going. <<<\n")

    for remaining in range(int(seconds), 0, -1):
        await asyncio.sleep(1)
        print(f"      {remaining:2d}s left   events so far: {len(events)}", end="\r", flush=True)
    print(" " * 50, end="\r")

    for uuid in subscribed:
        try:
            await client.stop_notify(uuid)
        except Exception:  # noqa: BLE001, S110 - teardown only
            pass

    return events


async def sweep_subdata(client, position: int, dwell: float) -> list[tuple[int, analyze.StreamStats]]:
    """Vary one sub-data byte of the enable command and measure the accel rate."""
    results = []
    for value in RATE_VALUES:
        sub = bytearray(protocol.PACKET_SIZE - 2)
        sub[0] = protocol.RAW_ENABLE_ALL
        sub[position - 1] = value
        packet = protocol.make_packet(protocol.CMD_RAW_SENSOR, sub)

        records: list[tuple[float, bytes]] = []
        t0 = time.perf_counter()

        def on_notify(_s, data: bytearray) -> None:
            records.append((time.perf_counter() - t0, bytes(data)))

        await client.start_notify(protocol.UART_TX_CHAR_UUID, on_notify)
        await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
        await asyncio.sleep(dwell)
        for stop in protocol.STOP_RAW_SENSOR_PACKETS:
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, stop, response=False)
            await asyncio.sleep(0.15)
        await client.stop_notify(protocol.UART_TX_CHAR_UUID)

        stats = analyze.analyze(records, duration_s=dwell)
        results.append((value, stats))
        print(f"    A1 04 [{position}]={value:#04x}   {stats.accel_rate_hz:6.2f} Hz   {stats.total_packets:4d} packets")
        await asyncio.sleep(1.0)

    return results


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, timeout=args.timeout)

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"device   {info.name}  fw {info.firmware}\n")

        print("=" * 62)
        print("  PHASE 1 -- passive listen for gesture events")
        print("=" * 62)
        events = await listen_for_gestures(client, args.listen)

        print(f"    captured {len(events)} unsolicited packets")
        if events:
            kinds = Counter((src, p[0] if p else -1) for _, src, p in events)
            for (src, opcode), n in kinds.most_common():
                print(f"      {src}  opcode {opcode:#04x}  x{n}")
            print("\n    first 12:")
            for t, src, payload in events[:12]:
                print(f"      {t:6.2f}s  {src:<5} {payload.hex()}")
        else:
            print("    none. The ring sends nothing unless asked.")

        print()
        print("=" * 62)
        print(f"  PHASE 2 -- is the rate in sub-data byte {args.position}?")
        print("=" * 62)
        results = await sweep_subdata(client, args.position, args.dwell)

    baseline = next((s.accel_rate_hz for v, s in results if v == 0x00), None)
    best = max(results, key=lambda r: r[1].accel_rate_hz)
    print()
    print(f"  baseline {baseline:.2f} Hz, best {best[1].accel_rate_hz:.2f} Hz at {best[0]:#04x}")
    if baseline and best[1].accel_rate_hz > baseline * 1.5:
        print("  *** sub-data byte affects the rate -- follow up with a longer capture")
    else:
        print(f"  sub-data byte {args.position} does not set the rate")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Hunt for gesture events and a hidden rate parameter")
    parser.add_argument("--listen", type=float, default=25.0, help="seconds of passive listening")
    parser.add_argument("--position", type=int, default=2, help="sub-data byte to sweep")
    parser.add_argument("--dwell", type=float, default=6.0, help="seconds per sub-data value")
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
