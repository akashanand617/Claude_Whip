"""Low-level, no-write BLE reachability tool for R02 recovery.

Examples (Linux with a dedicated USB BLE adapter):

    python -m probe.ble_recovery doctor
    sudo python -m probe.ble_recovery scan --adapter 1 --seconds 60 --execute
    sudo python -m probe.ble_recovery recover --adapter 1 \
        --address 30:32:41:33:CC:07 --seconds 90 --execute

``recover`` links only when the exact address was observed as connectable in
the same process.  It disconnects immediately and sends no GATT or ring data.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import shutil
import sys
from dataclasses import asdict

from whip.ble_recovery import ADDRESS_TYPE_NAME, HCIError, RawHCI


def doctor() -> int:
    adapters = sorted(glob.glob("/sys/class/bluetooth/hci*")) if sys.platform.startswith("linux") else []
    report = {
        "platform": sys.platform,
        "raw_hci_supported": sys.platform.startswith("linux"),
        "adapters": [os.path.basename(item) for item in adapters],
        "tools": {name: shutil.which(name) for name in ("btmgmt", "bluetoothctl", "hcitool")},
        "scope": "advertisement inventory and exact-address link test only",
        "gatt_or_dfu_writes": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["raw_hci_supported"]:
        print("\nThis machine cannot run raw HCI through Apple's internal controller.")
        print("Use a dedicated USB BLE adapter attached to Linux, a Linux VM, or a Raspberry Pi.")
        return 2
    if not adapters:
        print("\nNo Linux HCI adapter is present.")
        return 2
    return 0


def _require_execute(args: argparse.Namespace) -> None:
    if not args.execute:
        raise HCIError("refusing controller access without --execute")


def _print_advertisement(report) -> None:
    kind = ADDRESS_TYPE_NAME.get(report.address_type, f"type-{report.address_type}")
    identity = "ring" if report.strong_ring_identity else "candidate"
    print(
        f"{report.address} {kind:<6} rssi={report.rssi:>4} "
        f"connectable={str(report.connectable).lower():<5} "
        f"directed={str(report.directed).lower():<5} {identity:<9} "
        f"name={report.local_name or '-'} services={','.join(report.service_uuids) or '-'} "
        f"raw={report.data.hex()}"
    )


def scan(args: argparse.Namespace) -> int:
    _require_execute(args)
    seen = {}
    with RawHCI(args.adapter) as controller:
        for report in controller.scan(args.seconds):
            key = (report.address, report.address_type, report.event_type, report.data)
            previous = seen.get(key)
            if previous is None or report.rssi > previous.rssi:
                seen[key] = report
                _print_advertisement(report)
    print(f"observed {len(seen)} distinct advertisement forms; no connection or GATT write was sent")
    return 0


async def _darwin_wait(args: argparse.Namespace) -> int:
    if sys.platform != "darwin":
        raise HCIError("cached CoreBluetooth retrieval is available only on macOS")
    _require_execute(args)
    try:
        from Foundation import NSUUID
        from bleak import BleakClient
        from bleak.backends.device import BLEDevice
        from bleak.backends.corebluetooth.CentralManagerDelegate import CentralManagerDelegate
    except ImportError as exc:
        raise HCIError(f"macOS CoreBluetooth bridge is unavailable: {exc}") from exc

    identifier = NSUUID.alloc().initWithUUIDString_(args.identifier)
    if identifier is None:
        raise HCIError(f"invalid CoreBluetooth identifier: {args.identifier!r}")
    manager = CentralManagerDelegate()
    await manager.wait_until_ready()
    peripherals = manager.central_manager.retrievePeripheralsWithIdentifiers_([identifier])
    if not peripherals:
        raise HCIError("CoreBluetooth has no cached peripheral for that identifier")

    peripheral = peripherals[0]
    device = BLEDevice(args.identifier.upper(), peripheral.name(), (peripheral, manager))
    print(
        f"cached peripheral found: id={device.address} name={device.name or '-'} "
        f"state={int(peripheral.state())}"
    )
    print(
        f"queuing direct CoreBluetooth connection for up to {args.seconds:.0f}s; "
        "no scan match, characteristic read/write, sensor command, or DFU write"
    )
    client = BleakClient(device, timeout=args.seconds)
    try:
        await client.connect(timeout=args.seconds)
        services = sorted(service.uuid.lower() for service in client.services)
        print(json.dumps({
            "connected": client.is_connected,
            "identifier": device.address,
            "name": device.name,
            "services": services,
            "uart_present": "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e" in services,
            "dfu_present": "de5bf728-d711-4e47-af26-65e3012a5dc7" in services,
            "characteristic_reads": 0,
            "characteristic_writes": 0,
        }, indent=2, sort_keys=True))
        if args.hold > 0:
            print(f"holding the read-free link for {args.hold:.0f}s")
            await asyncio.sleep(args.hold)
    except TimeoutError as exc:
        raise HCIError(
            "cached direct connection timed out; the controller still received "
            "no connectable advertisement from that peripheral"
        ) from exc
    except Exception as exc:
        raise HCIError(f"cached direct connection failed: {type(exc).__name__}: {exc}") from exc
    finally:
        if client.is_connected:
            await client.disconnect()
    return 0


def darwin_wait(args: argparse.Namespace) -> int:
    return asyncio.run(_darwin_wait(args))


def recover(args: argparse.Namespace) -> int:
    _require_execute(args)
    target = args.address.upper()
    observed = None
    with RawHCI(args.adapter) as controller:
        print(f"listening for exact address {target} for {args.seconds:.0f}s")
        reports = controller.scan(args.seconds)
        try:
            for report in reports:
                if report.address != target:
                    continue
                _print_advertisement(report)
                if report.connectable:
                    observed = report
                    break
        finally:
            # Closing the generator runs its scan-disable command before LE
            # Create Connection.  Do not rely on implementation-specific GC.
            reports.close()
        if observed is None:
            raise HCIError(
                "target emitted no connectable advertisement; raw LE Create Connection "
                "cannot bypass an idle or crashed peripheral radio"
            )
        print("exact connectable advertisement observed; starting bounded link test")
        complete = controller.connect(observed, timeout=args.connect_timeout)
        try:
            print(json.dumps({
                **asdict(complete),
                "address_type_name": ADDRESS_TYPE_NAME.get(complete.address_type),
                "att_gatt_writes": 0,
                "dfu_writes": 0,
            }, indent=2, sort_keys=True))
        finally:
            controller.disconnect(complete.handle)
        print("link proven and disconnected cleanly; firmware was not touched")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guarded raw-HCI advertisement/link recovery for an unreachable R02"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="report whether raw-HCI execution is available")

    darwin_parser = subparsers.add_parser(
        "darwin-wait",
        help="queue a direct connection to an exact cached CoreBluetooth identifier",
    )
    darwin_parser.add_argument("--identifier", required=True, help="historical CoreBluetooth UUID")
    darwin_parser.add_argument("--seconds", type=float, default=300.0, help="connection wait")
    darwin_parser.add_argument("--hold", type=float, default=0.0, help="seconds to hold a proven link")
    darwin_parser.add_argument("--execute", action="store_true", help="allow connection attempt")

    scan_parser = subparsers.add_parser("scan", help="inventory raw advertisements")
    scan_parser.add_argument("--adapter", type=int, default=0, help="dedicated Linux hci index")
    scan_parser.add_argument("--seconds", type=float, default=60.0)
    scan_parser.add_argument("--execute", action="store_true", help="allow controller access")

    recover_parser = subparsers.add_parser(
        "recover", help="link only after observing this exact address as connectable"
    )
    recover_parser.add_argument("--adapter", type=int, default=0, help="dedicated Linux hci index")
    recover_parser.add_argument("--address", required=True, help="exact public or random BLE address")
    recover_parser.add_argument("--seconds", type=float, default=90.0, help="observation window")
    recover_parser.add_argument("--connect-timeout", type=float, default=90.0)
    recover_parser.add_argument("--execute", action="store_true", help="allow controller access")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "darwin-wait":
            return darwin_wait(args)
        if args.command == "scan":
            return scan(args)
        return recover(args)
    except (HCIError, ValueError) as exc:
        print(f"recovery stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
