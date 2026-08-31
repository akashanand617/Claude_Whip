"""
Find the ring and report what it is.

Run this first. It answers the questions that everything else depends on:
does the ring connect, what firmware is on it, and how much battery is left.

    python -m probe.scan
    python -m probe.scan --address <uuid-or-mac>
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from bleak import BleakScanner

from whip import capture, protocol


async def run(address: str | None, name: str | None, timeout: float, show_all: bool) -> int:
    if show_all:
        print(f"scanning for {timeout:.0f}s, showing everything...\n")
        for device in await BleakScanner.discover(timeout=timeout):
            marker = "  <-- ring" if device.name and device.name.startswith(protocol.KNOWN_RING_NAMES) else ""
            print(f"  {device.name or '(unnamed)':<24} {device.address}{marker}")
        return 0

    device = await capture.find_ring(address=address, name=name, timeout=timeout)
    print(f"found {device.name} at {device.address}")

    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"  firmware   {info.firmware}")
        print(f"  hardware   {info.hardware}")

        battery = await capture.read_battery(client)
        if battery is None:
            print("  battery    (no reply)")
        else:
            level, charging = battery
            print(f"  battery    {level}%{' (charging)' if charging else ''}")

    print("\nRecord the firmware string. Rings that look identical ship different")
    print("firmware, and it is the first thing that explains a rate difference.")
    print(f"\nNext:  python -m probe.stream --duration 60 --label idle --address {device.address}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Find a Colmi ring and report its identity")
    parser.add_argument("--address", help="connect directly instead of scanning")
    parser.add_argument("--name", help="match on advertised name")
    parser.add_argument("--timeout", type=float, default=10.0, help="scan duration in seconds")
    parser.add_argument("--all", action="store_true", dest="show_all", help="list every BLE device, do not connect")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, format="%(levelname)s: %(message)s")

    try:
        return asyncio.run(run(args.address, args.name, args.timeout, args.show_all))
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
