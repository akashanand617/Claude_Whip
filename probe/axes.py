"""
Work out which axis the wrist actually rotates about, instead of assuming.

    python -m probe.axes
    python -m probe.axes --session prompted_20260909_160303

`model.augment` rotates axes 1 and 2 about axis 0, on the assumption that axis 0
is the finger axis -- the one a ring spins around when it shifts on the finger.
`CLAUDE.md` has carried that as unverified since the augmentation was written. If
it is wrong, the augmentation has been synthesising motion the ring never makes,
and it is a live candidate for the session-holdout gap.

**Method.** A flick is a rotation. Under a rotation about a unit axis `n`, the
gravity vector in the ring's frame turns about `n`, so its component along `n`
stays constant while the perpendicular components sweep. The axis of rotation is
therefore the direction of least variance in the gravity trajectory -- the
eigenvector of its covariance with the smallest eigenvalue.

This needs raw captures, not `data/windows.npz`: the exported windows have the DC
term removed, which is exactly the gravity direction this measurement depends on.

The ratio of eigenvalues matters as much as the direction. If the smallest is not
clearly smaller than the others, the motion was not a clean rotation about any
single axis and the answer means nothing -- which is reported rather than hidden.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from whip import accel, dataset

SESSIONS = Path("data/sessions")
GRAVITY_WINDOW = 9          # matches model.GRAVITY_WINDOW: ~2.8 Hz at 25 Hz
AXIS_NAMES = ("x", "y", "z")


def gravity_track(samples, width: int = GRAVITY_WINDOW) -> np.ndarray:
    """Low-passed acceleration: the gravity vector over time, in g. Returns (3, N)."""
    raw = np.array([[s.x for s in samples], [s.y for s in samples], [s.z for s in samples]],
                   dtype=float) / accel.COUNTS_PER_G
    kernel = np.ones(width) / width
    return np.stack([np.convolve(row, kernel, mode="same") for row in raw])


def rotation_axis(track: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Least-variance direction of a gravity trajectory, plus all three eigenvalues.

    Returns (unit axis, eigenvalues ascending). The axis is only meaningful when
    the smallest eigenvalue is well below the others.
    """
    centred = track - track.mean(axis=1, keepdims=True)
    values, vectors = np.linalg.eigh(np.cov(centred))
    return vectors[:, 0], values


def describe_axis(axis: np.ndarray) -> str:
    """Which stored axis this is closest to, and how close."""
    best = int(np.argmax(np.abs(axis)))
    return f"{AXIS_NAMES[best]} (|cos| = {abs(axis[best]):.3f})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Find the wrist rotation axis empirically")
    parser.add_argument("--session", action="append", default=[],
                        help="session id; default is every prompted session with marks")
    parser.add_argument("--pre-roll", type=float, default=0.2,
                        help="seconds before the cue to include")
    parser.add_argument("--duration", type=float, default=dataset.GESTURE_DURATION_S)
    args = parser.parse_args()

    # Path.stem strips only the final suffix, so "x.notes.json" stems to "x.notes".
    ids = args.session or sorted(
        sid for sid in (p.name.removesuffix(".notes.json") for p in SESSIONS.glob("*.notes.json"))
        if (SESSIONS / f"{sid}.jsonl").exists())
    if not ids:
        print("no marked sessions found under data/sessions")
        return 1

    print("Which axis does a flick rotate about?")
    print("Gravity turns about the rotation axis, so that axis is the direction of")
    print("least variance in the gravity trajectory.\n")

    per_session = {}
    for sid in ids:
        cap = SESSIONS / f"{sid}.jsonl"
        notes_path = SESSIONS / f"{sid}.notes.json"
        try:
            times, samples = dataset._decode_stream(cap)
        except Exception as exc:                      # noqa: BLE001 - report, do not crash a survey
            print(f"  {sid}: unreadable ({exc})")
            continue
        if len(samples) < 50:
            continue
        marks = [m for m in json.loads(notes_path.read_text()).get("marks", [])
                 if m.get("label") in ("flag", "approve")]
        if not marks:
            continue

        times = np.asarray(times)
        track = gravity_track(samples)

        axes, ratios = [], []
        for m in marks:
            lo = np.searchsorted(times, m["cue_at"] - args.pre_roll)
            hi = np.searchsorted(times, m["cue_at"] + args.duration)
            if hi - lo < 15:
                continue
            axis, values = rotation_axis(track[:, lo:hi])
            if values[2] <= 0:
                continue
            # Sign is arbitrary for an eigenvector; fix it so they can be averaged.
            if axis[int(np.argmax(np.abs(axis)))] < 0:
                axis = -axis
            axes.append(axis)
            ratios.append(values[0] / values[2])

        if not axes:
            continue
        mean_axis = np.mean(axes, axis=0)
        mean_axis /= np.linalg.norm(mean_axis)
        # How tightly the per-gesture axes agree. Low means the rotation axis
        # wanders, so a single answer would be a fiction.
        agreement = float(np.mean([abs(np.dot(a, mean_axis)) for a in axes]))
        per_session[sid] = (mean_axis, agreement, float(np.median(ratios)), len(axes))

        print(f"  {sid}   n={len(axes)}")
        print(f"    axis            [{mean_axis[0]:+.3f} {mean_axis[1]:+.3f} {mean_axis[2]:+.3f}]"
              f"  -> closest to {describe_axis(mean_axis)}")
        print(f"    agreement       {agreement:.3f}   (1.0 = every gesture rotates about the same axis)")
        print(f"    flatness        {np.median(ratios):.3f}   (low = a clean rotation, "
              f"high = not a rotation at all)")

    if not per_session:
        print("no gestures could be measured")
        return 1

    print("\n" + "=" * 72)
    overall = np.mean([v[0] for v in per_session.values()], axis=0)
    overall /= np.linalg.norm(overall)
    print(f"  rotation axis across sessions  [{overall[0]:+.3f} {overall[1]:+.3f} {overall[2]:+.3f}]")
    print(f"  closest stored axis            {describe_axis(overall)}")

    assumed = np.array([1.0, 0.0, 0.0])
    alignment = abs(float(np.dot(overall, assumed)))
    print(f"\n  model.augment rotates axes 1 and 2 about axis 0, i.e. assumes [+1 0 0].")
    print(f"  alignment with the measured axis: {alignment:.3f}")
    if alignment > 0.9:
        print("  -> the assumption holds. The augmentation models real variation.")
    elif alignment > 0.6:
        print("  -> partly. The augmentation is off-axis and is synthesising some motion")
        print("     the ring does not make; worth rotating about the measured axis instead.")
    else:
        print("  -> the assumption is WRONG. The augmentation has been rotating about an")
        print("     axis unrelated to how the ring actually moves, which would explain")
        print("     why rotation augmentation hurt when it was tried at +/-30 degrees.")

    if len(per_session) > 1:
        ids_ = list(per_session)
        pair = abs(float(np.dot(per_session[ids_[0]][0], per_session[ids_[1]][0])))
        print(f"\n  between-session axis agreement {pair:.3f}")
        print("  (low means the ring sat differently on the finger between sessions,")
        print("   which is distribution shift rather than overfitting -- a different fix)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
