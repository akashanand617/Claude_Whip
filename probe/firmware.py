"""
Inspect a firmware image, and diff two of them, before flashing anything.

    python -m probe.firmware firmware/rt02cr-low-latency.bin
    python -m probe.firmware firmware/*.bin --diff
    python -m probe.firmware firmware/rt02cr-low-latency.bin --expect-sha 2ea1bb08...

The point is to be able to state what an image will do to the ring without
taking anyone's word for it. Everything here is offline; no ring required.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

from whip import fwimage

# What the raw motion timer looks like on stock RT02CR.
STOCK_PERIOD_MS = 1000
GATE_HZ = 25.0


def describe(image: fwimage.FirmwareImage, hardware: str | None) -> None:
    print("=" * 66)
    print(f"  {image.path.name}")
    print("=" * 66)
    print(f"  size            {image.size} bytes")
    print(f"  sha256          {image.sha256}")
    print(f"  container       {image.magic.hex()}  {image.container}")
    print(f"  payload at      {image.payload_offset:#06x}" if image.payload_offset else "  payload at      unknown")
    if image.crc32_verifies is not None:
        state = "verifies" if image.crc32_verifies else "does not verify (different algorithm, not encryption)"
        print(f"  header CRC32    {state}")
    print(f"  firmware string {image.firmware_string!r}")
    print(f"  hardware string {image.hardware_string!r}")

    match = image.matches_hardware(hardware)
    if match is not None:
        verdict = "MATCH" if match else "MISMATCH -- DO NOT FLASH"
        print(f"  vs ring hw      {hardware!r}  [{verdict}]")

    candidates = fwimage.raw_motion_candidates(image)
    print(f"\n  timer sites (movs rN,#imm / lsls rN,rN,#3 -> imm * 8 ms)")
    print(f"  {len(image.timer_sites)} total, {len(candidates)} with period <= 2000 ms\n")
    print(f"    {'offset':>10}  {'reg':>4}  {'imm':>4}  {'period':>9}  {'rate':>10}")
    print(f"    {'-' * 10}  {'-' * 4}  {'-' * 4}  {'-' * 9}  {'-' * 10}")
    for site in candidates[:24]:
        flag = ""
        if site.period_ms == STOCK_PERIOD_MS:
            flag = "  <- stock 1 Hz idiom"
        elif site.rate_hz >= GATE_HZ:
            flag = "  <- clears the 25 Hz gate"
        print(
            f"    {site.offset:#010x}  r{site.register:<3}  {site.immediate:>4}"
            f"  {site.period_ms:>6} ms  {site.rate_hz:>7.2f} Hz{flag}"
        )
    print()


def diff(a: fwimage.FirmwareImage, b: fwimage.FirmwareImage) -> None:
    """Byte diff plus the timer sites that changed -- what the patch actually did."""
    da, db = a.path.read_bytes(), b.path.read_bytes()
    print("=" * 66)
    print(f"  DIFF  {a.path.name}  ->  {b.path.name}")
    print("=" * 66)

    if len(da) != len(db):
        print(f"  sizes differ: {len(da)} vs {len(db)} -- different builds, byte diff not meaningful")
    else:
        changed = [i for i in range(len(da)) if da[i] != db[i]]
        print(f"  {len(changed)} bytes differ")
        for i in changed[:24]:
            print(f"    {i:#010x}  {da[i]:#04x} -> {db[i]:#04x}")

    sites_a = {s.offset: s for s in a.timer_sites}
    sites_b = {s.offset: s for s in b.timer_sites}
    shared = sorted(set(sites_a) & set(sites_b))
    changed_sites = [o for o in shared if sites_a[o].immediate != sites_b[o].immediate]

    print(f"\n  timer sites changed at the same offset: {len(changed_sites)}")
    for offset in changed_sites:
        sa, sb = sites_a[offset], sites_b[offset]
        print(
            f"    {offset:#010x}  #{sa.immediate} -> #{sb.immediate}"
            f"   {sa.period_ms} ms -> {sb.period_ms} ms"
            f"   {sa.rate_hz:.2f} Hz -> {sb.rate_hz:.2f} Hz"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect and diff ring firmware images offline")
    parser.add_argument("paths", nargs="+", help="image files (globs allowed)")
    parser.add_argument("--hardware", help="ring hardware string to check against, e.g. RT02CR_V3.1")
    parser.add_argument("--expect-sha", help="fail unless the image has this sha256")
    parser.add_argument("--diff", action="store_true", help="diff the first two images")
    args = parser.parse_args()

    paths: list[Path] = []
    for pattern in args.paths:
        matches = sorted(glob.glob(pattern))
        paths.extend(Path(m) for m in matches) if matches else paths.append(Path(pattern))

    images = []
    for path in paths:
        if not path.exists():
            print(f"missing: {path}")
            return 1
        image = fwimage.inspect(path)
        images.append(image)
        describe(image, args.hardware)

        if args.expect_sha and image.sha256 != args.expect_sha:
            print(f"  SHA MISMATCH: expected {args.expect_sha}")
            return 1

    if args.diff and len(images) >= 2:
        diff(images[0], images[1])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
