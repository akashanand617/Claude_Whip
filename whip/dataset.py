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
from whip.registry import DIRECTIONS, NONE_LABEL, Registry, class_name, load_registry

SAMPLE_RATE_HZ = 25.0

# Bumped whenever the stored windows change meaning. Version 2 despikes the
# stream before windowing, so a model trained on version 1 saw artifacts in its
# amplitude channel. Version 3 added a `motion` class; version 4 removes it in
# favour of the registry vocabulary (flick, double_flick, wave, snap, clap, ...)
# with data-driven labels, span labelling for sustained gestures, and a
# per-window direction. Version 5 keeps each window's mean gravity vector
# alongside the centred waveform: it was being subtracted and discarded, and it
# is the one feature that separates a palm-down flick from a hand-vertical one.
# Label indices and fields move at every one of these steps, so a stale export
# read by newer code silently means something else.
FORMAT_VERSION = 5

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

# Measured span of a real gesture: 480-1395 ms across 33 recordings. The
# registry carries a per-gesture duration; this is the default.
GESTURE_DURATION_S = 1.2

# Windows inside a cued sustained span (a 20 s "keep waving" block) quieter than
# this stay `none`. A span contains moments of stillness, and labelling silence
# as `wave` teaches exactly the wrong thing.
#
# Deliberately NOT the removed amplitude->class rule: that rule *invented* a
# class from loudness alone. This one only gates whether a window inside a
# human-labelled span was actually performing the labelled motion at that
# moment. The label source is the cue; amplitude is just hygiene.
HYGIENE_FLOOR_G = 0.5


def gesture_names(labels) -> list[str]:
    """Every class that fires an event -- everything except `none`."""
    return [str(name) for name in labels if str(name) != NONE_LABEL]


@dataclass
class Window:
    session_id: str
    start_s: float
    label: str
    # (3, WINDOW_SAMPLES) in g, gravity removed
    axes: list[list[float]]
    # "none" unless this window is a directed gesture from a prompted session.
    direction: str = "none"
    # The window's mean acceleration in g -- the gravity vector, i.e. the hand's
    # posture in the ring's frame. Removed from `axes` so static orientation
    # cannot shortcut gesture TYPE; kept here because posture is exactly what
    # tells a palm-down flick from a hand-vertical one, and a direction model
    # that cannot see it permutes directions between sessions.
    gravity: tuple[float, float, float] = (0.0, 0.0, 0.0)


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


# An excluded gesture's exclusion zone: half a second before the cue (an early
# start) to two seconds after (the longest window that can hold its tail).
EXCLUSION_BEFORE_S = 0.5
EXCLUSION_AFTER_S = 2.0


def _excluded_cues(capture_path: Path) -> list[float]:
    from whip import audit  # local: audit imports dataset for the stream decoder
    return audit.excluded_cues(capture_path)


def _marks_from_notes(notes, registry: Registry, duration_override: float | None):
    """
    Split a session's marks into point marks and span marks, canonically named.

    Point marks are prompted gestures: `{"label": "flag", "direction": "up",
    "cue_at": t}`. The cue fires when the instruction is given, so the gesture
    follows it -- the labelled span runs `cue_at .. cue_at + duration`.

    Span marks are cued motion blocks: `{"label": "none", "motion": "waving",
    "cue_at": t, "until": u}` -- twenty seconds of "keep doing this". If the
    motion name resolves in the registry the whole block is that gesture;
    unrecognised motions ("chin on hand", "dismissive flick") stay attribution
    only, exactly as before. That last part matters: the adversarial cues were
    *deliberate near-gestures recorded as negatives*, and promoting every cued
    motion to a class would quietly convert hard negatives into positives.
    """
    points: list[tuple[float, float, str, str]] = []
    spans: list[tuple[float, float, str]] = []
    for m in notes.marks:
        motion = m.get("motion")
        if motion is not None and "until" in m:
            spec = registry.resolve(motion)
            if spec is not None:
                spans.append((m["cue_at"], m["until"], spec.name))
            continue
        spec = registry.resolve(m.get("label", NONE_LABEL))
        if spec is not None:
            duration = duration_override if duration_override is not None else spec.duration_s
            # Direction values outside the canonical set ("any" from generic
            # gesture schedules, free text from early sessions) mean "no
            # direction supervision for this window", which is what "none" is.
            direction = m.get("direction", "none")
            if direction not in DIRECTIONS:
                direction = "none"
            # A split gesture without a usable direction cannot join any
            # sub-class; giving it the bare name would create an overlapping
            # class. It is skipped and counted, not guessed at.
            if spec.split_by_direction and direction == "none":
                continue
            points.append((m["cue_at"], m["cue_at"] + duration,
                           class_name(spec.name, direction, spec.split_by_direction), direction))
    return points, spans


