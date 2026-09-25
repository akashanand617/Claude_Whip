"""Build the exact-image Health-default / temporary-Gesture candidate offline."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from whip import fwoptical_unified

DEFAULT_BASE = Path(__file__).resolve().parents[1] / "firmware/rt02cr-25hz.bin"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--out", type=Path, required=True,
                        help="new output only; existing paths are refused")
    args = parser.parse_args(argv)
    try:
        candidate = fwoptical_unified.build(args.base.read_bytes())
        with args.out.open("xb") as stream:
            stream.write(candidate)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("HEALTH-DEFAULT / TEMPORARY-GESTURE CANDIDATE — NOT YET DEVICE-VALIDATED")
    print(f"Wrote: {args.out} ({len(candidate)} bytes)")
    print(f"SHA-256: {hashlib.sha256(candidate).hexdigest()}")
    print("No partition growth; no new persistent RAM; stock UART mode switch retained.")
    print("No flash performed. Recovery and physical continuity gates remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
