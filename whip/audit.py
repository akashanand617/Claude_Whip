"""
Per-gesture data-quality audit of a prompted session.

Run this right after recording, before the session goes into an export. It
answers the questions that a label file cannot: did anything happen at the
cue, did it happen when the label says it did, does the stroke count match the
cued class, and did the wearer follow the amplitude and tempo prompts at all.

Why it exists (2026-09-15): the two doubles a held-out model missed were not
corrupt records. They were legitimate gestures whose stroke spacing (0.51 and
0.68 s) sat beyond every double in the training sessions (95th percentile
0.46 s), and one of them was cued "soft" and executed as the hardest stroke of
the session. Separately, the "brisk"/"deliberate" tempo prompt produced NO
measurable difference in any session -- the doubles corpus has one tempo. None
of that is visible from the notes file; all of it is visible from the stream.

Everything here is numpy on the despiked stream, so it needs no model and no
hardware, and its findings do not depend on any checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from whip import accel, dataset, despike, session
from whip.registry import Registry, load_registry

# A stroke is a local maximum of |a - rest| above this, in g. Real strokes are
# 2-7 g; the wearer's stillness is under 0.3 g.
STROKE_FLOOR_G = 1.0
# Two maxima closer than this are one stroke with a noisy crest, not two.
MIN_STROKE_SPACING_S = 0.20
# A second stroke counts only if it reaches this fraction of the larger one.
STROKE_RATIO_FLOOR = 0.35
# Onset later than this after the cue is outside what the coverage rule was
# designed for; the label still lands on the gesture, but only just.
LATE_ONSET_S = 1.0
# The audit's look-ahead after the cue. Longer would run into the next prompt.
SPAN_S = 1.8


@dataclass
class GestureAudit:
    index: int
    label: str          # canonical gesture name
    direction: str
    amplitude: str      # the prompt's amplitude word, or ""
    tempo: str          # the prompt's tempo word, or ""
    peak_g: float
    onset_s: float | None      # first sample above the floor, relative to the cue
    strokes: list[tuple[float, float]]   # (time after cue, peak g) per stroke, in time order
    flags: list[str] = field(default_factory=list)

    @property
    def stroke_gap_s(self) -> float | None:
        return self.strokes[1][0] - self.strokes[0][0] if len(self.strokes) >= 2 else None

    @property
    def stroke_ratio(self) -> float | None:
        """Second stroke peak over first, for doubles: 1.0 is two equal taps."""
        return self.strokes[1][1] / self.strokes[0][1] if len(self.strokes) >= 2 else None


def strokes_in(mag: np.ndarray, t_rel: np.ndarray) -> list[tuple[float, float]]:
    """Local maxima of |a| above the floor, at least MIN_STROKE_SPACING_S apart, strongest first."""
    cand = [i for i in range(1, len(mag) - 1)
            if mag[i] >= mag[i - 1] and mag[i] > mag[i + 1] and mag[i] > STROKE_FLOOR_G]
    cand.sort(key=lambda i: -mag[i])
    kept: list[int] = []
    for i in cand:
        if all(abs(t_rel[i] - t_rel[j]) >= MIN_STROKE_SPACING_S for j in kept):
            kept.append(i)
    if not kept:
        return []
    top = mag[kept[0]]
    kept = [i for i in kept if mag[i] >= STROKE_RATIO_FLOOR * top]
    return sorted((float(t_rel[i]), float(mag[i])) for i in kept)


def audit_gesture(x_g: np.ndarray, times: np.ndarray, cue_at: float, label: str,
                  registry: Registry) -> tuple[float, float | None, list[tuple[float, float]]]:
    """
    (peak g, onset s after cue, strokes) for one cued gesture. `x_g` is (3, N)
    in g, despiked; rest is the mean over the second before the cue.
    """
    pre = (times >= cue_at - 1.0) & (times < cue_at - 0.2)
    win = (times >= cue_at - 0.3) & (times <= cue_at + SPAN_S)
    if pre.sum() < 5 or win.sum() < 10:
        return 0.0, None, []
    rest = x_g[:, pre].mean(axis=1)
    mag = np.linalg.norm(x_g[:, win] - rest[:, None], axis=0)
    t_rel = times[win] - cue_at
    peak = float(mag.max())
    above = np.where(mag > STROKE_FLOOR_G)[0]
    onset = float(t_rel[above[0]]) if len(above) else None
    return peak, onset, strokes_in(mag, t_rel)


def audit_session(capture_path: Path, notes_path: Path, registry: Registry | None = None) -> list[GestureAudit]:
    registry = registry or load_registry()
    times_l, samples = dataset._decode_stream(capture_path)
    times = np.asarray(times_l)
    stream = despike.hampel(np.array(
        [[s.x for s in samples], [s.y for s in samples], [s.z for s in samples]], dtype=float))
    x_g = stream / accel.COUNTS_PER_G
    notes = session.load_notes(notes_path)
    out: list[GestureAudit] = []
    for i, m in enumerate(notes.marks):
        if "until" in m:
            continue
        spec = registry.resolve(m.get("label", ""))
        if spec is None or spec.kind != "impulsive":
            continue
        peak, onset, strokes = audit_gesture(x_g, times, m["cue_at"], spec.name, registry)
        g = GestureAudit(index=m.get("index", i), label=spec.name, direction=m.get("direction", "none"),
                         amplitude=m.get("amplitude", ""), tempo=m.get("tempo", ""),
                         peak_g=peak, onset_s=onset, strokes=strokes)
        if peak < STROKE_FLOOR_G:
            g.flags.append("NO_MOTION")
        elif onset is not None and onset > LATE_ONSET_S:
            g.flags.append("LATE_ONSET")
        # Stroke COUNT is not a hard check: a single flick's recoil is often
        # 40-60% of its stroke and 0.25-0.35 s later, indistinguishable by
        # amplitude from a weak second tap -- which is exactly the boundary
        # the model has to learn. The list is reported; only the one
        # unambiguous case is flagged.
        if spec.name.startswith("double_") and peak >= STROKE_FLOOR_G and len(strokes) == 1:
            g.flags.append("DOUBLE_WITH_ONE_STROKE")
        out.append(g)
    _flag_prompt_adherence(out)
    return out


def _flag_prompt_adherence(audits: list[GestureAudit]) -> None:
    """A 'soft' gesture louder than the session's median 'hard' one (or the reverse) did not follow the prompt."""
    for name in {a.label for a in audits}:
        soft = [a.peak_g for a in audits if a.label == name and a.amplitude == "soft" and a.peak_g >= STROKE_FLOOR_G]
        hard = [a.peak_g for a in audits if a.label == name and a.amplitude == "hard" and a.peak_g >= STROKE_FLOOR_G]
        if len(soft) < 3 or len(hard) < 3:
            continue
        soft_med, hard_med = float(np.median(soft)), float(np.median(hard))
        for a in audits:
            if a.label != name or a.peak_g < STROKE_FLOOR_G:
                continue
            if a.amplitude == "soft" and a.peak_g > hard_med:
                a.flags.append("CUED_SOFT_DID_HARD")
            if a.amplitude == "hard" and a.peak_g < soft_med:
                a.flags.append("CUED_HARD_DID_SOFT")


