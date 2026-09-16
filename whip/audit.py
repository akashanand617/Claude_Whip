"""
Per-gesture data-quality audit of a prompted session.

Run this right after recording, before the session goes into an export. It
answers the questions a label file cannot: did anything happen at the cue,
did it happen when the label says it did, does the stroke structure match the
cued class, does the motion agree with the cued direction, was the stream
intact, and did the wearer follow the amplitude prompt.

Why it exists (2026-09-15): the two doubles a held-out model missed were not
corrupt records. They were legitimate gestures whose stroke spacing (0.51 and
0.68 s) sat beyond every double in the training sessions (95th percentile
0.46 s), and one of them was cued "soft" and executed as the hardest stroke of
the session. Separately, the "brisk"/"deliberate" tempo prompt produced NO
measurable difference in any session -- the doubles corpus has one tempo. None
of that is visible from the notes file; all of it is visible from the stream.

The audit's output is a verdict per cued gesture:

- ``valid``   -- keep, train on it, score it.
- ``suspect`` -- something is unusual: prompt not followed, a single whose
  recoil looks like a second tap, direction feature on the wrong side of the
  cut. Listed so the session can be judged.
- ``invalid`` -- the record does not show the gesture that was cued: no
  motion, a peak under 1.5 g, a start later than 0.6 s after the cue, a
  double with one stroke or with a stroke spacing outside the defined range,
  samples missing inside the gesture.

**Both suspect and invalid are excluded** from training and scoring
(`EXCLUDED_VERDICTS`, decided 2026-09-15: uncertain data is dropped and made
up in the next session rather than trained on). ``dataset`` treats every
window touching an excluded gesture as ambiguous (dropped, never relabelled
`none`), ``probe.rollout`` does not score it, and ``shortfall()`` says how
many of each class the next session has to replace.

A double flick is DEFINED as two comparable taps at the natural quick
spacing: stroke peaks 0.20-0.50 s apart, second peak between half and twice
the first. That range is the measured corpus (p5-p95 of 132 training doubles:
0.22-0.46 s, 0.70-1.66) with a margin, not a preference. A "double" with a
0.7 s pause is a different gesture, and the prompt words that were supposed
to vary tempo ("brisk", "deliberate") did not move it in any session.

Everything here is numpy on the despiked stream, so it needs no model and no
hardware, and its findings do not depend on any checkpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from whip import accel, dataset, despike, session
from whip.registry import Registry, load_registry

# A stroke is a local maximum of |a - rest| above this, in g. Real strokes are
# 2-7 g; the wearer's stillness is under 0.3 g.
STROKE_FLOOR_G = 1.0
# Two maxima closer than this are one stroke with a noisy crest, not two.
MIN_STROKE_SPACING_S = 0.20
# A further stroke counts only if it reaches this fraction of the largest one.
STROKE_RATIO_FLOOR = 0.35
# Onset later than this after the cue is not a response to the cue: the
# corpus p95 is 0.47 s, and the label (cue .. cue + 1.2 s) would cover only
# half of a gesture that starts later. (Was 1.0 s; tightened 2026-09-15
# after a shape review of every flagged gesture.)
LATE_ONSET_S = 0.6
# A gesture whose peak never reaches this is a wobble, not a flick: the
# softest deliberate flicks in the corpus are 1.5-2.5 g, and every gesture
# under 1.5 g in the shape review was a multi-bump smear.
MIN_PEAK_G = 1.5
# The audit's look-ahead after the cue. Longer would run into the next prompt.
SPAN_S = 1.8
# The double flick, as a range: peak-to-peak spacing and second/first peak.
DOUBLE_GAP_RANGE_S = (0.20, 0.50)
DOUBLE_RATIO_RANGE = (0.50, 2.00)
# A single whose second bump is this much of its stroke, this late, is at
# the double boundary. Kept and listed.
SINGLE_SECOND_TAP_RATIO = 0.70
SINGLE_SECOND_TAP_GAP_S = 0.30
# Fraction of impulsive energy along gravity: above the cut is vertical motion
# (up/down), below is horizontal (left/right). One fixed cut separates the
# pairs for 95% of 296 gestures across three days (see `model.to_model_input`,
# group `gref`).
VERTICAL_CUT = 0.35
# Sample loss inside the gesture above this leaves a hole the model has never
# seen and the label cannot vouch for.
MAX_LOSS = 0.10
# The next cue closer than this puts the next gesture inside this label's
# 2.0 s windows.
MIN_CUE_SPACING_S = 2.0
FULL_SCALE_G = 32767 / accel.COUNTS_PER_G

INVALID_FLAGS = ("NO_MOTION", "WEAK", "LATE_ONSET", "DOUBLE_WITH_ONE_STROKE",
                 "DOUBLE_GAP_OUT_OF_RANGE", "DOUBLE_RATIO_OUT_OF_RANGE", "SAMPLE_LOSS",
                 "MANUAL_EXCLUDE")
# A late but otherwise clean gesture can be re-anchored: its mark's cue_at is
# moved so the onset sits here, where the corpus median onset is. The original
# cue time is kept on the mark as `cue_at_original`. Only LATE_ONSET gestures
# with no other invalid flag qualify -- a late double with a pause stays out.
REANCHOR_ONSET_S = 0.2
REANCHOR_MAX_ONSET_S = 1.5
SUSPECT_FLAGS = ("CUED_SOFT_DID_HARD", "CUED_HARD_DID_SOFT", "SINGLE_SECOND_TAP",
                 "DIRECTION_PAIR_MISMATCH", "CUE_COLLISION")

AUDIT_SUFFIX = ".audit.json"
# Verdicts the exporter and the rollout leave out. Only `valid` trains.
EXCLUDED_VERDICTS = ("invalid", "suspect")


@dataclass
class GestureAudit:
    index: int
    cue_at: float
    label: str          # canonical gesture name
    direction: str
    amplitude: str      # the prompt's amplitude word, or ""
    tempo: str          # the prompt's tempo word, or ""
    peak_g: float
    onset_s: float | None      # first sample above the floor, relative to the cue
    strokes: list[tuple[float, float]]   # (time after cue, peak g) per stroke, in time order
    vertical_frac: float | None = None   # impulsive energy along gravity / total
    clip_frac: float = 0.0               # samples at the +/-4.09 g rail, of the gesture span
    loss: float = 0.0                    # missing samples in the gesture span, as a fraction
    next_cue_s: float | None = None      # seconds to the next mark
    flags: list[str] = field(default_factory=list)

    @property
    def stroke_gap_s(self) -> float | None:
        return self.strokes[1][0] - self.strokes[0][0] if len(self.strokes) >= 2 else None

    @property
    def stroke_ratio(self) -> float | None:
        """Second stroke peak over first, for doubles: 1.0 is two equal taps."""
        return self.strokes[1][1] / self.strokes[0][1] if len(self.strokes) >= 2 else None

    @property
    def verdict(self) -> str:
        if any(f in INVALID_FLAGS for f in self.flags):
            return "invalid"
        if self.flags:
            return "suspect"
        return "valid"

    def to_json(self) -> dict:
        d = asdict(self)
        d["strokes"] = [[round(t, 3), round(g, 3)] for t, g in self.strokes]
        d["stroke_gap_s"] = self.stroke_gap_s
        d["stroke_ratio"] = self.stroke_ratio
        d["verdict"] = self.verdict
        return d


def strokes_in(mag: np.ndarray, t_rel: np.ndarray) -> list[tuple[float, float]]:
    """Local maxima of |a| above the floor, at least MIN_STROKE_SPACING_S apart, in time order."""
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


def vertical_fraction(x_g: np.ndarray, rest: np.ndarray) -> float | None:
    """
    Fraction of the impulsive (high-pass) energy that lies along gravity, for a
    (3, N) gesture segment in g. Same construction as the `gref` channel group:
    a relation between a and g in one frame, so it does not depend on how the
    ring sits on the finger.
    """
    if x_g.shape[1] < 12:
        return None
    from whip.model import _moving_average, GRAVITY_WINDOW
    g = rest / max(np.linalg.norm(rest), 1e-6)
    lin = x_g - _moving_average(x_g, GRAVITY_WINDOW)
    along = g @ lin
    tot = float((lin ** 2).sum())
    return float((along ** 2).sum() / tot) if tot > 0 else None


def audit_gesture(x_g: np.ndarray, times: np.ndarray, cue_at: float) -> dict:
    """
    Measurements for one cued gesture. `x_g` is (3, N) in g, despiked; rest is
    the mean over the second before the cue.
    """
    pre = (times >= cue_at - 1.0) & (times < cue_at - 0.2)
    win = (times >= cue_at - 0.3) & (times <= cue_at + SPAN_S)
    if pre.sum() < 5 or win.sum() < 10:
        return dict(peak_g=0.0, onset_s=None, strokes=[], vertical_frac=None, clip_frac=0.0, loss=1.0)
    rest = x_g[:, pre].mean(axis=1)
    seg = x_g[:, win]
    mag = np.linalg.norm(seg - rest[:, None], axis=0)
    t_rel = times[win] - cue_at
    peak = float(mag.max())
    above = np.where(mag > STROKE_FLOOR_G)[0]
    onset = float(t_rel[above[0]]) if len(above) else None
    expected = (SPAN_S + 0.3) * dataset.SAMPLE_RATE_HZ
    loss = max(0.0, 1.0 - win.sum() / expected)
    clip = float((np.abs(seg) >= 0.98 * FULL_SCALE_G).any(axis=0).mean())
    return dict(peak_g=peak, onset_s=onset, strokes=strokes_in(mag, t_rel),
                vertical_frac=vertical_fraction(seg, rest), clip_frac=clip, loss=loss)


def _flags_for(g: GestureAudit) -> list[str]:
    flags: list[str] = []
    if g.loss > MAX_LOSS:
        flags.append("SAMPLE_LOSS")
    if g.peak_g < STROKE_FLOOR_G:
        flags.append("NO_MOTION")
        return flags
    if g.peak_g < MIN_PEAK_G:
        flags.append("WEAK")
    if g.onset_s is not None and g.onset_s > LATE_ONSET_S:
        flags.append("LATE_ONSET")
    is_double = g.label.startswith("double_")
    if is_double:
        if len(g.strokes) == 1:
            flags.append("DOUBLE_WITH_ONE_STROKE")
        elif len(g.strokes) >= 2:
            lo, hi = DOUBLE_GAP_RANGE_S
            if not (lo <= g.stroke_gap_s <= hi):
                flags.append("DOUBLE_GAP_OUT_OF_RANGE")
            lo, hi = DOUBLE_RATIO_RANGE
            if not (lo <= g.stroke_ratio <= hi):
                flags.append("DOUBLE_RATIO_OUT_OF_RANGE")
    else:
        # Stroke COUNT is not a hard check for singles: a recoil is often
        # 40-60% of the stroke and 0.25-0.35 s later, the same size as a weak
        # second tap at 25 Hz. That boundary is the model's job. Only a second
        # bump that is nearly a full tap, at double spacing, is listed.
        if len(g.strokes) >= 2 and g.stroke_ratio >= SINGLE_SECOND_TAP_RATIO \
                and g.stroke_gap_s >= SINGLE_SECOND_TAP_GAP_S:
            flags.append("SINGLE_SECOND_TAP")
    if g.vertical_frac is not None and g.direction in ("up", "down", "left", "right"):
        vertical = g.direction in ("up", "down")
        if (g.vertical_frac >= VERTICAL_CUT) != vertical:
            flags.append("DIRECTION_PAIR_MISMATCH")
    if g.next_cue_s is not None and g.next_cue_s < MIN_CUE_SPACING_S:
        flags.append("CUE_COLLISION")
    # Clipping is measured (`clip_frac`) but never flagged: every hard flick
    # clips at the +/-4.09 g rail, and the model has a saturation channel for it.
    return flags


def audit_session(capture_path: Path, notes_path: Path, registry: Registry | None = None) -> list[GestureAudit]:
    registry = registry or load_registry()
    times_l, samples = dataset._decode_stream(capture_path)
    times = np.asarray(times_l)
    stream = despike.hampel(np.array(
        [[s.x for s in samples], [s.y for s in samples], [s.z for s in samples]], dtype=float))
    x_g = stream / accel.COUNTS_PER_G
    notes = session.load_notes(notes_path)
    point_marks = [(i, m) for i, m in enumerate(notes.marks) if "until" not in m]
    out: list[GestureAudit] = []
    for n, (i, m) in enumerate(point_marks):
        spec = registry.resolve(m.get("label", ""))
        if spec is None or spec.kind != "impulsive":
            continue
        meas = audit_gesture(x_g, times, m["cue_at"])
        nxt = point_marks[n + 1][1]["cue_at"] - m["cue_at"] if n + 1 < len(point_marks) else None
        g = GestureAudit(index=m.get("index", i), cue_at=float(m["cue_at"]), label=spec.name,
                         direction=m.get("direction", "none"), amplitude=m.get("amplitude", ""),
                         tempo=m.get("tempo", ""), next_cue_s=nxt, **meas)
        g.flags = _flags_for(g)
        if m.get("exclude"):
            # The wearer's own call, recorded on the mark ("did it too early
            # and redid it late", "phone rang"). The audit cannot know that.
            g.flags.append("MANUAL_EXCLUDE")
        out.append(g)
    _flag_prompt_adherence(out)
    return out


def reanchorable(g: GestureAudit) -> bool:
    """A late gesture whose only fault is lateness, and not absurdly late."""
    return ("LATE_ONSET" in g.flags and g.onset_s is not None and g.onset_s <= REANCHOR_MAX_ONSET_S
            and not any(f in INVALID_FLAGS and f != "LATE_ONSET" for f in g.flags))


def reanchor(notes_path: Path, audits: list[GestureAudit]) -> list[int]:
    """
    Move the cue_at of every re-anchorable mark so its onset lands at
    REANCHOR_ONSET_S after the (new) cue, keeping the original as
    `cue_at_original`. Returns the mark indices changed. Re-run the audit
    afterwards; the moved marks then measure as on-time.
    """
    doc = json.loads(notes_path.read_text())
    by_index = {g.index: g for g in audits if reanchorable(g)}
    changed = []
    for m in doc.get("marks", []):
        g = by_index.get(m.get("index"))
        if g is None or "until" in m or abs(m["cue_at"] - g.cue_at) > 1e-6:
            continue
        m["cue_at_original"] = m["cue_at"]
        m["cue_at"] = round(g.cue_at + g.onset_s - REANCHOR_ONSET_S, 3)
        changed.append(m["index"])
    if changed:
        notes_path.write_text(json.dumps(doc, indent=2))
    return changed


def exclude_marks(notes_path: Path, indices: list[int], reason: str) -> list[int]:
    """Record the wearer's exclusion on the given marks; the audit then flags them MANUAL_EXCLUDE."""
    doc = json.loads(notes_path.read_text())
    done = []
    for m in doc.get("marks", []):
        if m.get("index") in indices and "until" not in m:
            m["exclude"] = reason
            done.append(m["index"])
    if done:
        notes_path.write_text(json.dumps(doc, indent=2))
    return done


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
    out: dict = {"n": len(audits), "by_flag": {}, "by_verdict": {"valid": 0, "suspect": 0, "invalid": 0}}
    for a in audits:
        out["by_verdict"][a.verdict] += 1
        for f in a.flags:
            out["by_flag"][f] = out["by_flag"].get(f, 0) + 1
    out["flagged"] = sum(1 for a in audits if a.flags)
    doubles = [a for a in audits if a.label.startswith("double_") and a.stroke_gap_s is not None]
    if doubles:
        gaps = np.array([a.stroke_gap_s for a in doubles]); ratios = np.array([a.stroke_ratio for a in doubles])
        out["double_gap_s"] = {"p5": float(np.percentile(gaps, 5)), "p50": float(np.median(gaps)), "p95": float(np.percentile(gaps, 95))}
        out["double_ratio"] = {"p5": float(np.percentile(ratios, 5)), "p50": float(np.median(ratios)), "p95": float(np.percentile(ratios, 95))}
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


