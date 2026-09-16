"""
The session audit flags what a label file cannot show: no motion at a cue,
a late gesture, a stroke structure outside the defined double, motion on the
wrong side of gravity for the cued direction, and a wearer who ignored the
amplitude prompt. Its verdicts are written next to the session and honoured
by the exporter.
"""

import json

import numpy as np
import pytest

from whip import audit
from whip.registry import load_registry


def _stroke(mag_g: float, width: int = 6, axis: int = 1):
    """A one-lobe |a| bump on one axis, `width` samples wide."""
    w = np.hanning(width + 2)[1:-1]; w = w / w.max()
    out = np.zeros((3, width)); out[axis] = mag_g * w
    return out


def _stream(events, seconds=4.0, rest=(0.0, 0.0, 1.0), axis=1):
    """A still wearer (gravity `rest`) with strokes added at (t_s, peak_g) pairs. Returns (x_g, times)."""
    n = int(seconds * 25)
    x = np.tile(np.asarray(rest, float)[:, None], (1, n))
    for t_s, g in events:
        k = int(t_s * 25)
        s = _stroke(g, axis=axis)
        x[:, k:k + s.shape[1]] += s
    return x, np.arange(n) / 25.0


R = load_registry()


def _ga(label, direction, meas, **kw):
    g = audit.GestureAudit(index=0, cue_at=2.0, label=label, direction=direction, amplitude=kw.get("amplitude", ""),
                           tempo="", next_cue_s=kw.get("next_cue_s", 3.5), **meas)
    g.flags = audit._flags_for(g)
    return g


def test_a_single_at_the_cue_is_valid():
    x, t = _stream([(2.1, 4.0)])
    m = audit.audit_gesture(x, t, cue_at=2.0)
    assert m["peak_g"] == pytest.approx(4.0, abs=0.05)
    assert 0.0 <= m["onset_s"] < 0.2 and len(m["strokes"]) == 1 and m["loss"] == pytest.approx(0, abs=0.05)
    assert _ga("flick", "none", m).verdict == "valid"


def test_a_quick_equal_double_is_valid_and_a_slow_one_is_invalid():
    x, t = _stream([(2.1, 4.0), (2.45, 3.6)])          # 0.35 s apart, ratio 0.9
    g = _ga("double_flick", "none", audit.audit_gesture(x, t, 2.0))
    assert len(g.strokes) == 2 and g.verdict == "valid"
    x, t = _stream([(2.1, 4.0), (2.8, 3.6)])           # 0.70 s apart: a pause, not a double
    g = _ga("double_flick", "none", audit.audit_gesture(x, t, 2.0))
    assert g.stroke_gap_s == pytest.approx(0.7, abs=0.05)
    assert "DOUBLE_GAP_OUT_OF_RANGE" in g.flags and g.verdict == "invalid"


def test_an_unequal_double_is_invalid_and_a_one_stroke_double_too():
    x, t = _stream([(2.1, 2.0), (2.45, 5.0)])          # second tap 2.5x the first
    g = _ga("double_flick", "none", audit.audit_gesture(x, t, 2.0))
    assert "DOUBLE_RATIO_OUT_OF_RANGE" in g.flags and g.verdict == "invalid"
    x, t = _stream([(2.1, 5.0)])
    g = _ga("double_flick", "none", audit.audit_gesture(x, t, 2.0))
    assert g.flags == ["DOUBLE_WITH_ONE_STROKE"] and g.verdict == "invalid"


def test_a_noisy_crest_is_one_stroke_and_a_faint_bump_is_not_a_stroke():
    x, t = _stream([(2.1, 4.0), (2.18, 3.5)])          # 80 ms apart
    assert len(audit.audit_gesture(x, t, 2.0)["strokes"]) == 1
    x, t = _stream([(2.1, 5.0), (2.6, 1.2)])           # 24% of the main stroke
    assert len(audit.audit_gesture(x, t, 2.0)["strokes"]) == 1


def test_a_single_with_a_full_second_tap_is_suspect_not_invalid():
    x, t = _stream([(2.1, 4.0), (2.5, 3.5)])
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0))
    assert g.flags == ["SINGLE_SECOND_TAP"] and g.verdict == "suspect"
    # a normal recoil (half the stroke, 0.25 s later) is nothing
    x, t = _stream([(2.1, 4.0), (2.35, 2.0)])
    assert _ga("flick", "none", audit.audit_gesture(x, t, 2.0)).verdict == "valid"


def test_no_motion_weak_late_onset_and_sample_loss_are_invalid():
    x, t = _stream([])
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0))
    assert g.flags == ["NO_MOTION"] and g.verdict == "invalid"
    x, t = _stream([(2.8, 4.0)])                        # 0.8 s after the cue
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0))
    assert "LATE_ONSET" in g.flags and g.verdict == "invalid"
    x, t = _stream([(2.1, 1.3)])                        # a 1.3 g wobble
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0))
    assert "WEAK" in g.flags and g.verdict == "invalid"
    x, t = _stream([(2.1, 4.0)])
    keep = ~((t > 2.4) & (t < 3.0))                     # a 0.6 s hole after the stroke
    g = _ga("flick", "none", audit.audit_gesture(x[:, keep], t[keep], 2.0))
    assert "SAMPLE_LOSS" in g.flags and g.verdict == "invalid"


