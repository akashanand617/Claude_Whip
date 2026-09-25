"""
Frozen-sample audit over every archived raw capture. Read-only.

    python -m probe.freshness                # all capture directories
    python -m probe.freshness data/sessions  # one directory or file

The rate and loss gates cannot see this failure: the ring keeps sending
`A1 03` frames at 25 Hz while carrying the same XYZ bytes. It happens when the
accelerometer driver idles the STK8321 after a quiet spell (any-motion
low-power mode; firmware sub_0cd08 -> sub_0ca60 -> sub_0c888) and the raw
producer then repeats its last cached sample every tick (sub_0cbda). A worn
ring never produces a second of byte-identical frames on its own -- sensor
noise toggles the low bits every few frames -- so a run of identical frames at
least `analyze.FROZEN_RUN_S` long is the cached sample, not stillness.

Why it matters: a frozen stretch cannot contain a gesture and cannot produce a
false positive, so ambient-hour false-positive rates measured on captures with
frozen stretches are bounded on less time than their length says. Measured on
2026-09-22: the two ambient hours (`negative_20260915_*`) were frozen for 28%
and 39% of their length, in runs up to 84 s; prompted sessions were under 3%.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path

from whip import analyze

DEFAULT_ROOTS = ("data/sessions", "data/live", "data/raw", "data/drain", "data/ledcheck", "data/batterycheck")
MIN_FRAMES = 100


def load_accel_records(path: Path) -> list[tuple[float, bytes]]:
    """(arrival_s, payload) for every `A1 03` frame in a capture, any of the project's line formats."""
    records: list[tuple[float, bytes]] = []
    with path.open() as handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = rec.get("p") or rec.get("payload")
            t = rec.get("t")
            if not isinstance(payload, str) or t is None or not payload.startswith("a103"):
                continue
            records.append((float(t), bytes.fromhex(payload)))
    return records


def audit(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        records = load_accel_records(path)
        if len(records) < MIN_FRAMES:
            continue
        runs, frozen_s, longest, distinct = analyze.frozen_sample_audit(records)
        duration = records[-1][0] - records[0][0]
        rows.append({
            "capture": str(path),
            "frames": len(records),
            "duration_s": duration,
            "frozen_runs": runs,
            "frozen_s": frozen_s,
            "frozen_fraction": frozen_s / duration if duration else 0.0,
            "longest_frozen_s": longest,
            "distinct_fraction": distinct,
        })
    rows.sort(key=lambda r: -r["frozen_s"])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen-sample audit of raw captures")
    parser.add_argument("paths", nargs="*", help="capture files or directories (default: the project's capture dirs)")
    parser.add_argument("--min-frozen", type=float, default=0.0, help="only print captures with at least this many frozen seconds")
    args = parser.parse_args()

    targets = args.paths or [r for r in DEFAULT_ROOTS if os.path.isdir(r)]
    files: list[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            files.extend(Path(p) for p in glob.glob(str(path / "**" / "*.jsonl"), recursive=True))
        elif path.is_file():
            files.append(path)
    rows = audit(sorted(set(files)))

    print(f"{'capture':<64} {'frames':>7} {'dur_s':>7} {'longest':>8} {'runs':>5} {'frozen_s':>9} {'frozen':>7} {'distinct':>9}")
    for r in rows:
        if r["frozen_s"] < args.min_frozen:
            continue
        name = r["capture"][-64:]
        print(f"{name:<64} {r['frames']:>7} {r['duration_s']:>7.0f} {r['longest_frozen_s']:>7.1f}s {r['frozen_runs']:>5} "
              f"{r['frozen_s']:>8.1f}s {r['frozen_fraction'] * 100:>6.1f}% {r['distinct_fraction'] * 100:>8.1f}%")
    print(f"\n{len(rows)} captures with >= {MIN_FRAMES} accelerometer frames. "
          f"A frozen run is >= {analyze.FROZEN_RUN_S:.0f} s of byte-identical frames.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