# ---------------------------------------------------------------------------
# The audit file: written next to the session, read by the exporter.

def audit_path(capture_path: Path) -> Path:
    return capture_path.with_name(capture_path.stem + AUDIT_SUFFIX)


def write_audit(capture_path: Path, audits: list[GestureAudit]) -> Path:
    path = audit_path(capture_path)
    doc = {
        "session_id": capture_path.stem,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ranges": {"double_gap_s": DOUBLE_GAP_RANGE_S, "double_ratio": DOUBLE_RATIO_RANGE,
                   "late_onset_s": LATE_ONSET_S, "stroke_floor_g": STROKE_FLOOR_G},
        "summary": summary(audits),
        "gestures": [a.to_json() for a in audits],
    }
    path.write_text(json.dumps(doc, indent=1))
    return path


def excluded_cues(capture_path: Path, verdicts: tuple[str, ...] = EXCLUDED_VERDICTS) -> list[float]:
    """
    Cue times of gestures the audit gave one of `verdicts`, or [] when no
    audit file exists. The exporter and the rollout use this to leave those
    gestures out.
    """
    path = audit_path(capture_path)
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    return [float(g["cue_at"]) for g in doc.get("gestures", []) if g.get("verdict") in verdicts]


def invalid_cues(capture_path: Path) -> list[float]:
    """Only the invalid ones (kept for reporting; exclusion uses `excluded_cues`)."""
    return excluded_cues(capture_path, ("invalid",))


