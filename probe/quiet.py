"""
Turn the ring's optical sensors off.

`A1 04` enables sensor bit 0x800 and starts the optical front end in raw mode;
`A1 02` only clears bit 0x40, so after a capture stopped that way the sensor
kept running and the LEDs stayed lit until a power cycle. `A1 05` is the stop
that matches `A1 04`: it clears 0x800 and, with no bit left set, the firmware
stops the optical sensor itself. This sends both stops, then the health-command
stops for good measure.

Run this any time the ring is visibly lit when idle.

    python -m probe.quiet
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from whip import capture, protocol


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, timeout=args.timeout)

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        before = await capture.read_battery(client)
        print(f"device   {info.name}  fw {info.firmware}")
        if before:
            print(f"battery  {before[0]}%")

        for packet in protocol.STOP_RAW_SENSOR_PACKETS:
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
            await asyncio.sleep(0.2)
            print(f"sent     {packet[:2].hex()}  (raw sensor stop)")

        for packet in protocol.DISABLE_LOGGING_PACKETS:
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
            await asyncio.sleep(0.4)
            print(f"sent     {packet[:4].hex()}...  (disable periodic logging)")

        for packet in protocol.QUIET_SENSOR_PACKETS:
            await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
            await asyncio.sleep(0.3)
            print(f"sent     {packet[:4].hex()}...")

    print("\nThe LED should be off. If it is still lit, take the ring off the")
    print("charger and leave it idle for a minute -- some states clear on their own.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop the ring's optical sensors and LED")
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
