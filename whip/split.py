"""
One fixed train / validation / test split, BY GESTURE, random across every
session, with a hold-out that is never trained on and never tuned on.

Decided 2026-09-16 (replacing a by-session split that same day: session
sizes are lopsided, one session holds a whole class, and the deployed model
trains on every day's variety anyway). Rules:

- Every valid cued gesture is a unit. Units are dealt to train / val / test
  at random, STRATIFIED BY CLASS, with a fixed seed, so each part has the
  same class mix and the same across-session variety.
- A gesture's windows all go where the gesture goes. Windows overlap 88%, so
  the leak to guard against is a window that holds part of one gesture and
  part of another in a different part: a window is assigned only if it lies
  wholly inside one unit's interval, and consecutive units' intervals meet
  midway between their cues. Anything straddling a boundary is dropped.
- Everything that is not a gesture -- ambient wear, typing, the quiet
  between cues -- is cut into CHUNK_S-second chunks that are dealt to parts
  at random too, with the same wholly-inside rule, so the false-positive
  rate is measured on chunks from every negative recording rather than on
  one session's second half.
- A cued span (the wave) is cut into chunks the same way; each chunk's
  windows keep the span label.

`data/split.json` holds the seed, fractions and chunk length; `probe.split
make` reads it and `data/windows.npz` and writes
`data/split/{train,val,test,trainval}.npz`. Change the seed only as a
decision: the test part is the same set of gestures for every model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from whip import audit
from whip.registry import load_registry

PARTS = ("train", "val", "test")
WINDOW_S = 2.0
# A cued gesture's labelled windows START anywhere from cue-1.4 (a 2 s
# window holding 70% of the cue..cue+1.2 label) to cue+0.85, so they END up
# to cue+2.85. The unit's interval must hold all of them, or a run is cut
# short and never fires -- the first bounds (cue-0.5 .. cue+2.0) kept ~3 of
# ~10 windows per gesture and scored 4/69 on val.
MARK_BEFORE_S = 1.4
MARK_AFTER_S = 2.85

DEFAULT_PLAN = {"seed": 0, "fractions": [0.65, 0.15, 0.20], "chunk_s": 20.0}


@dataclass
class Interval:
    start: float
    end: float
    part: str
    unit: str            # "gesture:<class>", "span:<class>" or "chunk"


@dataclass
class Plan:
    seed: int = 0
    fractions: list[float] = field(default_factory=lambda: list(DEFAULT_PLAN["fractions"]))
    chunk_s: float = 20.0
    intervals: dict[str, list[Interval]] = field(default_factory=dict)   # per session, filled by resolve()

    @classmethod
    def load(cls, path: Path) -> "Plan":
        doc = json.loads(Path(path).read_text())
        return cls(seed=doc.get("seed", 0), fractions=list(doc.get("fractions", DEFAULT_PLAN["fractions"])),
                   chunk_s=float(doc.get("chunk_s", DEFAULT_PLAN["chunk_s"])))

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"seed": self.seed, "fractions": self.fractions, "chunk_s": self.chunk_s}, indent=1))


def _deal(n: int, fractions, rng) -> list[str]:
    """`n` part labels in the given proportions, shuffled: stratification within one class."""
    counts = [int(round(f * n)) for f in fractions]
    counts[0] += n - sum(counts)
    labels = [p for p, c in zip(PARTS, counts) for _ in range(c)]
    rng.shuffle(labels)
    return labels


def _chunks(t0: float, t1: float, chunk_s: float, rng, unit: str) -> list[Interval]:
    out = []
    t = t0
    while t1 - t > 1e-6:
        out.append(Interval(t, min(t + chunk_s, t1), "", unit)); t += chunk_s
    return out


def resolve(plan: Plan, sessions_dir: Path, session_spans: dict[str, tuple[float, float]], registry=None) -> Plan:
    """
    Build every session's intervals. Two passes: gestures are dealt per class
    across all sessions (stratified), then chunks and span pieces are dealt.
    """
    registry = registry or load_registry()
    rng = np.random.default_rng(plan.seed)
    gestures: dict[str, list[tuple[str, float]]] = {}      # class -> [(session, cue)]
    spans: dict[str, list[tuple[float, float, str]]] = {}   # session -> [(start, end, class)]
    for sid in sorted(session_spans):
        notes = sessions_dir / f"{sid}.notes.json"
        if not notes.exists():
            continue
        bad = set(audit.excluded_cues(sessions_dir / f"{sid}.jsonl"))
        for m in json.loads(notes.read_text()).get("marks", []):
            if "until" in m:
                spec = registry.resolve(m.get("motion", ""))
                if spec is not None:
                    spans.setdefault(sid, []).append((float(m["cue_at"]), float(m["until"]), spec.name))
                continue
            if m["cue_at"] in bad:
                continue
            spec = registry.resolve(m.get("label", ""))
            if spec is None:
                continue
            d = m.get("direction", "none")
            name = f"{spec.name}_{d}" if spec.split_by_direction and d in ("up", "down", "left", "right") else spec.name
            gestures.setdefault(name, []).append((sid, float(m["cue_at"])))
    assigned: dict[str, list[tuple[float, str, str]]] = {}     # session -> [(cue, part, class)]
    for name in sorted(gestures):
        units = gestures[name]
        for (sid, cue), part in zip(units, _deal(len(units), plan.fractions, rng)):
            assigned.setdefault(sid, []).append((cue, part, name))
    for sid, (t0, t1) in session_spans.items():
        ivs: list[Interval] = []
        marks = sorted(assigned.get(sid, []))
        # gesture intervals, meeting midway between consecutive cues
        for i, (cue, part, name) in enumerate(marks):
            start = cue - MARK_BEFORE_S; end = cue + MARK_AFTER_S
            if i > 0:
                prev_end = marks[i - 1][0] + MARK_AFTER_S
                if start < prev_end:
                    mid = (prev_end + start) / 2; ivs[-1].end = mid; start = mid
            ivs.append(Interval(start, end, part, f"gesture:{name}"))
        # spans: chunked, keeping the class
        for a, b, name in spans.get(sid, []):
            ivs += _chunks(a, b, plan.chunk_s, rng, f"span:{name}")
        ivs.sort(key=lambda iv: iv.start)
        # the rest of the timeline: chunks
        rest: list[Interval] = []; cursor = t0
        for iv in ivs:
            if iv.start - cursor > WINDOW_S:
                rest += _chunks(cursor, iv.start, plan.chunk_s, rng, "chunk")
            cursor = max(cursor, iv.end)
        if t1 - cursor > WINDOW_S:
            rest += _chunks(cursor, t1, plan.chunk_s, rng, "chunk")
        ivs = sorted(ivs + rest, key=lambda iv: iv.start)
        # deal the unassigned (chunks and span pieces), stratified by unit kind
        for kind in sorted({iv.unit for iv in ivs if not iv.part}):
            todo = [iv for iv in ivs if iv.unit == kind and not iv.part]
            for iv, part in zip(todo, _deal(len(todo), plan.fractions, rng)):
                iv.part = part
        plan.intervals[sid] = ivs
    return plan


def part_of_window(plan: Plan, sid: str, start_s: float) -> str | None:
    """Which part a window belongs to, or None when it straddles a boundary (dropped)."""
    for iv in plan.intervals.get(sid, ()):
        if start_s >= iv.start and start_s + WINDOW_S <= iv.end:
            return iv.part
    return None


def part_of_mark(plan: Plan, sid: str, cue_at: float) -> str | None:
    t = cue_at + 0.6
    for iv in plan.intervals.get(sid, ()):
        if iv.unit.startswith("gesture:") and iv.start <= t <= iv.end:
            return iv.part
    return None
