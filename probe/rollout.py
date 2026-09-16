"""
Stream every session past the model the way the daemon will, and count.

    python -m probe.rollout --checkpoint data/model.pt
    python -m probe.rollout --checkpoint data/model.pt --budget-per-hour 1.0

This is the evaluation that matches deployment: a continuous stream, most of
which is nothing, with occasional gestures. Window accuracy and macro F1 both
mislead here -- they count one gesture six times, treat every isolated flicker
as a failure, and say nothing about how often the thing fires while you type.

Three rules it enforces, each because breaking them produced a wrong answer that
survived for weeks. See `whip/evaluate.py` for the full account.

**The threshold is calibrated on a session that is not reported on.** The longest
held-out negative is split in half by time; the first half sets the threshold,
the second half is scored. Every earlier number in this project chose its
threshold by looking at the evaluation negative.

**Recall comes with a sampling interval, not just a seed spread.** At 64 gestures
the interval is about +/-11 points, wider than most differences ever claimed here.

**A rate is per minute of the activity**, and short recordings report an upper
bound rather than a flattering zero.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from whip import audit, dataset, evaluate, events

WINDOWS = Path("data/windows.npz")
SESSIONS = Path("data/sessions")

# Minutes of clean ambient wear needed before a "< 1 per hour" claim is
# supportable at all. By the rule of three, zero events in T minutes bounds the
# rate at 3/T, so one clean hour bounds it at 3/hour -- not 1. Three hours is the
# break-even, and this sits just past it. An earlier version of this file used 30
# minutes, which could never have demonstrated the criterion.
MIN_AMBIENT_MIN = 190.0


from whip.registry import load_registry

_REGISTRY = load_registry()


def truth_for(session_id: str) -> list[tuple[float, str]]:
    """Impulsive gesture times from the session's marks, canonically named."""
    path = SESSIONS / f"{session_id}.notes.json"
    if not path.exists():
        return []
    notes = json.loads(path.read_text())
    # Gestures the audit did not pass as valid are not scored: the record does
    # not show the cued gesture, or not certainly, so a hit or a miss on it
    # means nothing. Same set the exporter excludes.
    invalid = set(audit.excluded_cues(SESSIONS / f"{session_id}.jsonl"))
    out = []
    for m in notes.get("marks", []):
        if "until" in m or m["cue_at"] in invalid:
            continue
        spec = _REGISTRY.resolve(m.get("label", "none"))
        if spec is not None:
            out.append((m["cue_at"] + 0.6, spec.name))
    return out