def shortfall(audits: list[GestureAudit]) -> dict[str, int]:
    """
    How many gestures of each class the next session has to make up: every
    cued gesture that is not `valid`, keyed by `label_direction` (or `label`
    when undirected), in registry-ish order of first appearance.
    """
    out: dict[str, int] = {}
    for a in audits:
        if a.verdict == "valid":
            continue
        key = f"{a.label}_{a.direction}" if a.direction not in ("", "none") else a.label
        out[key] = out.get(key, 0) + 1
    return out


def corpus_shortfall(sessions_dir: Path, target: int | None = None) -> dict[str, int]:
    """
    What the next session has to record to make every class the same size:
    `target - valid` per class, over every audit file in the directory.

    `target` defaults to the MEDIAN valid count over the classes (rounded
    up): the classes below the middle are brought up to it. The largest class
    was the first default, and one class that happened to collect extra
    valid gestures from partial sessions then made every other class "short"
    -- a target that ran away from the corpus. Passing a target grows every
    class to it. Counting excluded gestures instead (the very first version)
    kept re-asking for gestures that a later session had already replaced.
    Reads the files, so `probe.audit --all --write` must have run.
    """
    valid: dict[str, int] = {}
    for path in sorted(Path(sessions_dir).glob("*" + AUDIT_SUFFIX)):
        doc = json.loads(path.read_text())
        for g in doc.get("gestures", []):
            d = g.get("direction", "none")
            key = f"{g['label']}_{d}" if d not in ("", "none", "any") else g["label"]
            valid.setdefault(key, 0)
            if g.get("verdict") == "valid":
                valid[key] += 1
    if not valid:
        return {}
    import math
    goal = target if target is not None else int(math.ceil(float(np.median(list(valid.values())))))
    return {k: goal - v for k, v in valid.items() if goal - v > 0}


