"""Build an experimental optical-disabled image offline, without flashing.

    python -m probe.build_optical_off --out /tmp/rt02cr-optical-off-experimental.bin

The output must be a new file. The source archive and existing outputs are
never overwritten. Optical health and indicator functions are disabled
globally; this image still requires hardware validation.
The raw-start path now requests accelerometer wake, and a conditional guard
defers its idle requests during connected raw tracking. Stop or disconnect
releases the hold. Disconnect also clears raw mode 4 and stops its producer
timer; reconnect requires a new A1 04 to request wake. These changes
address the sleep path associated with frozen acceleration in the optical-STOP
trial; fresh motion-responsive samples with optics off remain unvalidated on
hardware.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from whip import fwoptical

DEFAULT_BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=fwoptical.EXPERIMENTAL_LABEL)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE, help="exact pinned 25 Hz archive")
    parser.add_argument("--out", type=Path, required=True, help="new output file; existing files are refused")
    args = parser.parse_args(argv)

    try:
        patched = fwoptical.build(args.base.read_bytes())
        with args.out.open("xb") as output:
            output.write(patched)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(fwoptical.EXPERIMENTAL_LABEL)
    print(f"Hardware: {fwoptical.HARDWARE}")
    print(f"Wrote: {args.out} ({len(patched)} bytes)")
    print(f"SHA-256: {hashlib.sha256(patched).hexdigest()}")
    print("Container and reviewed byte-change allowlist verified. No flash performed.")
    print("Connected raw mode defers idle; stop or disconnect restores idle eligibility.")
    print("Disconnect clears raw mode 4 and stops its timer after the original cleanup.")
    print("A new A1 04 requests accelerometer wake, including after reconnect.")
    print("Hardware validation pending: fresh XYZ, dark optics, start/stop, and battery drain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