def test_direction_pair_is_checked_against_gravity():
    # gravity along axis 2; a stroke along axis 2 is vertical motion, along axis 1 horizontal
    x, t = _stream([(2.1, 4.0)], rest=(0.0, 0.0, 1.0), axis=2)
    m = audit.audit_gesture(x, t, 2.0)
    assert m["vertical_frac"] > audit.VERTICAL_CUT
    assert _ga("flick", "up", m).verdict == "valid"
    assert "DIRECTION_PAIR_MISMATCH" in _ga("flick", "left", m).flags
    x, t = _stream([(2.1, 4.0)], rest=(0.0, 0.0, 1.0), axis=1)
    m = audit.audit_gesture(x, t, 2.0)
    assert m["vertical_frac"] < audit.VERTICAL_CUT
    assert _ga("flick", "left", m).verdict == "valid"
    assert "DIRECTION_PAIR_MISMATCH" in _ga("flick", "up", m).flags


def test_cue_collision_is_suspect():
    x, t = _stream([(2.1, 4.0)])
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0), next_cue_s=1.5)
    assert g.flags == ["CUE_COLLISION"] and g.verdict == "suspect"


def test_prompt_adherence_flags_a_soft_cue_done_hard():
    mk = lambda i, amp, peak: audit.GestureAudit(i, 2.0, "flick", "up", amp, "natural", peak, 0.1, [(0.1, peak)])
    audits = [mk(0, "soft", 2.0), mk(1, "soft", 2.2), mk(2, "soft", 6.0),
              mk(3, "hard", 5.0), mk(4, "hard", 5.5), mk(5, "hard", 1.5)]
    audit._flag_prompt_adherence(audits)
    assert audits[2].flags == ["CUED_SOFT_DID_HARD"] and audits[2].verdict == "suspect"
    assert audits[5].flags == ["CUED_HARD_DID_SOFT"]
    assert not any(a.flags for a in audits if a.index in (0, 1, 3, 4))


def test_summary_reports_doubles_and_whether_tempo_did_anything():
    mk = lambda i, tempo, gap: audit.GestureAudit(i, 2.0, "double_flick", "up", "hard", tempo, 5.0, 0.1, [(0.1, 5.0), (0.1 + gap, 4.0)])
    s = audit.summary([mk(0, "brisk", 0.35), mk(1, "brisk", 0.37), mk(2, "deliberate", 0.36), mk(3, "deliberate", 0.38)])
    assert s["n"] == 4 and s["by_verdict"] == {"valid": 4, "suspect": 0, "invalid": 0}
    assert s["double_gap_s"]["p50"] == pytest.approx(0.365, abs=0.01)
    assert abs(s["double_gap_by_tempo"]["brisk"] - s["double_gap_by_tempo"]["deliberate"]) < 0.08


def test_audit_file_round_trips_and_lists_invalid_cues(tmp_path):
    cap = tmp_path / "prompted_x.jsonl"; cap.write_text("")
    good = audit.GestureAudit(0, 2.0, "flick", "up", "hard", "", 4.0, 0.1, [(0.1, 4.0)])
    bad = audit.GestureAudit(1, 6.0, "double_flick", "up", "hard", "", 4.0, 0.1, [(0.1, 4.0), (0.8, 4.0)])
    bad.flags = audit._flags_for(bad)
    assert bad.verdict == "invalid"
    path = audit.write_audit(cap, [good, bad])
    assert path == audit.audit_path(cap) and path.name == "prompted_x.audit.json"
    doc = json.loads(path.read_text())
    assert doc["summary"]["by_verdict"]["invalid"] == 1 and doc["gestures"][1]["verdict"] == "invalid"
    assert audit.invalid_cues(cap) == [6.0]
    assert audit.excluded_cues(cap) == [6.0]
    assert audit.excluded_cues(tmp_path / "nothing.jsonl") == []


def test_suspect_gestures_are_excluded_too_and_counted_as_shortfall(tmp_path):
    """Uncertain data is dropped and made up next session, not trained on."""
    cap = tmp_path / "prompted_y.jsonl"; cap.write_text("")
    ok = audit.GestureAudit(0, 2.0, "flick", "up", "hard", "", 4.0, 0.1, [(0.1, 4.0)])
    sus = audit.GestureAudit(1, 6.0, "flick", "left", "soft", "", 4.0, 0.1, [(0.1, 4.0)]); sus.flags = ["CUED_SOFT_DID_HARD"]
    bad = audit.GestureAudit(2, 9.0, "double_flick", "left", "hard", "", 0.5, None, []); bad.flags = ["NO_MOTION"]
    assert (ok.verdict, sus.verdict, bad.verdict) == ("valid", "suspect", "invalid")
    audit.write_audit(cap, [ok, sus, bad])
    assert audit.excluded_cues(cap) == [6.0, 9.0]
    assert audit.invalid_cues(cap) == [9.0]
    assert audit.shortfall([ok, sus, bad]) == {"flick_left": 1, "double_flick_left": 1}