def windows_from_session(
    capture_path: Path,
    notes_path: Path | None = None,
    gesture_duration_s: float | None = None,
    rate_tolerance: float = 1.0,
    declared_negative: bool = False,
    registry: Registry | None = None,
    hygiene_floor_g: float = HYGIENE_FLOOR_G,
) -> list[Window]:
    """
    Slice one session into labelled windows.

    Two labelling modes, decided by the *mark's* shape rather than the gesture's
    kind. Point marks use the coverage rule: >= 70% of the gesture inside the
    window labels it, 30-70% is ambiguous and dropped rather than guessed at.
    Span marks label every window fully inside the span, subject to the hygiene
    floor; windows straddling a span edge are ambiguous and dropped.

    Raises rather than guessing in two cases, both of which silently corrupt a
    training set:

    **Wrong sample rate.** WINDOW_SAMPLES describes 2.0 s only at 25 Hz. The same
    50 samples from a 50 Hz capture cover 1.0 s -- identical tensor shape, half
    the time span, and no error anywhere downstream.

    **Unknown provenance.** Treating "no notes" as "all negative" put 33 real
    gestures from the flick probe captures into the `none` class. A capture is
    negative only if it says so.
    """
    registry = registry or load_registry()
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
    points: list[tuple[float, float, str, str]] = []
    spans: list[tuple[float, float, str]] = []
    # Gestures the audit did not pass as valid (no motion, too late, not the
    # cued stroke structure, samples missing -- or merely uncertain: prompt
    # not followed, recoil at the double boundary, direction feature across
    # the cut). They are neither positives nor negatives: every window
    # touching them is ambiguous and dropped, exactly like a window straddling
    # a span edge. `probe.audit --write` produces the file; without one
    # nothing is excluded. Uncertain data is made up in the next session, not
    # trained on.
    excluded: list[tuple[float, float]] = [
        (cue - EXCLUSION_BEFORE_S, cue + EXCLUSION_AFTER_S) for cue in _excluded_cues(capture_path)]
    if notes_path and notes_path.exists():
        notes = session.load_notes(notes_path)
        points, spans = _marks_from_notes(notes, registry, gesture_duration_s)
        points = [p for p in points if not any(lo < p[0] < hi for lo, hi in excluded)]
        if not points and not spans and notes.kind not in ("negative",) and not declared_negative:
            raise UnlabelledCapture(
                f"{capture_path.name} has notes but no usable marks and is not declared "
                "negative; it may contain unlabelled gestures"
            )
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
        if any(min(t1, hi) > max(t0, lo) for lo, hi in excluded):
            continue

        # Remove the DC term so *static* orientation cannot be a shortcut, but do
        # not divide by the standard deviation: amplitude genuinely separates a
        # deliberate gesture from incidental motion. The swing of the gravity
        # vector during the window -- the wrist rotation a flick is made of --
        # survives the mean removal; see `model.to_model_input`.
        chunk = stream[:, start:end]
        means = chunk.mean(axis=1)
        centred = (chunk - means[:, None]) / accel.COUNTS_PER_G
        gravity = tuple(float(v) for v in means / accel.COUNTS_PER_G)

        label, direction, ambiguous = NONE_LABEL, "none", False
        for ges_start, ges_end, ges_label, ges_dir in points:
            cov = _coverage(t0, t1, ges_start, ges_end)
            if cov >= MIN_POSITIVE_COVERAGE:
                label, direction = ges_label, ges_dir
                break
            if cov > MAX_NEGATIVE_COVERAGE:
                ambiguous = True

        if label == NONE_LABEL:
            for span_start, span_end, span_label in spans:
                if t0 >= span_start and t1 <= span_end:
                    peak = float(np.sqrt((centred ** 2).sum(axis=0)).max())
                    # Inside the span but quiet: the wearer paused. `none` is
                    # correct, and unambiguous.
                    if peak >= hygiene_floor_g:
                        label = span_label
                    break
                if min(t1, span_end) > max(t0, span_start):
                    # Straddles a span edge: contains an unknown amount of the
                    # motion, so no label is defensible.
                    ambiguous = True

        if ambiguous and label == NONE_LABEL:
            continue

        out.append(Window(session_id=session_id, start_s=t0, label=label,
                          axes=[row.tolist() for row in centred], direction=direction,
                          gravity=gravity))

    return out


def load_all(
    directory: Path,
    gesture_duration_s: float | None = None,
    declared_negative: set[str] | None = None,
    registry: Registry | None = None,
) -> tuple[list[Window], list[str]]:
    """
    Every usable session in a directory, plus why each of the others was skipped.

    Skipping is reported rather than silent: a capture quietly dropped from the
    training set is as surprising as one quietly mislabelled.
    """
    registry = registry or load_registry()
    declared_negative = declared_negative or set()
    out: list[Window] = []
    skipped: list[str] = []
    for cap in sorted(Path(directory).glob("*.jsonl")):
        notes = cap.parent / f"{cap.stem}.notes.json"
        try:
            out.extend(windows_from_session(
                cap, notes if notes.exists() else None, gesture_duration_s,
                declared_negative=cap.stem in declared_negative, registry=registry))
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

    Version 2 despikes the stream before windowing; a version 1 export carries
    single-sample BLE artifacts that reach the model as a full-scale amplitude
    channel. Version 3 added a `motion` class; version 4 replaces it with the
    registry vocabulary and adds per-window direction. Every step moves the
    label indices, and every mismatch is silent about it.
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
    counts: dict[str, int] = {}
    directions: dict[str, int] = {}
    sessions: dict[str, int] = {}
    for w in windows:
        counts[w.label] = counts.get(w.label, 0) + 1
        if w.direction != "none":
            directions[w.direction] = directions.get(w.direction, 0) + 1
        sessions[w.session_id] = sessions.get(w.session_id, 0) + 1
    total = len(windows) or 1
    return {
        "total": len(windows),
        "counts": counts,
        "balance": {k: v / total for k, v in counts.items()},
        "directions": directions,
        "sessions": sessions,
    }
