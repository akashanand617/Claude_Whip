"""Build the exact-image RT12COL Health-default / temporary-Gesture candidate."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from whip import fwrt12col_unified


DEFAULT_BASE = Path(__file__).resolve().parents[1] / "firmware" / "rt12col-stock-1.00.00.bin"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument(
        "--revision", required=True,
        choices=("v1", "v2", "v3-revoked", "v4-lp2", "v5-lp1", "v6-sleep-fix",
                 "v7-100hz-compare"),
        help="explicit archived, revoked, or off-ring comparison revision",
    )
    parser.add_argument("--out", type=Path, required=True,
                        help="new output only; existing paths are refused")
    args = parser.parse_args(argv)
    try:
        builders = {
            "v1": fwrt12col_unified.build_v1,
            "v2": fwrt12col_unified.build_v2,
            "v3-revoked": fwrt12col_unified.build_v3,
            "v4-lp2": fwrt12col_unified.build_lp2,
            "v5-lp1": fwrt12col_unified.build_lp1,
            "v6-sleep-fix": fwrt12col_unified.build_v6,
            "v7-100hz-compare": fwrt12col_unified.build_v7,
        }
        candidate = builders[args.revision](args.base.read_bytes())
        with args.out.open("xb") as stream:
            stream.write(candidate)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"RT12COL HEALTH-DEFAULT / TEMPORARY-GESTURE {args.revision.upper()}")
    print(f"Wrote: {args.out} ({len(candidate)} bytes)")
    print(f"SHA-256: {hashlib.sha256(candidate).hexdigest()}")
    print("Stock boot, GATT, DFU, partitions and image size retained.")
    if args.revision == "v4-lp2":
        print("REVOKED: physical testing measured 49.4% paired duplicate payloads.")
        print("Reproduced for provenance only; never select this image for installation.")
    elif args.revision == "v5-lp1":
        print("REVOKED: physical testing measured 49.0% paired duplicate payloads.")
        print("Reproduced for provenance only; never select this image for installation.")
    elif args.revision == "v6-sleep-fix":
        print("BASELINE: V4-LP2 plus Gesture WAKE_UP_THS 0x01; exits restore stock 0x41.")
        print("Bounded freshness/renewal tests passed; this command still performs no flash.")
    elif args.revision == "v7-100hz-compare":
        print("DISABLED COMPARISON: V6 with Gesture CTRL1 0x51 (100 Hz LP2).")
        print("Freshness passed but model transfer did not beat V6; no app install route.")
    else:
        print("Archived/revoked artifact; never select it as an install target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
