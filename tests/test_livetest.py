"""
The live test's scoring is pure: a cue is a hit when the first event in its
window matches gesture and direction, wrong when another arrives, a miss
when nothing does; events outside every cue window are spurious.
"""
from pathlib import Path

from probe import livetest
from whip import session
from whip.registry import load_registry


def ev(t, name, direction="none"):
    return {"t_s": t, "name": name, "direction": direction, "confidence": 0.9}


def test_score_cue_hit_wrong_miss():
    events = [ev(11.2, "flick", "up"), ev(20.5, "flick", "left"), ev(40.0, "snap")]
    assert livetest.score_cue("flick_up", events, 10.0)[0:2] == ("hit", 1.2)
    assert livetest.score_cue("flick_right", events, 19.0)[0] == "wrong"
    assert livetest.score_cue("snap", events, 30.0)[0] == "miss"
    assert livetest.score_cue("snap", events, 39.0)[0:2] == ("hit", 1.0)
    # an onset just before the cue is the cue's (early starts are a fifth of the corpus); a second earlier is not
    assert livetest.score_cue("flick_up", [ev(9.5, "flick", "up")], 10.0)[0] == "hit"
    assert livetest.score_cue("flick_up", [ev(9.0, "flick", "up")], 10.0)[0] == "miss"


def test_summary_counts_spurious_outside_cue_windows():
    cues = [livetest.CueResult(0, 10.0, "flick_up", [], "hit", 1.1), livetest.CueResult(1, 20.0, "snap", [], "miss", None),
            livetest.CueResult(2, 30.0, "double_clap", [], "wrong", 1.4)]
    events = [ev(11.1, "flick", "up"), ev(31.4, "snap"), ev(50.0, "flick", "down"), ev(55.0, "wave")]
    s = livetest.summarize(cues, events, minutes=1.0)
    assert (s["cues"], s["hits"], s["wrong"], s["miss"]) == (3, 1, 1, 1)
    assert s["spurious_events"] == 2 and s["spurious_per_hour"] == 120.0
    assert s["by_class"]["flick_up"]["latency_s"] == 1.1


def test_schedule_covers_every_impulsive_class_with_directions():
    class A: gestures = None; rounds = 1; seed = 3
    sched = livetest.build_schedule(A(), load_registry())
    names = {livetest.expected_name(p, load_registry()) for p in sched}
    assert names == {f"flick_{d}" for d in session.DIRECTIONS} | {f"double_flick_{d}" for d in session.DIRECTIONS} | {"snap", "double_clap"}
    assert len(sched) == 10


def test_report_reads_a_finished_log(tmp_path, capsys):
    p = tmp_path / "livetest_x.jsonl"
    p.write_text("\n".join([
        '{"kind": "header", "cues": 2}',
        '{"kind": "cue", "index": 0, "cue_at": 5.0, "expected": "snap", "verdict": "hit", "latency_s": 1.2, "fired": ["snap/none"]}',
        '{"kind": "event", "t_s": 6.2, "name": "snap", "direction": "none", "confidence": 0.9}',
        '{"kind": "cue", "index": 1, "cue_at": 12.0, "expected": "flick_up", "verdict": "miss", "latency_s": null, "fired": []}',
    ]) + "\n")
    assert livetest.report(p) == 0
    out = capsys.readouterr().out
    assert "reconstructed" in out and "hits 1" in out and "flick_up" in out
