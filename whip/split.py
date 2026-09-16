"""
One fixed train / validation / test split, by session, with a hold-out that
is never trained on and never tuned on.

Decided 2026-09-16, replacing leave-one-session-out: the deployed model has
to train on every day's variety, and the number that matters is one model
scored once on sessions it never saw. So:

- **train**: most sessions; the deployed checkpoint trains on train + val.
- **val**: a few sessions for choosing the threshold and the seed. Nothing
  is reported on val.
- **test**: the hold-out. Scored by `probe.split score --part test`, and
  the sessions in it are not to be used for anything else.

Split is BY SESSION for every class recorded on more than one day, because
windows overlap 88% and any within-session split leaks. A class recorded on
ONE day (the snap / clap / wave session) cannot be split by session, so
that session is split BY TIME inside each class block, with a guard: a
window is assigned to a part only if it lies wholly inside that part's
interval, and the intervals are cut midway between consecutive cued
gestures, so no window straddles a cut. Ambient: one hour trains, the
other is halved by time into a val half (threshold) and a test half
(false-positive rate) -- the same halving `probe.rollout` already does.

The plan is a JSON file (`data/split.json`); the exporter of parts
(`probe.split make`) reads it and `data/windows.npz` and writes
`data/split/{train,val,test}.npz`. Changing the plan is a decision, not a
side effect: edit the file and re-make.
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
# Where a cued gesture's windows start and end, relative to its cue: the
# label covers cue .. cue+1.2 and a 2 s window that holds 70% of it starts
# no earlier than cue-0.5 and no later than cue+0.85.
MARK_BEFORE_S = 0.5
MARK_AFTER_S = 2.0

DEFAULT_PLAN = {
    "seed": 0,
    "sessions": {
        # multi-day flick sessions: by session
        "prompted_20260909_160303": "train",
        "prompted_20260912_013715": "train",
        "prompted_20260916_010218": "train",
        "prompted_20260916_044026": "train",
        "prompted_20260915_184744": "val",
        "prompted_20260916_010415": "val",
        "prompted_20260916_023243": "val",
        # test: a different day, a back-to-front wearing (frame-corrected), the
        # posture matrix, and a fill session with doubles -- never trained on
        "prompted_20260915_235801": "test",
        "prompted_20260916_040358": "test",
        "prompted_20260916_010756": "test",
        # negatives
        "negative_20260908_200022": "train",
        "negative_20260908_201610": "train",
        "negative_20260908_202143": "train",
        "negative_20260915_021616": "train",
        "negative_20260915_224235": "halves",     # first half val, second half test
    },
    # single-day classes: by time inside each class block, fractions per part
    "time_split": {"prompted_20260916_044426": [0.65, 0.15, 0.20]},
    # anything not named: train
    "default": "train",
}


@dataclass
class Interval:
    start: float
    end: float
    part: str


@dataclass
class Plan:
    sessions: dict[str, str]
    time_split: dict[str, list[float]]
    default: str = "train"
    seed: int = 0
    intervals: dict[str, list[Interval]] = field(default_factory=dict)   # filled by resolve()

    @classmethod
    def load(cls, path: Path) -> "Plan":
        doc = json.loads(Path(path).read_text())
        return cls(sessions=doc["sessions"], time_split=doc.get("time_split", {}),
                   default=doc.get("default", "train"), seed=doc.get("seed", 0))

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"seed": self.seed, "sessions": self.sessions,
                                          "time_split": self.time_split, "default": self.default}, indent=1))

    def part_of_session(self, sid: str) -> str:
        return self.sessions.get(sid, self.default)


def _time_split_intervals(sessions_dir: Path, sid: str, fractions: list[float], registry) -> list[Interval]:
    """
    Cut a blocked single-day session into parts per class block. Marks of
    each class (valid ones, in time order) are dealt to parts by the
    fractions; each part's interval runs from its first mark - MARK_BEFORE_S
    to its last mark + MARK_AFTER_S, and consecutive parts' intervals are
    trimmed to meet midway between the last mark of one and the first of the
    next. Cued spans (the wave) are cut by time at the same fractions.
    """
    notes = json.loads((sessions_dir / f"{sid}.notes.json").read_text())
    excluded = set(audit.excluded_cues(sessions_dir / f"{sid}.jsonl"))
    out: list[Interval] = []
    by_class: dict[str, list[float]] = {}
    for m in notes["marks"]:
        if "until" in m:
            a, b = m["cue_at"], m["until"]; t = a
            for frac, part in zip(fractions, PARTS):
                seg = (b - a) * frac
                out.append(Interval(t, t + seg, part)); t += seg
            continue
        if m["cue_at"] in excluded:
            continue
        spec = registry.resolve(m.get("label", ""))
        if spec is None:
            continue
        by_class.setdefault(spec.name, []).append(float(m["cue_at"]))
    for name, cues in by_class.items():
        cues.sort(); n = len(cues)
        n_train = int(round(fractions[0] * n)); n_val = int(round(fractions[1] * n))
        groups = [cues[:n_train], cues[n_train:n_train + n_val], cues[n_train + n_val:]]
        prev_end = None
        for part, g in zip(PARTS, groups):
            if not g:
                continue
            start, end = g[0] - MARK_BEFORE_S, g[-1] + MARK_AFTER_S
            if prev_end is not None and start < prev_end:
                mid = (prev_end + start) / 2
                out[-1].end = mid; start = mid
            out.append(Interval(start, end, part)); prev_end = end
    return out


def resolve(plan: Plan, sessions_dir: Path, all_sessions: list[str], registry=None) -> Plan:
    registry = registry or load_registry()
    for sid in all_sessions:
        if sid in plan.time_split:
            plan.intervals[sid] = _time_split_intervals(sessions_dir, sid, plan.time_split[sid], registry)
    return plan


def part_of_window(plan: Plan, sid: str, start_s: float, session_span: tuple[float, float]) -> str | None:
    """Which part a window belongs to, or None when it straddles a cut (dropped)."""
    if sid in plan.intervals:
        for iv in plan.intervals[sid]:
            if start_s >= iv.start and start_s + WINDOW_S <= iv.end:
                return iv.part
        return None
    role = plan.part_of_session(sid)
    if role == "halves":
        t0, t1 = session_span; mid = (t0 + t1) / 2
        if start_s + WINDOW_S <= mid - WINDOW_S:
            return "val"
        if start_s >= mid + WINDOW_S:
            return "test"
        return None
    return role


def part_of_mark(plan: Plan, sid: str, cue_at: float, session_span: tuple[float, float]) -> str | None:
    """Which part a cued gesture is scored in (its windows must be there too)."""
    t = cue_at + 0.6
    if sid in plan.intervals:
        for iv in plan.intervals[sid]:
            if iv.start <= t <= iv.end:
                return iv.part
        return None
    role = plan.part_of_session(sid)
    if role == "halves":
        t0, t1 = session_span; mid = (t0 + t1) / 2
        return "val" if t < mid - WINDOW_S else ("test" if t > mid + WINDOW_S else None)
    return role