def valid_counts(sessions_dir: Path) -> dict[str, int]:
    """Valid gestures per class over every audit file in the directory."""
    valid: dict[str, int] = {}
    for path in sorted(Path(sessions_dir).glob("*" + AUDIT_SUFFIX)):
        for g in json.loads(path.read_text()).get("gestures", []):
            d = g.get("direction", "none")
            key = f"{g['label']}_{d}" if d not in ("", "none", "any") else g["label"]
            valid[key] = valid.get(key, 0) + (1 if g.get("verdict") == "valid" else 0)
    return valid


# ---------------------------------------------------------------------------
# Ring frame: which way round the ring was worn in a session.
#
# Room-frame left/right needs the finger axis to point the known way. A session
# recorded with the ring back to front is not bad data -- its frame is rotated
# by a half-turn -- so it is corrected at export rather than thrown away. The
# correction is a named proper rotation stored next to the session; the
# exporter applies it to the whole stream before anything else.

FRAME_ROTATIONS = {
    "identity":   ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "flip_axis0": ((1, 0, 0), (0, -1, 0), (0, 0, -1)),   # half-turn about the finger: same way round
    "flip_axis1": ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),   # back to front
    "flip_axis2": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),   # back to front
}
FRAME_SUFFIX = ".frame.json"


def frame_path(capture_path: Path) -> Path:
    return capture_path.with_name(capture_path.stem + FRAME_SUFFIX)


