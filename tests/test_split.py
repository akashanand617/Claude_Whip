"""
The fixed split: by session for multi-day classes, by time inside class
blocks for a single-day session, with no window straddling a cut, and the
ambient hour halved into a val half and a test half with a guard.
"""
import json

import numpy as np

from whip import split as sp


def _plan(**kw):
    return sp.Plan(sessions=kw.get("sessions", {}), time_split=kw.get("time_split", {}), default="train")


def test_session_level_parts_and_the_default():
    plan = _plan(sessions={"a": "test", "b": "val"})
    assert sp.part_of_window(plan, "a", 10.0, (0, 100)) == "test"
    assert sp.part_of_window(plan, "b", 10.0, (0, 100)) == "val"
    assert sp.part_of_window(plan, "unnamed", 10.0, (0, 100)) == "train"
    assert sp.part_of_mark(plan, "a", 10.0, (0, 100)) == "test"


def test_halves_split_an_ambient_session_by_time_with_a_guard():
    plan = _plan(sessions={"n": "halves"})
    span = (0.0, 100.0)
    assert sp.part_of_window(plan, "n", 10.0, span) == "val"
    assert sp.part_of_window(plan, "n", 80.0, span) == "test"
    assert sp.part_of_window(plan, "n", 49.0, span) is None          # straddles the midpoint guard
    assert sp.part_of_mark(plan, "n", 10.0, span) == "val" and sp.part_of_mark(plan, "n", 80.0, span) == "test"


def test_time_split_deals_each_class_block_by_fraction_and_never_straddles(tmp_path):
    # a blocked session: 10 snaps at 3 s spacing, then 10 claps; one 30 s wave span
    marks = [{"index": i, "label": "snap", "direction": "any", "cue_at": 5.0 + 3 * i} for i in range(10)]
    marks += [{"index": 10 + i, "label": "clap", "direction": "any", "cue_at": 40.0 + 3 * i} for i in range(10)]
    marks += [{"label": "none", "motion": "wave", "cue_at": 80.0, "until": 110.0}]
    (tmp_path / "s.notes.json").write_text(json.dumps({"marks": marks}))
    (tmp_path / "s.jsonl").write_text("")
    plan = _plan(time_split={"s": [0.6, 0.2, 0.2]})
    sp.resolve(plan, tmp_path, ["s"])
    parts = [sp.part_of_mark(plan, "s", m["cue_at"], (0, 120)) for m in marks[:20]]
    assert parts[:10] == ["train"] * 6 + ["val"] * 2 + ["test"] * 2
    assert parts[10:] == ["train"] * 6 + ["val"] * 2 + ["test"] * 2
    # a window fully inside a part is assigned; one crossing a cut is dropped
    assert sp.part_of_window(plan, "s", 5.0, (0, 120)) == "train"
    cut = [iv for iv in plan.intervals["s"] if iv.part == "val"][0].start
    assert sp.part_of_window(plan, "s", cut - 1.0, (0, 120)) is None
    # the wave span is cut by the same fractions
    wave = [iv for iv in plan.intervals["s"] if iv.start >= 80.0]
    assert [iv.part for iv in wave] == ["train", "val", "test"] and abs(wave[0].end - 98.0) < 1e-6
