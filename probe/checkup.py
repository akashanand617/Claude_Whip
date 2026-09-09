"""
Accept or reject a recorded session, before it reaches training.

    python -m probe.checkup prompted_20260908_201500
    python -m probe.checkup --all

A bad session caught now costs an hour of re-recording. Caught after training it
costs a week of wondering why the model will not generalise, and by then it has
already contaminated whatever it was averaged into.

Checks, each tied to a confound in docs/COLLECTION.md:

  rate          25 Hz +/- 0.2, measured from timestamps rather than assumed
  gaps          dropped samples look like flick onsets; baseline is ~0.24%
  clipping      full scale is +/-4.09 g and flicks reach 6.5 g
  interleaving  a run of one class lets session drift act as an oracle
  marks         every cue should sit on top of real motion
"""

from __future__ import annotations

import argparse
import glob
import statistics
from pathlib import Path

from whip import accel, capture, protocol, session

DATA_DIR = Path("data/sessions")

RATE_TARGET = 25.0
RATE_TOLERANCE = 0.2
LOSS_WARN = 0.02
CLIP_LIMIT = 32440  # within 1% of full scale
MAX_SAME_CLASS_RUN = 3


class Result:
    def __init__(self) -> None:
        self.problems: list[str] = []
        self.warnings: list[str] = []

    def fail(self, msg: str) -> None:
        self.problems.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.problems


def check(session_id: str) -> Result:
    result = Result()
    cap_path = DATA_DIR / f"{session_id}.jsonl"
    notes_path = DATA_DIR / f"{session_id}.notes.json"

    if not cap_path.exists():
        result.fail(f"no capture at {cap_path}")
        return result

    header, records = capture.load_capture(cap_path)
    acc = [(t, p) for t, p in records
           if len(p) >= 8 and p[0] == protocol.CMD_RAW_SENSOR and p[1] == protocol.SUBTYPE_ACCEL]

    if len(acc) < 100:
        result.fail(f"only {len(acc)} accelerometer samples")
        return result

    times = [t for t, _ in acc]
    span = times[-1] - times[0]
    rate = len(acc) / span

    print(f"  duration      {span / 60:7.1f} min   {len(acc)} samples")
    print(f"  rate          {rate:7.2f} Hz")
    if abs(rate - RATE_TARGET) > RATE_TOLERANCE:
        result.fail(f"rate {rate:.2f} Hz is outside {RATE_TARGET} +/- {RATE_TOLERANCE}")

    intervals = sorted((times[i + 1] - times[i]) * 1000 for i in range(len(times) - 1))
    median = statistics.median(intervals)
    missing = sum(max(0, round(g / median) - 1) for g in intervals)
    loss = missing / (missing + len(acc))
    print(f"  interval      {median:7.2f} ms median, p95 {intervals[int(len(intervals) * 0.95)]:.1f}, max {intervals[-1]:.1f}")
    print(f"  implied loss  {loss * 100:7.2f} %")
    if loss > LOSS_WARN:
        result.warn(f"implied loss {loss * 100:.2f}% is above the {LOSS_WARN * 100:.0f}% baseline")

    samples = [accel.decode(p) for _, p in acc]
    clipped = sum(1 for s in samples if max(abs(s.x), abs(s.y), abs(s.z)) > CLIP_LIMIT)
    print(f"  clipping      {clipped:7d} samples ({clipped / len(samples) * 100:.2f}%)")
    if clipped / len(samples) > 0.01:
        result.warn(f"{clipped / len(samples) * 100:.1f}% of samples clip; amplitude stops discriminating above full scale")

    if not notes_path.exists():
        print("  marks         (no notes file -- unprompted session)")
        return result

    notes = session.load_notes(notes_path)
    print(f"  kind          {notes.kind}, {notes.hand} hand, ring {notes.ring_position}")

    if not notes.marks:
        print("  marks         none")
        return result

    labels = [m["label"] for m in notes.marks]
    counts = {c: labels.count(c) for c in set(labels)}
    print(f"  marks         {len(notes.marks)}  {counts}")

    run, longest = 1, 1
    for a, b in zip(labels, labels[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    print(f"  longest run   {longest} of the same class")
    if longest > MAX_SAME_CLASS_RUN:
        result.fail(f"a run of {longest} identical labels lets session drift act as an oracle")

    # Every cue should land on top of real motion. A cue with a quiet window
    # around it means a missed gesture -- the participant did not perform it, or
    # performed it late.
    G = accel.COUNTS_PER_G
    mags = [((s.x ** 2 + s.y ** 2 + s.z ** 2) ** 0.5) / G for s in samples]
    baseline = statistics.median(mags)
    quiet = []
    for m in notes.marks:
        lo, hi = m["cue_at"], m["cue_at"] + 2.0
        window = [mg for t, mg in zip(times, mags) if lo <= t <= hi]
        if window and (max(window) - baseline) < 0.5:
            quiet.append(m["index"])
    if quiet:
        result.warn(f"{len(quiet)} cue(s) have no motion within 2 s: indices {quiet[:8]}")
    print(f"  cues with motion  {len(notes.marks) - len(quiet)}/{len(notes.marks)}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Accept or reject a recorded session")
    parser.add_argument("session", nargs="?", help="session id (filename without extension)")
    parser.add_argument("--all", action="store_true", help="check every session")
    args = parser.parse_args()

    if args.all:
        ids = sorted({Path(f).name.replace(".jsonl", "") for f in glob.glob(str(DATA_DIR / "*.jsonl"))})
    elif args.session:
        ids = [args.session.replace(".jsonl", "")]
    else:
        parser.error("give a session id or --all")

    if not ids:
        print("no sessions found in data/sessions/")
        return 1

    failed = 0
    for sid in ids:
        print(f"\n=== {sid} ===")
        result = check(sid)
        for w in result.warnings:
            print(f"  WARN  {w}")
        for p in result.problems:
            print(f"  FAIL  {p}")
        print(f"  -> {'ACCEPT' if result.ok else 'REJECT'}")
        failed += not result.ok

    print(f"\n{len(ids) - failed}/{len(ids)} sessions acceptable")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
