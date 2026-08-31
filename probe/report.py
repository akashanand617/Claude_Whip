"""
Re-analyse a saved capture without touching the ring.

Every capture keeps the raw notification payloads, so a new idea about decoding
or a new metric can be tested against data collected weeks ago.

    python -m probe.report data/raw/idle_20250831_120000.jsonl
    python -m probe.report data/raw/idle_*.jsonl --stationary
    python -m probe.report data/raw/typing_*.jsonl --dump 20
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

from whip import accel, analyze, capture, protocol


def accel_payloads(records: list[tuple[float, bytes]]) -> list[bytes]:
    return [
        p
        for _, p in records
        if len(p) >= 8 and p[0] == protocol.CMD_RAW_SENSOR and p[1] == protocol.SUBTYPE_ACCEL
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse a saved capture")
    parser.add_argument("paths", nargs="+", help="JSONL capture files (globs allowed)")
    parser.add_argument("--stationary", action="store_true", help="rank candidate unpackers using gravity")
    parser.add_argument("--unpacker", default=accel.DEFAULT_UNPACKER, choices=list(accel.UNPACKERS))
    parser.add_argument("--dump", type=int, default=0, help="print the first N decoded samples")
    parser.add_argument("--hex", type=int, default=0, help="print the first N raw payloads as hex")
    args = parser.parse_args()

    paths: list[Path] = []
    for pattern in args.paths:
        matches = sorted(glob.glob(pattern))
        paths.extend(Path(m) for m in matches) if matches else paths.append(Path(pattern))

    for path in paths:
        if not path.exists():
            print(f"missing: {path}")
            continue

        header, records = capture.load_capture(path)
        stats = analyze.analyze(records)
        payloads = accel_payloads(records)

        print(analyze.format_report(stats, header=header, payloads=payloads if args.stationary else None))

        if args.hex:
            print(f"\n  first {args.hex} raw payloads")
            for _, payload in records[: args.hex]:
                print(f"    {payload.hex()}")

        if args.dump:
            print(f"\n  first {args.dump} samples via '{args.unpacker}'")
            print(f"    {'x':>8} {'y':>8} {'z':>8} {'|a|':>9}")
            for payload in payloads[: args.dump]:
                s = accel.decode(payload, args.unpacker)
                print(f"    {s.x:8d} {s.y:8d} {s.z:8d} {s.magnitude:9.1f}")

        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
