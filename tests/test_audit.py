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


def test_no_motion_late_onset_and_sample_loss_are_invalid():
    x, t = _stream([])
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0))
    assert g.flags == ["NO_MOTION"] and g.verdict == "invalid"
    x, t = _stream([(3.3, 4.0)])
    g = _ga("flick", "none", audit.audit_gesture(x, t, 2.0))
    assert "LATE_ONSET" in g.flags and g.verdict == "invalid"
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
    assert audit.invalid_cues(tmp_path / "nothing.jsonl") == []
