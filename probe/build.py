"""
Build a custom-rate firmware image.

The raw motion period is one immediate operand: `movs rN, #imm` feeding
`lsls rN, rN, #3`.

The instruction says the period is `imm * 8` ms, but **the delivered period is
`imm * 10` ms**, measured at three points on hardware:

    #2   50.00 Hz   bimodal arrivals, implied loss ~26%
    #3   33.33 Hz   clean 30 ms intervals, loss 1.96%  <-- passes M0
    #4   24.98 Hz   clean 40 ms intervals, loss 0.07%, just under the gate

Where the extra 25% comes from is not established -- a slower timer tick, or
scheduling overhead between the timer and the notification. Rates here are
computed from the measured relationship, not the instruction, because the
instruction predicts 25% high.

    python -m probe.build --immediate 3      # 33 Hz, the one that passes

Every derived container field is recomputed, so the result is bootable. Verify
before flashing:

    python -m probe.firmware firmware/rt02cr-31hz.bin --hardware RT02CR_V3.1
    python -m probe.flash firmware/rt02cr-31hz.bin --dry-run --allow-unpinned
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from whip import fwbuild, fwimage

DEFAULT_BASE = Path("firmware/rt02cr-low-latency.bin")

# The period the published low-latency image ships with. We locate the site by
# its current value rather than a hard-coded offset, so this keeps working if
# upstream republishes at a different address.
LOW_LATENCY_PERIOD_MS = 16

# The instruction computes imm * 8 ms, but delivered periods are imm * 10 ms:
# 50.00 / 33.33 / 24.98 Hz measured at #2 / #3 / #4. Predict from the
# measurement, not the arithmetic.
MEASURED_MS_PER_UNIT = 10


def find_raw_motion_site(image: fwimage.FirmwareImage) -> fwimage.TimerSite:
    """
    Locate the raw motion timer by its period, not its address.

    Several sites share the idiom, so this insists on exactly one match and
    refuses to guess. Sites in DO_NOT_PATCH are excluded by
    `raw_motion_candidates` -- 0x007ed4 in particular looks identical but is DFU
    frame reassembly, and lowering it can break OTA recovery.
    """
    candidates = [s for s in fwimage.raw_motion_candidates(image) if s.period_ms == LOW_LATENCY_PERIOD_MS]
    if len(candidates) != 1:
        raise SystemExit(
            f"expected exactly one {LOW_LATENCY_PERIOD_MS} ms timer site, found {len(candidates)}. "
            "The base image is not the one this tool was written for."
        )
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a firmware image with a custom raw motion rate")
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="image to patch")
    parser.add_argument("--immediate", type=int, required=True, help="timer immediate; period is imm * 8 ms")
    parser.add_argument("--out", type=Path, help="output path (default names itself after the rate)")
    args = parser.parse_args()

    if not 1 <= args.immediate <= 255:
        raise SystemExit("immediate must fit in a byte (1-255)")

    period_ms = args.immediate * MEASURED_MS_PER_UNIT
    rate_hz = 1000 / period_ms
    if rate_hz < 25:
        raise SystemExit(f"immediate {args.immediate} gives {rate_hz:.1f} Hz, below the 25 Hz gate")

    data = args.base.read_bytes()
    image = fwimage.inspect(args.base)

    problems = fwbuild.verify(data)
    if problems:
        raise SystemExit("base image is not internally consistent:\n  " + "\n  ".join(problems))

    site = find_raw_motion_site(image)
    file_offset = image.payload_offset + site.offset

    print(f"  base            {args.base.name}")
    print(f"  hardware        {image.hardware_string!r}")
    print(f"  timer site      {file_offset:#08x}  (payload {site.offset:#08x}, r{site.register})")
    print(f"  current         #{site.immediate}  -> {1000 / (site.immediate * MEASURED_MS_PER_UNIT):.2f} Hz measured")
    print(f"  new             #{args.immediate}  -> {rate_hz:.2f} Hz expected ({period_ms} ms)")

    patched = fwbuild.patch(data, {file_offset: args.immediate})

    remaining = fwbuild.verify(patched)
    if remaining:
        raise SystemExit("built image is inconsistent:\n  " + "\n  ".join(remaining))

    out = args.out or args.base.parent / f"rt02cr-{rate_hz:.0f}hz.bin"
    out.write_bytes(patched)

    changed = sum(1 for a, b in zip(data, patched) if a != b)
    print(f"\n  wrote           {out}  ({len(patched)} bytes)")
    print(f"  sha256          {hashlib.sha256(patched).hexdigest()}")
    print(f"  changed         {changed} bytes (1 timer + 32 sha + body sum)")
    print(f"  container       consistent")

    rebuilt = fwimage.inspect(out)
    fast = [s for s in fwimage.raw_motion_candidates(rebuilt) if s.rate_hz >= 25]
    print(f"  timers >=25 Hz  {[(hex(s.offset), f'{s.rate_hz:.1f}Hz') for s in fast]}")

    print("\n  next:")
    print(f"    python -m probe.flash {out} --dry-run --allow-unpinned")
    print(f"    python -m probe.flash {out} --allow-unpinned")
    print("\n  --allow-unpinned is required because this image is ours, not from the")
    print("  upstream catalogue. Recovery remains firmware/rt02cr-stock-3.12.02.bin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
