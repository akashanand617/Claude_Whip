"""
Identify the ring by proximity when it does not advertise a recognisable name.

Cheap rings ship inconsistent firmware. Some advertise as R01-R10, some use an
OEM placeholder, some advertise no name at all. Name matching fails on those,
and so does service-UUID matching when the ring does not put its service in the
advertisement.

Proximity always works. Watch every device's signal strength while the ring is
moved away from the machine: the ring is the one whose RSSI collapses.

    python -m probe.find

Follow the prompts. Keep the ring next to the laptop for the first half, then
carry it to another room for the second half.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
from collections import defaultdict

from bleak import BleakScanner

from whip import protocol


async def watch(duration: float, samples: dict) -> None:
    """Record every advertisement seen during `duration` seconds."""

    def on_detect(device, adv) -> None:
        name = adv.local_name or device.name
        # CoreBluetooth reports 127 when RSSI is unavailable. Treating that as
        # an exceptionally strong signal can make an unrelated anonymous
        # device outrank the ring during recovery diagnostics.
        if adv.rssi is not None and -127 <= adv.rssi < 0:
            samples[device.address]["rssi"].append(adv.rssi)
        if name:
            samples[device.address]["name"] = name
        if adv.service_uuids:
            samples[device.address]["uuids"].update(u.upper() for u in adv.service_uuids)
        samples[device.address]["manufacturers"].update(adv.manufacturer_data)
        for item in adv.platform_data:
            try:
                if "kCBAdvDataIsConnectable" in item:
                    samples[device.address]["connectable"].add(
                        bool(item["kCBAdvDataIsConnectable"])
                    )
            except (TypeError, KeyError):
                continue

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        await asyncio.sleep(duration)
    finally:
        await scanner.stop()


def new_bucket() -> dict:
    return {
        "rssi": [],
        "name": None,
        "uuids": set(),
        "manufacturers": set(),
        "connectable": set(),
    }


async def run(phase: float) -> int:
    near: dict = defaultdict(new_bucket)
    far: dict = defaultdict(new_bucket)

    print("=" * 60)
    print("  RING PROXIMITY FINDER")
    print("=" * 60)
    print()
    print(f"  PHASE 1 ({phase:.0f}s): hold the ring against the laptop.")
    print("  Move it around a little to keep it advertising.")
    print()
    for i in range(5, 0, -1):
        print(f"    starting in {i}...", end="\r", flush=True)
        await asyncio.sleep(1)
    print("    PHASE 1 RUNNING -- ring NEXT TO laptop        ")

    await watch(phase, near)
    print(f"    saw {len(near)} devices")
    print()

    print(f"  PHASE 2 ({phase:.0f}s): take the ring as far away as you can.")
    print("  Another room, or a closed drawer across the house.")
    print()
    for i in range(15, 0, -1):
        print(f"    walk away now -- phase 2 starts in {i:2d}s ...", end="\r", flush=True)
        await asyncio.sleep(1)
    print("    PHASE 2 RUNNING -- ring AWAY from laptop         ")

    await watch(phase, far)
    print(f"    saw {len(far)} devices")
    print()

    # A device is a candidate if it was strong when near and weak or absent when far.
    results = []
    for addr, data in near.items():
        if len(data["rssi"]) < 2:
            continue
        near_rssi = statistics.median(data["rssi"])
        far_data = far.get(addr)
        if far_data and far_data["rssi"]:
            far_rssi = statistics.median(far_data["rssi"])
            vanished = False
        else:
            far_rssi = -120.0
            vanished = True
        results.append((near_rssi - far_rssi, near_rssi, far_rssi, vanished, addr, data))

    results.sort(key=lambda r: -r[0])

    print("=" * 60)
    print("  CANDIDATES -- biggest signal drop first")
    print("=" * 60)
    print(f"  {'drop':>6} {'near':>6} {'far':>6}  {'name':<20} {'link':<5} {'mfg':<10} address")
    print(f"  {'-' * 6} {'-' * 6} {'-' * 6}  {'-' * 20} {'-' * 5} {'-' * 10} {'-' * 36}")

    for drop, near_rssi, far_rssi, vanished, addr, data in results[:12]:
        name = data["name"] or "(unnamed)"
        far_txt = "gone" if vanished else f"{far_rssi:.0f}"
        link = "yes" if True in data["connectable"] else "no" if data["connectable"] == {False} else "?"
        manufacturers = ",".join(f"{value:04x}" for value in sorted(data["manufacturers"])) or "-"
        ring_hint = ""
        if protocol.UART_SERVICE_UUID.upper() in data["uuids"]:
            ring_hint = "  <-- UART SERVICE"
        elif protocol.looks_like_ring(name):
            ring_hint = "  <-- ring name"
        elif data["manufacturers"] == {0x004C} and data["connectable"] == {False}:
            ring_hint = "  <-- Apple, nonconnectable"
        print(
            f"  {drop:6.0f} {near_rssi:6.0f} {far_txt:>6}  "
            f"{name:<20} {link:<5} {manufacturers:<10} {addr}{ring_hint}"
        )

    print()
    plausible = [
        row for row in results
        if 0x004C not in row[5]["manufacturers"]
        and row[5]["connectable"] != {False}
    ]
    if plausible:
        best = plausible[0]
        print(f"  most likely the ring: {best[5]['name'] or '(unnamed)'}  {best[4]}")
        print(f"  signal dropped {best[0]:.0f} dB when you walked away")
        print()
        print("  confirm it with:")
        print(f"    python -m probe.inspect --address {best[4]}")
    else:
        print("  nothing moved. The ring may not be advertising at all --")
        print("  make sure it is off the charger, awake, and not held by the phone.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Identify the ring by walking it away from the machine")
    parser.add_argument("--phase", type=float, default=20.0, help="seconds per phase")
    args = parser.parse_args()
    return asyncio.run(run(args.phase))


if __name__ == "__main__":
    raise SystemExit(main())
