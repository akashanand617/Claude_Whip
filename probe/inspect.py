"""Connect to one BLE address and list GATT services without writing commands."""

from __future__ import annotations

import argparse
import asyncio

from bleak import BleakClient, BleakScanner


async def run(address: str, timeout: float) -> int:
    device = await BleakScanner.find_device_by_address(address, timeout=timeout)
    if device is None:
        raise RuntimeError(f"no advertisement found for {address}")

    print(f"found {device.name or '(unnamed)'} at {device.address}")
    async with BleakClient(device, timeout=timeout) as client:
        for service in client.services:
            print(f"  service {service.uuid}  {service.description}")
            for characteristic in service.characteristics:
                properties = ",".join(characteristic.properties)
                print(f"    characteristic {characteristic.uuid}  {properties}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List a BLE device's services without sending commands"
    )
    parser.add_argument("--address", required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args.address, args.timeout))
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
