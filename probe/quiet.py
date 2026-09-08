"""
Turn the ring's optical sensors off.

Stopping the raw stream does not stop the LED. `A1 04` powers the PPG and SpO2
front end, and the low-latency firmware only suppresses their *notifications* --
the sensor and its green LED keep running, burning a 17 mAh cell for data that
is being thrown away.

Run this after any capture, and any time the ring is visibly lit when idle.

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

        await client.write_gatt_char(
            protocol.UART_RX_CHAR_UUID, protocol.DISABLE_RAW_SENSOR, response=False
        )
        print("sent     raw sensor disable")

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
