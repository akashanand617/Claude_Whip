"""
Stream every session past the model the way the daemon will, and count.

    python -m probe.rollout --checkpoint data/model.pt
    python -m probe.rollout --checkpoint data/model.pt --debounce 3 14

This is the evaluation that matches deployment: a continuous stream, most of
which is nothing, with occasional gestures. Window accuracy and macro F1 both
mislead here -- they count one gesture six times, treat every isolated flicker
as a failure, and say nothing about how often the thing fires while you type.

What this reports instead, per session: gestures present, gestures detected,
missed, and false detections. Sessions the model trained on are marked, because
their perfect recall is memorisation rather than evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from whip import events

WINDOWS = Path("data/windows.npz")
SESSIONS = Path("data/sessions")

# Below this, a false-positive rate is extrapolation rather than measurement.
# Showing "< 1/hour" honestly needs roughly an hour; 30 minutes is the point
# where the number stops being pure noise.
MIN_AMBIENT_MIN = 30.0


def truth_for(session_id: str) -> list[tuple[float, str]]:
    """Gesture times from the session's marks, offset to the middle of the gesture."""
    path = SESSIONS / f"{session_id}.notes.json"
    if not path.exists():
        return []
    notes = json.loads(path.read_text())
    return [
        (m["cue_at"] + 0.6, m["label"])
        for m in notes.get("marks", [])
        if m.get("label") in ("flag", "approve")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream sessions past the model and count detections")
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--windows", type=Path, default=WINDOWS)
    parser.add_argument("--debounce", type=int, nargs=2, default=(events.MIN_RUN, events.MAX_RUN),
                        metavar=("MIN", "MAX"))
    parser.add_argument("--trained-on", action="append", default=[],
                        help="session ids the model trained on; their recall is not evidence")
    args = parser.parse_args()

    if not args.checkpoint.exists():
        print(f"no checkpoint at {args.checkpoint} -- save one from the notebook first")
        return 1

    import torch

    from whip import model as gesture_model

    model, provenance = gesture_model.load(args.checkpoint)
    # The checkpoint records which sessions it trained on, so the report cannot
    # silently count memorised recall as evidence just because nobody passed a flag.
    trained_on = set(args.trained_on) | set(provenance.get("trained_on", []))

    d = np.load(args.windows, allow_pickle=True)
    X, SESS, START = d["X"], d["session"], d["start_s"]
    labels = [str(s) for s in d["labels"]]
    lo, hi = args.debounce

    print(f"debounce {lo}-{hi} consecutive windows\n")
    print(f"{'session':<42} {'min':>6} {'have':>6} {'found':>6} {'miss':>6} {'false':>6}")
    print("-" * 80)

    totals = dict(minutes=0.0, have=0, found=0, false=0)
    unseen = dict(minutes=0.0, have=0, found=0, false=0)

    for session_id in sorted(set(SESS.tolist())):
        mask = SESS == session_id
        if mask.sum() < 60:
            continue
        order = np.where(mask)[0][np.argsort(START[mask])]
        with torch.no_grad():
            pred = model(torch.tensor(X[order])).argmax(1).numpy()
        preds = [labels[p] for p in pred]
        starts = START[order].tolist()
        hours = (starts[-1] - starts[0]) / 3600

        truth = truth_for(session_id)
        detected = events.detect(preds, starts, min_run=lo, max_run=hi)
        scored = events.score(detected, truth, hours)
        found = sum(v["tp"] for v in scored["per_class"].values())
        missed = sum(v["fn"] for v in scored["per_class"].values())

        tag = "  (trained on)" if session_id in trained_on else ""
        print(f"{session_id:<42} {hours*60:6.1f} {len(truth):>6} {found:>6} {missed:>6} "
              f"{scored['false_positives']:>6}{tag}")

        buckets = [totals]
        if session_id not in trained_on:
            buckets.append(unseen)
        for bucket in buckets:
            bucket["minutes"] += hours * 60
            bucket["have"] += len(truth)
            bucket["found"] += found
            bucket["false"] += scored["false_positives"]

    print("-" * 80)

    # Recall and false-positive rate are measured on different data and must not
    # share a summary line. Recall needs gestures, so it comes from held-out
    # prompted sessions. A false-positive rate needs ambient wear -- extrapolating
    # one spurious event in a 3.6 minute gesture-dense session to "16.7/hour" is
    # arithmetic dressed up as a measurement, and it was the first thing this
    # tool printed.
    have = unseen["have"]
    if have:
        print(f"  recall (held out)     {unseen['found']}/{have} = "
              f"{unseen['found'] / have * 100:.1f}%   over {unseen['minutes']:.1f} min")
    else:
        print("  recall (held out)     no held-out session with gestures -- recall unmeasured")

    ambient = unseen["minutes"] if not have else 0.0
    if ambient >= MIN_AMBIENT_MIN:
        print(f"  false positives       {unseen['false'] / (ambient / 60):.2f}/hour "
              f"over {ambient:.1f} min of held-out ambient wear")
    else:
        print(f"  false positives       UNMEASURED -- needs >= {MIN_AMBIENT_MIN:.0f} min of "
              f"held-out wear with no gestures; have {ambient:.1f}")
        print("                        (every negative session above is in the training set,")
        print("                         so their zero false positives prove nothing)")

    print("\n  target: FP < 1/hour, which cannot be shown with less than an hour of ambient data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
