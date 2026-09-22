"""
Does any command turn the ring's optical emitters off?

Historical health-command probe. The dedicated raw stop is A1 05; it also
stops motion. LED-off tracking is tested separately by probe.ledcheck.
69 01 04 was previously mislabeled as HR stop: the firmware starts HR on
that path. The corrected 69 06 04 disables HR and stops its report timer.

This drives health commands without raw streaming. Background schedules and
indicators can still affect the observed LEDs:

    start heart rate   69 01 01     expect the green LED to light
    stop heart rate    69 06 04     expect it to go out if HR was the only owner
    stop realtime HR   6a 01 00 00
    start blood oxygen 69 03 01     expect the red LED
    stop realtime SpO2 6a 03 00 00

    python -m probe.ledtest

Watch the ring and note what each step does. What we learn:

  - if start lights it and stop darkens it, the off-switch works and raw mode is
    overriding it -- worth patching the raw path
  - if stop never darkens it, these are the wrong opcodes and searching the
    firmware for an LED enable is aimed at the wrong thing
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from whip import capture, protocol

STEPS = [
    ("start heart rate", 0x69, bytes([0x01, 0x01]), "green LED should LIGHT"),
    ("stop heart rate", 0x69, bytes([0x06, 0x04]), "HR emitter should stop if no other owner"),
    ("stop realtime HR", 0x6A, bytes([0x01, 0x00, 0x00]), "if still lit, should GO OUT now"),
    ("start blood oxygen", 0x69, bytes([0x03, 0x01]), "red LED should LIGHT"),
    ("stop realtime SpO2", 0x6A, bytes([0x03, 0x00, 0x00]), "red LED should GO OUT"),
]


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, timeout=args.timeout)

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"device   {info.name}  fw {info.firmware}\n")

        replies: list[bytes] = []

        def on_notify(_s, data: bytearray) -> None:
            replies.append(bytes(data))

        await client.start_notify(protocol.UART_TX_CHAR_UUID, on_notify)

        # Make sure raw streaming is off, so only these commands are in play.
        for stop in protocol.STOP_RAW_SENSOR_PACKETS:
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, stop, response=False)
            await asyncio.sleep(0.15)
        print("raw streaming stopped (A1 05 + A1 02). Watch the ring.\n")
        await asyncio.sleep(2)

        for name, command, sub, expectation in STEPS:
            replies.clear()
            packet = protocol.make_packet(command, sub)
            print(f"  >>> {name:<20} {packet[:4].hex()}...   {expectation}", flush=True)
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
            await asyncio.sleep(args.dwell)
            if replies:
                print(f"      ring replied: {', '.join(r[:4].hex() for r in replies[:3])}")
            else:
                print("      no reply")
            print(flush=True)

        await client.stop_notify(protocol.UART_TX_CHAR_UUID)

    print("Report what you saw at each step.")
    print("  stop darkened it  -> the off-switch works; raw mode overrides it")
    print("  never darkened    -> wrong opcodes; the firmware search needs a different target")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Test whether any command turns the optical emitters off")
    parser.add_argument("--dwell", type=float, default=6.0, help="seconds to hold each step")
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
