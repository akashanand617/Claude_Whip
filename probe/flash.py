"""
Flash firmware to the ring over BLE -- the CLI over `whip.flashing`.

    python -m probe.flash firmware/rt02cr-low-latency.bin --dry-run
    python -m probe.flash firmware/rt02cr-25hz.bin
    python -m probe.flash firmware/rt02cr-stock-3.12.02.bin --init-type 1   # restore

Every refuse-by-default gate lives in the library so the web frontend cannot
skip one either; see whip/flashing.py. `--dry-run` is the whole transfer minus
the radio -- run it first, every time.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from whip import capture, fwimage
# Re-exported so existing imports (tests included) keep one canonical home.
from whip.flashing import (  # noqa: F401
    BATTERY_FLOOR_PERCENT,
    DEFAULT_SEGMENT_BYTES,
    DfuChannel,
    FlashAborted,
    dry_run,
    firmware_is_compatible,
    flash_connected,
    has_compatibility_rules,
    load_catalogue_entry,
    preflight,
    print_progress,
    transfer,
)

CONFIRM_WORD = "FLASH"


async def run(args: argparse.Namespace) -> int:
    image = fwimage.inspect(args.image)
    entry = load_catalogue_entry(image)

    print("=" * 64)
    print("  PREFLIGHT")
    print("=" * 64)
    preflight(image, entry, args.allow_unpinned)

    if args.dry_run:
        dry_run(image, args.segment_bytes)
        print("  no connection attempted")
        return 0

    print()
    print("=" * 64)
    print("  RING")
    print("=" * 64)
    device = await capture.find_ring(address=args.address, timeout=args.timeout)
    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        print(f"  connected       {info.name}")
        print(f"  hardware        {info.hardware!r}")
        print(f"  firmware        {info.firmware!r}")

        if not args.yes:
            print(f"\n  About to overwrite firmware on {info.name}.")
            print("  There is no recovery path if DFU stops responding.")
            reply = input(f"  Type {CONFIRM_WORD} to proceed: ").strip()
            if reply != CONFIRM_WORD:
                print("  aborted")
                return 1

        await flash_connected(
            client, info, Path(args.image), args.init_type,
            battery_floor=args.battery_floor, allow_unpinned=args.allow_unpinned,
            segment_bytes=args.segment_bytes,
        )

    print("\n  transfer complete. Verify with:")
    print("    python -m probe.scan")
    print("    python -m probe.stream --duration 60 --label postflash --stationary")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Flash firmware to a Colmi ring over BLE")
    parser.add_argument("image", help="path to the OTA image")
    parser.add_argument("--dry-run", action="store_true", help="build and validate every frame, do not connect")
    parser.add_argument("--init-type", type=int, choices=(1, 4), default=4,
                        help="4 skips the app-level hardware-string compare (catalogue images expect 4)")
    parser.add_argument("--segment-bytes", type=int, default=DEFAULT_SEGMENT_BYTES)
    parser.add_argument("--battery-floor", type=int, default=BATTERY_FLOOR_PERCENT)
    parser.add_argument("--allow-unpinned", action="store_true", help="permit an image absent from the manifest")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    parser.add_argument("--address")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(run(args))
    except FlashAborted as exc:
        print(f"\n  ABORTED: {exc}")
        return 2
    except RuntimeError as exc:
        print(f"\n  error: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n  interrupted -- if a transfer was in progress the ring may be in DFU state")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