def spans_for(session_id: str) -> list[tuple[float, float, str]]:
    """
    Cued gesture spans, canonically named.

    These make a session *positive* content: the adversarial session's waving /
    snapping / clapping blocks are now classes, and an event fired inside one is
    a detection, not a false positive. Unrecognised motions stay attribution-only
    and their stretches still count toward the negative clock.
    """
    path = SESSIONS / f"{session_id}.notes.json"
    if not path.exists():
        return []
    notes = json.loads(path.read_text())
    out = []
    for m in notes.get("marks", []):
        if "until" not in m:
            continue
        spec = _REGISTRY.resolve(m.get("motion", ""))
        if spec is not None:
            out.append((m["cue_at"], m["until"], spec.name))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream sessions past the model and count detections")
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--windows", type=Path, default=WINDOWS)
    parser.add_argument("--budget-per-hour", type=float, default=1.0,
                        help="false-positive budget from the build spec")
    parser.add_argument("--calibrate-on", default=None,
                        help="negative session id; default is the longest held-out one")
    parser.add_argument("--debounce", type=int, nargs=2, default=(events.MIN_RUN, events.MAX_RUN),
                        metavar=("MIN", "MAX"))
    parser.add_argument("--trained-on", action="append", default=[])
    args = parser.parse_args()

    if not args.checkpoint.exists():
        print(f"no checkpoint at {args.checkpoint} -- train one first")
        return 1

    import torch

    from whip import model as gesture_model

    model, provenance = gesture_model.load(args.checkpoint)
    trained_on = set(args.trained_on) | set(provenance.get("trained_on", []))
    # The checkpoint says which channel groups it was trained on; deriving with
    # anything else is a silent shape or, worse, meaning mismatch.
    model_channels = tuple(provenance.get("channels", gesture_model.DEFAULT_CHANNELS))

    d = np.load(args.windows, allow_pickle=True)
    try:
        dataset.check_format_version(d)
    except dataset.StaleDataset as exc:
        print(exc)
        return 1
    X, SESS, START = d["X"], d["session"], d["start_s"]
    GRAV = d["gravity"] if "gravity" in d else None
    class_names = [str(s) for s in d["labels"]]
    # After collapsing, the class axis is the collapsed vocabulary.
    collapsed_names = _REGISTRY.collapsed_names(class_names)
    lo, hi = args.debounce
    budget_per_minute = args.budget_per_hour / 60.0

    def stream(session_id, mask=None):
        """Probabilities and start times for one session, in time order."""
        sel = SESS == session_id if mask is None else mask
        order = np.where(sel)[0][np.argsort(START[sel])]
        batch = gesture_model.to_model_input(
            X[order], model_channels, gravity=None if GRAV is None else GRAV[order])
        with torch.no_grad():
            probs = torch.softmax(model(torch.tensor(batch)), dim=1).numpy()
        starts = START[order].tolist()
        minutes = (starts[-1] - starts[0]) / 60 if len(starts) > 1 else 0.0
        # Direction-split sub-classes (flick_up, flick_down, ...) are a
        # training-time device. Scoring, debouncing and truth all speak in
        # collapsed names, so their probability mass is summed per gesture
        # here -- exactly what the realtime engine does before its tracker.
        return _REGISTRY.collapse_probabilities(probs, class_names), starts, minutes

    sessions = sorted(set(SESS.tolist()))
    held_out = [s for s in sessions if s not in trained_on and (SESS == s).sum() >= 60]
    # A session is negative only if it carries neither impulsive marks nor
    # recognised gesture spans. Spans count: a wave block is positive content.
    negatives = [s for s in held_out if not truth_for(s) and not spans_for(s)]
    with_gestures = [s for s in held_out if truth_for(s)]
    policies = _REGISTRY.policies(collapsed_names)

    # --- pick a calibration session, and split it so it is never reported on ---
    calib_id = args.calibrate_on
    if calib_id is None and negatives:
        calib_id = max(negatives, key=lambda s: (SESS == s).sum())
    if calib_id is None:
        print("no held-out negative session -- cannot calibrate a threshold without")
        print("tuning on the data being reported. Record ambient wear, or pass")
        print("--calibrate-on explicitly and accept the leak.")
        return 1

    sel = SESS == calib_id
    order = np.where(sel)[0][np.argsort(START[sel])]
    cut = START[order][0] + (START[order][-1] - START[order][0]) * 0.5
    guard = events.WINDOW_S
    first = sel & (START + events.WINDOW_S <= cut)
    second = sel & (START >= cut + guard)

    cp, cs, cm = stream(calib_id, first)
    try:
        threshold = evaluate.calibrate(cp, cs, cm, collapsed_names, budget_per_minute,
                                       min_run=lo, max_run=hi, policies=policies)
        note = ""
    except evaluate.NotMeasurable as exc:
        threshold = evaluate.calibrate(cp, cs, cm, collapsed_names, budget_per_minute,
                                       min_run=lo, max_run=hi, strict=False, policies=policies)
        note = f"  WARNING: {exc}"

    print(f"debounce {lo}-{hi} windows.  budget {args.budget_per_hour:.2f}/hour "
          f"({budget_per_minute:.4f}/min)")
    print(f"calibrated on {calib_id} first half ({cm:.1f} min) -> threshold {threshold:.2f}")
    if note:
        print(note)
    print()

    # --- report, on data the threshold never saw -------------------------------
    print(f"{'session':<42} {'min':>6} {'have':>5} {'found':>6} {'false':>6} {'/min':>7} {'95% ub/hr':>10}")
    print("-" * 88)

    ambient_minutes = 0.0
    ambient_fp = 0
    for session_id in sessions:
        if (SESS == session_id).sum() < 60:
            continue
        mask = second if session_id == calib_id else None
        probs, starts, minutes = stream(session_id, mask)
        labels = evaluate.labels_at(probs, collapsed_names, threshold)
        found = events.detect(labels, starts, min_run=lo, max_run=hi, policies=policies)
        truth = truth_for(session_id)
        spans = spans_for(session_id)

        if truth or spans:
            in_span = [e for e in found
                       if any(t_lo <= e.centre_s <= t_hi and e.label == name
                              for t_lo, t_hi, name in spans)]
            point_events = [e for e in found if e not in in_span]
            hits = evaluate.gesture_hits(point_events, truth)
            shits = events.span_hits(found, spans)
            n_found = sum(hits) + sum(shits)
            n_false = len(point_events) - sum(hits)
            truth = truth + [((t_lo + t_hi) / 2, name) for t_lo, t_hi, name in spans]
            rate = ub = float("nan")
        else:
            n_found, n_false = 0, len(found)
            point = evaluate.CurvePoint(threshold, 0, 0, n_false, minutes)
            rate, ub = point.fp_per_minute, point.fp_upper_bound_per_minute * 60
            if session_id not in trained_on:
                ambient_minutes += minutes
                ambient_fp += n_false

        tag = "  (trained on)" if session_id in trained_on else ""
        if session_id == calib_id:
            tag = "  (2nd half; 1st calibrated)"
        rate_s = "" if np.isnan(rate) else f"{rate:7.2f}"
        ub_s = "" if np.isnan(ub) else f"{ub:10.1f}"
        print(f"{session_id:<42} {minutes:6.1f} {len(truth):>5} {n_found:>6} {n_false:>6} "
              f"{rate_s:>7} {ub_s:>10}{tag}")

    print("-" * 88)

    # --- the curve, on the held-out gesture session ----------------------------
    if with_gestures:
        gid = with_gestures[0]
        gp, gs, _ = stream(gid)
        np_, ns_, nm_ = stream(calib_id, second)
        points = evaluate.curve(gp, gs, truth_for(gid), [(np_, ns_)], nm_, collapsed_names,
                                min_run=lo, max_run=hi, policies=policies)
        best = evaluate.recall_at_budget(points, budget_per_minute)

        print(f"\nrecall / false-positive curve on {gid}")
        print(f"  (false positives measured on {calib_id} second half, {nm_:.1f} min)\n")
        print(f"  {'thr':>5} {'recall':>8} {'95% CI':>16} {'FP/min':>8} {'95% ub/hr':>10}")
        for p in points:
            if p.threshold not in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
                continue
            hits = evaluate.gesture_hits(
                events.detect(evaluate.labels_at(gp, collapsed_names, p.threshold), gs,
                              min_run=lo, max_run=hi, policies=policies), truth_for(gid))
            ci = evaluate.bootstrap_recall_ci(hits)
            mark = "  <- budget" if best and p.threshold == best.threshold else ""
            print(f"  {p.threshold:5.2f} {p.recall * 100:7.1f}% "
                  f"{ci[0] * 100:6.1f}-{ci[1] * 100:5.1f}% {p.fp_per_minute:8.2f} "
                  f"{p.fp_upper_bound_per_minute * 60:10.1f}{mark}")

        if best is None:
            print(f"\n  NO threshold meets {args.budget_per_hour}/hour on the reporting negative.")
        else:
            hits = evaluate.gesture_hits(
                events.detect(evaluate.labels_at(gp, collapsed_names, best.threshold), gs,
                              min_run=lo, max_run=hi, policies=policies), truth_for(gid))
            lo_ci, hi_ci = evaluate.bootstrap_recall_ci(hits)
            print(f"\n  recall at budget  {best.recall * 100:.1f}%  "
                  f"(95% CI {lo_ci * 100:.1f}-{hi_ci * 100:.1f} over {best.total} gestures)")
        print(f"  mean recall across the usable curve  "
              f"{evaluate.area_under_curve(points, budget_per_minute) * 100:.1f}%")

    # --- the ambient claim, which is the one the spec actually asks for --------
    print()
    if ambient_minutes >= MIN_AMBIENT_MIN:
        ub = evaluate.CurvePoint(threshold, 0, 0, ambient_fp,
                                 ambient_minutes).fp_upper_bound_per_minute * 60
        print(f"  ambient false positives  {ambient_fp} in {ambient_minutes:.0f} min "
              f"-> 95% upper bound {ub:.2f}/hour")
    else:
        print(f"  ambient false positives  UNMEASURED -- {ambient_minutes:.0f} min of held-out")
        print(f"  ambient wear, need >= {MIN_AMBIENT_MIN:.0f}. By the rule of three, zero events")
        print(f"  in T minutes only bounds the rate at 3/T, so even a clean hour bounds it")
        print(f"  at 3/hour, not 1. Demonstrating < 1/hour takes over three hours.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
