"""
Is each cued direction a repeatable motion? Check before training on it.

    python -m probe.directions prompted_20260915_120000
    python -m probe.directions --all

For every prompted gesture this measures two things the classifier would need
to tell directions apart:

  - the wrist's ROTATION AXIS during the gesture (least-variance direction of
    the low-passed gravity trajectory), signed by the sense of rotation;
  - the GRAVITY VECTOR in the ring's frame during the gesture -- i.e. the hand's
    posture. A flick with the hand vertical is the same wrist flexion as one
    with the palm down; what differs is where gravity points.

Per direction it reports how consistent each is across repetitions (mean
resultant length: 1.0 = identical every time, ~0 = random) and how the
directions relate to each other. A direction whose reps do not share an axis
cannot be learned by any model, and the session is flagged before it costs a
training run. Measured on the first two sessions: `down` scored 0.94 and 0.99,
`up` 0.06 and 0.07 -- the labels were not the same motion twice, which is why a
direction-split model permuted them between days.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from whip import accel, dataset, despike
from whip.registry import SPLIT_DIRECTIONS, load_registry

SESSIONS = Path("data/sessions")
GRAVITY_WINDOW = 9
MIN_CONSISTENCY = 0.8


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _angle(a, b) -> float:
    return float(np.degrees(np.arccos(np.clip(np.dot(_unit(a), _unit(b)), -1, 1))))


def _lowpass(x, width=GRAVITY_WINDOW):
    k = np.ones(width) / width
    return np.stack([np.convolve(row, k, mode="same") for row in x])


def gesture_geometry(x, t, cue_at: float, duration_s: float = 1.2):
    """
    (signed rotation axis, gesture-mean gravity unit vector, rest gravity unit
    vector, flatness) for one cued gesture, or None if the stream is too short
    around it. `x` is (3, N) in g, already despiked.
    """
    pre = (t >= cue_at - 1.0) & (t < cue_at - 0.2)
    win = (t >= cue_at) & (t < cue_at + duration_s)
    if pre.sum() < 10 or win.sum() < 15:
        return None
    g0 = x[:, pre].mean(axis=1)
    track = _lowpass(x[:, win])
    centred = track - track.mean(axis=1, keepdims=True)
    values, vectors = np.linalg.eigh(np.cov(centred))
    axis = vectors[:, 0]
    early = track[:, :8].mean(axis=1) - g0
    late = track[:, 8:16].mean(axis=1) - g0
    sense = np.sign(np.dot(np.cross(g0, late - early), axis)) or 1.0
    flatness = values[0] / values[2] if values[2] > 0 else 1.0
    return axis * sense, _unit(track.mean(axis=1)), _unit(g0), float(flatness)


def analyse_session(session_id: str, registry=None) -> dict:
    registry = registry or load_registry()
    cap = SESSIONS / f"{session_id}.jsonl"
    notes = json.loads((SESSIONS / f"{session_id}.notes.json").read_text())
    times, samples = dataset._decode_stream(cap)
    t = np.asarray(times)
    x = despike.hampel(np.array(
        [[s.x for s in samples], [s.y for s in samples], [s.z for s in samples]], dtype=float)
    ) / accel.COUNTS_PER_G

    per: dict[str, dict[str, list]] = {}
    for m in notes.get("marks", []):
        spec = registry.resolve(m.get("label", "none"))
        if spec is None or "until" in m:
            continue
        direction = m.get("direction", "none")
        if direction not in SPLIT_DIRECTIONS:
            continue
        geo = gesture_geometry(x, t, m["cue_at"], spec.duration_s)
        if geo is None:
            continue
        axis, g_gesture, g_rest, flatness = geo
        slot = per.setdefault(direction, {"axis": [], "gravity": [], "rest": [], "flat": []})
        slot["axis"].append(axis)
        slot["gravity"].append(g_gesture)
        slot["rest"].append(g_rest)
        slot["flat"].append(flatness)

    summary = {}
    for direction, s in per.items():
        axes = np.array(s["axis"])
        grav = np.array(s["gravity"])
        # Unsigned consistency: align every rep's axis to the first principal
        # direction before averaging, so a consistent axis whose SENSE estimate
        # flips reads high here and low in the signed figure -- a 0.50 signed
        # score with a ~1.0 unsigned score means the motion repeats and only
        # the rotation-sense estimate is ambiguous, not the gesture.
        _, _, vt = np.linalg.svd(axes, full_matrices=False)
        principal = vt[0]
        aligned = axes * np.sign(axes @ principal)[:, None]
        summary[direction] = {
            "n": len(axes),
            "axis_consistency": float(np.linalg.norm(axes.mean(axis=0))),
            "axis_consistency_unsigned": float(np.linalg.norm(aligned.mean(axis=0))),
            "axis": _unit(axes.mean(axis=0)),
            "gravity_consistency": float(np.linalg.norm(grav.mean(axis=0))),
            "gravity": _unit(grav.mean(axis=0)),
            "flatness": float(np.median(s["flat"])),
        }
    return summary


def report(session_id: str, summary: dict, min_consistency: float = MIN_CONSISTENCY) -> bool:
    print(f"=== {session_id} ===")
    if not summary:
        print("  no directed gestures found")
        return False
    print(f"  {'dir':<6} {'n':>3} {'axis signed':>12} {'axis unsigned':>14} "
          f"{'gravity':>8} {'flatness':>9}   verdict")
    ok = True
    for d in SPLIT_DIRECTIONS:
        if d not in summary:
            continue
        s = summary[d]
        # The motion is repeatable if the unsigned axis agrees; the sense
        # estimate is a separate, weaker instrument and is reported, not judged.
        good = s["axis_consistency_unsigned"] >= min_consistency
        ok &= good
        print(f"  {d:<6} {s['n']:>3} {s['axis_consistency']:>12.2f} {s['axis_consistency_unsigned']:>14.2f} "
              f"{s['gravity_consistency']:>8.2f} {s['flatness']:>9.3f}   "
              f"{'ok' if good else 'INCONSISTENT'}")

    dirs = [d for d in SPLIT_DIRECTIONS if d in summary]
    print("\n  angle between mean rotation axes (deg; 180 = same axis opposite sense):")
    print("        " + "".join(f"{d:>8}" for d in dirs))
    for a in dirs:
        print(f"  {a:<6}" + "".join(f"{_angle(summary[a]['axis'], summary[b]['axis']):8.0f}" for b in dirs))
    print("\n  angle between mean gravity vectors during the gesture (deg; posture):")
    print("        " + "".join(f"{d:>8}" for d in dirs))
    for a in dirs:
        print(f"  {a:<6}" + "".join(f"{_angle(summary[a]['gravity'], summary[b]['gravity']):8.0f}" for b in dirs))
    print(f"\n  -> {'ACCEPT' if ok else 'FLAGGED: a direction is not one repeatable motion'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-direction consistency check for prompted sessions")
    parser.add_argument("sessions", nargs="*", help="session ids; default: all prompted sessions with marks")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--min-consistency", type=float, default=MIN_CONSISTENCY)
    args = parser.parse_args()

    ids = args.sessions
    if args.all or not ids:
        ids = sorted(p.name.removesuffix(".notes.json") for p in SESSIONS.glob("prompted_*.notes.json"))
    registry = load_registry()
    all_ok = True
    for sid in ids:
        all_ok &= report(sid, analyse_session(sid, registry), args.min_consistency)
        print()
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