def set_frame(capture_path: Path, name: str, evidence: str = "") -> Path:
    if name not in FRAME_ROTATIONS:
        raise ValueError(f"unknown frame rotation {name!r}; one of {sorted(FRAME_ROTATIONS)}")
    path = frame_path(capture_path)
    path.write_text(json.dumps({"session_id": capture_path.stem, "rotation": name, "evidence": evidence,
                                "set": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1))
    return path


def frame_for(capture_path: Path):
    """(3, 3) rotation to apply to the session's stream, identity when no frame file exists."""
    path = frame_path(capture_path)
    name = json.loads(path.read_text())["rotation"] if path.exists() else "identity"
    return np.asarray(FRAME_ROTATIONS[name], dtype=float)


# ---------------------------------------------------------------------------
# The hand rule: which way round was the ring, from the gestures themselves.
#
# In the room frame (gravity, gravity x finger), a left flick's first stroke
# accelerates one way along the lateral axis and a right flick's the other.
# Which sign is "left" depends only on which way the finger axis points, i.e.
# which way round the ring is on. Measured over every session: 25-39 of the
# left/right flicks in a session agree with the majority sign, 1-8 disagree,
# so a session's majority is unambiguous. CANONICAL is the sensor-below
# wearing (2026-09-16): left flicks lateral-NEGATIVE, right POSITIVE.

CANONICAL_LEFT_SIGN = -1
STROKE_SAMPLES = 5   # first 200 ms of the stroke: acceleration leads velocity, so this is the way the hand moved


def lateral_sign(window_g: np.ndarray, gravity: np.ndarray) -> int | None:
    """Sign of the first stroke's lateral component for one (3, W) centred window in g, or None if no stroke."""
    from whip.model import _moving_average, GRAVITY_WINDOW, FINGER_AXIS
    g = gravity / max(np.linalg.norm(gravity), 1e-6)
    f = np.zeros(3); f[FINGER_AXIS] = 1.0
    l = np.cross(g, f); ln = np.linalg.norm(l)
    if ln < 0.3:
        return None
    lin = window_g - _moving_average(window_g, GRAVITY_WINDOW)
    mag = np.linalg.norm(lin, axis=0); above = np.where(mag > STROKE_FLOOR_G)[0]
    if not len(above):
        return None
    k0 = above[0]
    h = float(((l / ln) @ lin)[k0:k0 + STROKE_SAMPLES].sum())
    return 1 if h > 0 else -1


def hand_rule(capture_path: Path, notes_path: Path, registry: Registry | None = None) -> dict:
    """
    Majority lateral sign of the session's valid left and right flicks, in the
    frame the exporter would use (frame file applied). Returns
    {"left": (+n, -n), "right": (+n, -n), "agrees": True/False/None}; `agrees`
    is whether the session matches CANONICAL, None when there are no
    left/right flicks to judge by.
    """
    from whip import dataset
    registry = registry or load_registry()
    windows = dataset.windows_from_session(capture_path, notes_path, registry=registry)
    counts = {"left": [0, 0], "right": [0, 0]}
    for w in windows:
        if w.direction not in counts or not w.label.startswith("flick"):
            continue
        s = lateral_sign(np.asarray(w.axes, dtype=float), np.asarray(w.gravity, dtype=float))
        if s is None:
            continue
        counts[w.direction][0 if s > 0 else 1] += 1
    votes = counts["left"][1] + counts["right"][0] - counts["left"][0] - counts["right"][1]   # + = canonical
    total = sum(counts["left"]) + sum(counts["right"])
    return {"left": tuple(counts["left"]), "right": tuple(counts["right"]),
            "agrees": None if total < 3 else votes > 0, "windows": total}