def summary(audits: list[GestureAudit]) -> dict:
    """Session-level numbers the collection protocol should be judged on."""
    out: dict = {"n": len(audits), "flagged": sum(1 for a in audits if a.flags), "by_flag": {}}
    for a in audits:
        for f in a.flags:
            out["by_flag"][f] = out["by_flag"].get(f, 0) + 1
    doubles = [a for a in audits if a.label.startswith("double_") and a.stroke_gap_s is not None]
    if doubles:
        gaps = np.array([a.stroke_gap_s for a in doubles]); ratios = np.array([a.stroke_ratio for a in doubles])
        out["double_gap_s"] = {"p5": float(np.percentile(gaps, 5)), "p50": float(np.median(gaps)), "p95": float(np.percentile(gaps, 95))}
        out["double_ratio"] = {"p5": float(np.percentile(ratios, 5)), "p50": float(np.median(ratios)), "p95": float(np.percentile(ratios, 95))}
    # Did the tempo prompt do anything? Compare stroke gap (doubles) / onset-to-peak (singles) by tempo word.
    tempo: dict[str, list[float]] = {}
    for a in doubles:
        if a.tempo:
            tempo.setdefault(a.tempo, []).append(a.stroke_gap_s)
    if len(tempo) >= 2:
        out["double_gap_by_tempo"] = {k: float(np.median(v)) for k, v in tempo.items() if v}
    amp: dict[str, list[float]] = {}
    for a in audits:
        if a.amplitude and a.peak_g >= STROKE_FLOOR_G:
            amp.setdefault(a.amplitude, []).append(a.peak_g)
    if len(amp) >= 2:
        out["peak_by_amplitude"] = {k: float(np.median(v)) for k, v in amp.items() if v}
    return out
