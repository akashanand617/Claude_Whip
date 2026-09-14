"""
Turn recorded sessions into labelled windows.

Every constant here was measured rather than assumed, and several of them
started out wrong. See docs/COLLECTION.md for the measurements.

The labelling rule is the subtle part. A gesture spans ~5 windows at 70%
coverage, and windows near the edges contain a fraction of it. Forcing a label
onto a window holding 40% of a flick teaches noise, so those are **dropped**
rather than guessed at -- the debouncer covers the gap, since a real gesture
still sits cleanly inside several windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from whip import accel, capture, despike, protocol, session

SAMPLE_RATE_HZ = 25.0

# Bumped whenever the stored windows change meaning. Version 2 despikes the
# stream before windowing; a model trained on version 1 data saw artifacts in
# its amplitude channel and is not comparable.
FORMAT_VERSION = 2

# 50 samples = 2.0 s. Sized so a 1395 ms worst-case gesture leaves ~600 ms of
# alignment slack; an earlier 38-sample window left only 125 ms, which meant
# almost every training window held a clipped gesture.
WINDOW_SAMPLES = 50
STRIDE_SAMPLES = 6  # 0.24 s

# A window holding at least this much of a gesture is labelled with it; at most
# MAX_NEGATIVE_COVERAGE it is a negative. Anything between is ambiguous and
# excluded -- do not force a label onto a window you cannot confidently label.
MIN_POSITIVE_COVERAGE = 0.70
MAX_NEGATIVE_COVERAGE = 0.30

# Measured span of a real gesture: 480-1395 ms across 33 recordings.
GESTURE_DURATION_S = 1.2

LABELS = ("none", "flag", "approve")
LABEL_INDEX = {name: i for i, name in enumerate(LABELS)}


@dataclass
class Window:
    session_id: str
    start_s: float
    label: str
    # (3, WINDOW_SAMPLES) in g, gravity removed
    axes: list[list[float]]

    @property
    def label_index(self) -> int:
        return LABEL_INDEX[self.label]


def _decode_stream(path: Path) -> tuple[list[float], list[accel.AccelSample]]:
    _, records = capture.load_capture(path)
    acc = [
        (t, p) for t, p in records
        if len(p) >= 8 and p[0] == protocol.CMD_RAW_SENSOR and p[1] == protocol.SUBTYPE_ACCEL
    ]
    return [t for t, _ in acc], [accel.decode(p) for _, p in acc]


def _coverage(win_start: float, win_end: float, ges_start: float, ges_end: float) -> float:
    """Fraction of the gesture that falls inside the window."""
    overlap = min(win_end, ges_end) - max(win_start, ges_start)
    span = ges_end - ges_start
    return max(0.0, overlap) / span if span > 0 else 0.0


class UnlabelledCapture(Exception):
    """A capture whose contents cannot be safely assumed to be negative."""


class WrongSampleRate(Exception):
    """A capture recorded at a rate the window geometry does not describe."""


def _sample_rate(times: list[float]) -> float:
    span = times[-1] - times[0]
    return (len(times) - 1) / span if span > 0 else 0.0


def windows_from_session(
    capture_path: Path,
    notes_path: Path | None = None,
    gesture_duration_s: float = GESTURE_DURATION_S,
    rate_tolerance: float = 1.0,
    declared_negative: bool = False,
) -> list[Window]:
    """
    Slice one session into labelled windows.

    Gestures are located by cue timestamp. The cue fires when the instruction is
    given, so the gesture follows it -- the labelled span runs from the cue to
    cue + duration.

    Raises rather than guessing in two cases, both of which silently corrupt a
    training set:

    **Wrong sample rate.** WINDOW_SAMPLES describes 2.0 s only at 25 Hz. The same
    50 samples from a 50 Hz capture cover 1.0 s -- identical tensor shape, half
    the time span, and no error anywhere downstream.

    **Unknown provenance.** Treating "no notes" as "all negative" put 33 real
    gestures from the flick probe captures into the `none` class. A capture is
    negative only if it says so.
    """
    times, samples = _decode_stream(capture_path)
    if len(samples) < WINDOW_SAMPLES:
        return []

    # Despike the whole stream at once rather than per window. The filter is
    # local, so applying it window by window would treat every window boundary
    # as a stream edge -- and at 88% overlap each sample would be filtered nine
    # times, with a different neighbourhood each time.
    stream = despike.hampel(np.array(
        [[s.x for s in samples], [s.y for s in samples], [s.z for s in samples]], dtype=float))

    rate = _sample_rate(times)
    if abs(rate - SAMPLE_RATE_HZ) > rate_tolerance:
        raise WrongSampleRate(
            f"{capture_path.name} is {rate:.1f} Hz; window geometry assumes {SAMPLE_RATE_HZ}"
        )

    session_id = capture_path.stem
    marks: list[tuple[float, float, str]] = []
    if notes_path and notes_path.exists():
        notes = session.load_notes(notes_path)
        for m in notes.marks:
            label = m.get("label", "none")
            if label in ("flag", "approve"):
                marks.append((m["cue_at"], m["cue_at"] + gesture_duration_s, label))
    else:
        header, _ = capture.load_capture(capture_path)
        kind = (header or {}).get("session_kind") or (header or {}).get("kind")
        if kind != "negative" and not declared_negative:
            raise UnlabelledCapture(
                f"{capture_path.name} has no marks and is not declared negative; "
                "it may contain unlabelled gestures"
            )

    out: list[Window] = []
    for start in range(0, len(samples) - WINDOW_SAMPLES + 1, STRIDE_SAMPLES):
        end = start + WINDOW_SAMPLES
        t0, t1 = times[start], times[end - 1]

        label, ambiguous = "none", False
        for ges_start, ges_end, ges_label in marks:
            cov = _coverage(t0, t1, ges_start, ges_end)
            if cov >= MIN_POSITIVE_COVERAGE:
                label = ges_label
                break
            if cov > MAX_NEGATIVE_COVERAGE:
                ambiguous = True
        if ambiguous and label == "none":
            continue

        # Remove the DC term so *static* orientation cannot be a shortcut, but do
        # not divide by the standard deviation: amplitude genuinely separates a
        # deliberate gesture from incidental motion.
        #
        # Note what this does *not* remove. Subtracting the mean kills the average
        # attitude of the hand, which is a session artifact and worth losing. The
        # swing of the gravity vector during the window survives it, and that
        # swing is the wrist rotation a flick is made of. So the gravity dynamics
        # are still here to be separated out downstream -- see
        # `model.to_model_input`. An earlier plan called for storing raw g to
        # recover them, which was unnecessary and would have handed the model back
        # the orientation shortcut.
        chunk = stream[:, start:end]
        axes = [((row - row.mean()) / accel.COUNTS_PER_G).tolist() for row in chunk]

        out.append(Window(session_id=session_id, start_s=t0, label=label, axes=axes))

    return out


def load_all(
    directory: Path,
    gesture_duration_s: float = GESTURE_DURATION_S,
    declared_negative: set[str] | None = None,
) -> tuple[list[Window], list[str]]:
    """
    Every usable session in a directory, plus why each of the others was skipped.

    Skipping is reported rather than silent: a capture quietly dropped from the
    training set is as surprising as one quietly mislabelled.
    """
    declared_negative = declared_negative or set()
    out: list[Window] = []
    skipped: list[str] = []
    for cap in sorted(Path(directory).glob("*.jsonl")):
        notes = cap.parent / f"{cap.stem}.notes.json"
        try:
            out.extend(windows_from_session(
                cap, notes if notes.exists() else None, gesture_duration_s,
                declared_negative=cap.stem in declared_negative))
        except (UnlabelledCapture, WrongSampleRate) as exc:
            skipped.append(str(exc))
    return out, skipped


def split_by_session(
    windows: list[Window], test_sessions: set[str], val_sessions: set[str] | None = None
) -> dict[str, list[Window]]:
    """
    Partition by session, never by window.

    Windows overlap 88% at this stride, one gesture yields ~5 of them, and
    session artifacts are constant within a session. A random window split would
    report near-perfect accuracy and mean nothing.
    """
    val_sessions = val_sessions or set()
    out: dict[str, list[Window]] = {"train": [], "val": [], "test": []}
    for w in windows:
        if w.session_id in test_sessions:
            out["test"].append(w)
        elif w.session_id in val_sessions:
            out["val"].append(w)
        else:
            out["train"].append(w)
    return out


class StaleDataset(Exception):
    """An exported window set produced by an older, incompatible pipeline."""


def check_format_version(loaded) -> int:
    """
    Refuse a window set whose contents no longer mean what the code expects.

    Version 2 despikes the stream before windowing. A version 1 export has
    single-sample BLE artifacts in it, which reach the model as a full-scale
    amplitude channel -- so a model trained on one and evaluated against the
    other is not comparable, and nothing downstream would notice.
    """
    found = int(loaded["format_version"]) if "format_version" in loaded else 1
    if found != FORMAT_VERSION:
        raise StaleDataset(
            f"window set is format v{found}, this code expects v{FORMAT_VERSION}. "
            f"Re-export with: python -m probe.dataset --out data/windows.npz"
        )
    return found


def split_session_by_time(
    windows: list[Window], session_id: str, fraction: float = 0.5, guard_s: float = WINDOW_SAMPLES / SAMPLE_RATE_HZ
) -> tuple[list[Window], list[Window]]:
    """
    Cut one session in two along the time axis.

    Exists so a threshold can be calibrated on data it is not then reported on.
    There is only one long negative session (10 minutes of typing), and using it
    for both jobs is what made every previous false-positive figure optimistic.
    Splitting it by time gives two disjoint stretches of the same activity.

    `guard_s` drops windows straddling the cut. Windows overlap 88% and each
    spans 2.0 s, so without a guard band the last window of the first half and
    the first of the second share most of their samples -- which is precisely
    the leak the split is meant to close.
    """
    chosen = sorted((w for w in windows if w.session_id == session_id), key=lambda w: w.start_s)
    if not chosen:
        return [], []
    span_start, span_end = chosen[0].start_s, chosen[-1].start_s
    cut = span_start + (span_end - span_start) * fraction
    first = [w for w in chosen if w.start_s + WINDOW_SAMPLES / SAMPLE_RATE_HZ <= cut]
    second = [w for w in chosen if w.start_s >= cut + guard_s]
    return first, second


def summarise(windows: list[Window]) -> dict:
    counts = {name: 0 for name in LABELS}
    sessions: dict[str, int] = {}
    for w in windows:
        counts[w.label] += 1
        sessions[w.session_id] = sessions.get(w.session_id, 0) + 1
    total = len(windows) or 1
    return {
        "total": len(windows),
        "counts": counts,
        "balance": {k: v / total for k, v in counts.items()},
        "sessions": sessions,
    }