def test_corpus_shortfall_sums_every_audit_file(tmp_path):
    a = audit.GestureAudit(0, 2.0, "flick", "left", "soft", "", 4.0, 0.1, [(0.1, 4.0)]); a.flags = ["CUED_SOFT_DID_HARD"]
    b = audit.GestureAudit(1, 5.0, "double_flick", "down", "hard", "", 0.5, None, []); b.flags = ["NO_MOTION"]
    c = audit.GestureAudit(2, 8.0, "snap", "any", "hard", "", 3.0, 0.1, [(0.1, 3.0)]); c.flags = ["LATE_ONSET"]
    ok = audit.GestureAudit(3, 11.0, "flick", "left", "hard", "", 4.0, 0.1, [(0.1, 4.0)])
    (tmp_path / "s1.jsonl").write_text(""); (tmp_path / "s2.jsonl").write_text("")
    audit.write_audit(tmp_path / "s1.jsonl", [a, b, ok]); audit.write_audit(tmp_path / "s2.jsonl", [a, c])
    # valid counts: flick_left 1, double_flick_down 0, snap 0 -> median 0 -> nothing below it
    assert audit.valid_counts(tmp_path) == {"flick_left": 1, "double_flick_down": 0, "snap": 0}
    assert audit.corpus_shortfall(tmp_path) == {}
    assert audit.corpus_shortfall(tmp_path, target=3) == {"flick_left": 2, "double_flick_down": 3, "snap": 3}
    assert audit.corpus_shortfall(tmp_path, target=1) == {"double_flick_down": 1, "snap": 1}
    # a class that reached the target is not asked for again, however many exclusions it collected
    more = [audit.GestureAudit(i, 20.0 + i, "flick", "left", "hard", "", 4.0, 0.1, [(0.1, 4.0)]) for i in range(4)]
    (tmp_path / "s3.jsonl").write_text(""); audit.write_audit(tmp_path / "s3.jsonl", more)
    assert "flick_left" not in audit.corpus_shortfall(tmp_path, target=5)



def test_manual_exclude_and_reanchor_round_trip(tmp_path):
    """
    The wearer can exclude a mark ("did it early, redid it late"); a gesture
    whose only fault is a late start can be re-anchored to its onset and
    then audits as on-time, with the original cue kept on the mark.
    """
    import json
    from tests.test_dataset import write_capture, write_notes

    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    # two cued flicks: one on time at 5.0, one that actually happens 0.8 s late at 10.0
    write_capture(cap, seconds=16.0, gestures=[(5.0, "flag"), (10.8, "flag")])
    write_notes(notes, "s", [(5.0, "flag"), (10.0, "flag")])
    A = audit.audit_session(cap, notes)
    # (the fixture's stroke is across gravity while the mark says "up", so the
    # on-time one is suspect on the pair check; what matters here is lateness)
    assert "LATE_ONSET" not in A[0].flags and A[0].verdict != "invalid"
    assert "LATE_ONSET" in A[1].flags and A[1].verdict == "invalid"
    assert audit.reanchorable(A[1]) and not audit.reanchorable(A[0])
    moved = audit.reanchor(notes, A)
    assert moved == [1]
    doc = json.loads(notes.read_text())
    assert doc["marks"][1]["cue_at_original"] == 10.0 and 10.4 < doc["marks"][1]["cue_at"] < 10.8
    A2 = audit.audit_session(cap, notes)
    assert "LATE_ONSET" not in A2[1].flags and A2[1].verdict != "invalid" and 0.0 <= A2[1].onset_s <= 0.4
    # and the wearer's exclusion is final, whatever the stream says
    assert audit.exclude_marks(notes, [0], "redid it") == [0]
    A3 = audit.audit_session(cap, notes)
    assert "MANUAL_EXCLUDE" in A3[0].flags and A3[0].verdict == "invalid"


def test_hand_rule_reads_the_lateral_sign_and_a_frame_flip_reverses_it():
    """
    In the room frame the first stroke of a left flick is lateral-negative
    (sensor-below wearing). Turning the ring round about the palm normal must
    reverse that sign and nothing else about the window.
    """
    from whip import model as gm

    rng = np.random.default_rng(3)
    W = gm.WINDOW_SAMPLES
    grav = np.zeros(3); grav[0] = 1.0                     # palm down: gravity on the palm normal
    f = np.zeros(3); f[gm.FINGER_AXIS] = 1.0
    lateral = np.cross(grav, f)
    win = np.zeros((3, W)); win[:, 20:26] = -2.0 * lateral[:, None] * np.hanning(6)[None, :]   # a stroke to the lateral-negative side
    win += 0.01 * rng.standard_normal(win.shape)
    assert audit.lateral_sign(win, grav) == -1
    flip = np.diag([1.0, -1.0, -1.0])                     # half-turn about the palm normal (axis 0)
    assert audit.lateral_sign(flip @ win, flip @ grav) == +1
    # fingers pointing straight down: no lateral direction, no verdict
    assert audit.lateral_sign(win, f) is None
