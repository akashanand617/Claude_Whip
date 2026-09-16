"""
The fixed split is by GESTURE, stratified by class, random across sessions:
every gesture's windows stay together, boundaries meet midway between cues,
a window that straddles a boundary is dropped, and the non-gesture timeline
is dealt in chunks the same way.
"""
import json
from collections import Counter

import numpy as np

from whip import split as sp


def _session(tmp_path, sid, marks, spans=()):
    (tmp_path / f"{sid}.notes.json").write_text(json.dumps({"marks": marks + [
        {"label": "none", "motion": m, "cue_at": a, "until": b} for a, b, m in spans]}))
    (tmp_path / f"{sid}.jsonl").write_text("")


def test_gestures_are_dealt_per_class_across_sessions_and_windows_follow_their_gesture(tmp_path):
    marks_a = [{"index": i, "label": "flag", "direction": "up", "cue_at": 5.0 + 3 * i} for i in range(20)]
    marks_b = [{"index": i, "label": "flag", "direction": "up", "cue_at": 5.0 + 3 * i} for i in range(20)]
    _session(tmp_path, "a", marks_a); _session(tmp_path, "b", marks_b)
    plan = sp.Plan(seed=1, fractions=[0.6, 0.2, 0.2], chunk_s=20.0)
    sp.resolve(plan, tmp_path, {"a": (0.0, 70.0), "b": (0.0, 70.0)})
    parts = Counter(sp.part_of_mark(plan, s, m["cue_at"]) for s in ("a", "b") for m in marks_a)
    assert parts == {"train": 24, "val": 8, "test": 8}
    # both sessions contribute to every part (random across sessions, not by session)
    for part in sp.PARTS:
        assert {s for s in ("a", "b") for m in marks_a if sp.part_of_mark(plan, s, m["cue_at"]) == part} == {"a", "b"}
    # a window inside a gesture's interval goes with the gesture; one across the midpoint boundary is dropped
    cue = marks_a[3]["cue_at"]; part = sp.part_of_mark(plan, "a", cue)
    assert sp.part_of_window(plan, "a", cue - 0.4) == part
    boundary = cue + sp.MARK_AFTER_S + 0.25   # midway to the next cue at +3.0 (next start = cue+2.5)
    assert sp.part_of_window(plan, "a", boundary - 1.0) is None


def test_stratification_is_per_class_and_the_seed_fixes_it(tmp_path):
    marks = ([{"index": i, "label": "snap", "direction": "any", "cue_at": 5.0 + 3 * i} for i in range(10)]
             + [{"index": 10 + i, "label": "clap", "direction": "any", "cue_at": 40.0 + 3 * i} for i in range(10)])
    _session(tmp_path, "s", marks)
    p1 = sp.resolve(sp.Plan(seed=7, fractions=[0.6, 0.2, 0.2]), tmp_path, {"s": (0.0, 75.0)})
    p2 = sp.resolve(sp.Plan(seed=7, fractions=[0.6, 0.2, 0.2]), tmp_path, {"s": (0.0, 75.0)})
    for lab in ("snap", "clap"):
        c = Counter(sp.part_of_mark(p1, "s", m["cue_at"]) for m in marks if m["label"] == lab)
        assert c == {"train": 6, "val": 2, "test": 2}
    assert [iv.part for iv in p1.intervals["s"]] == [iv.part for iv in p2.intervals["s"]]


def test_negatives_and_spans_are_dealt_in_chunks(tmp_path):
    _session(tmp_path, "n", [])                                       # a pure negative recording
    _session(tmp_path, "w", [], spans=[(10.0, 70.0, "waving")])       # one 60 s wave span
    plan = sp.resolve(sp.Plan(seed=0, fractions=[0.5, 0.25, 0.25], chunk_s=20.0), tmp_path, {"n": (0.0, 200.0), "w": (0.0, 80.0)})
    kinds = Counter(iv.unit for iv in plan.intervals["n"])
    assert kinds == {"chunk": 10}
    dealt = Counter(iv.part for iv in plan.intervals["n"])
    assert sum(dealt.values()) == 10 and set(dealt) == set(sp.PARTS) and dealt["train"] >= 5
    wave = [iv for iv in plan.intervals["w"] if iv.unit == "span:wave"]
    assert len(wave) == 3 and {iv.part for iv in wave} == {"train", "val", "test"}
    # a window inside a chunk is assigned; one straddling two chunks is dropped
    assert sp.part_of_window(plan, "n", 5.0) == plan.intervals["n"][0].part
    assert sp.part_of_window(plan, "n", 19.0) is None
