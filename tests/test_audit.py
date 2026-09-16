"""
The session audit flags what a label file cannot show: no motion at a cue,
a late gesture, a stroke count that does not match the cued class, and a
wearer who ignored the amplitude prompt.
"""

import numpy as np
import pytest

from whip import audit
from whip.registry import load_registry


def _stroke(mag_g: float, width: int = 6):
    """A one-lobe |a| bump on axis 1, `width` samples wide."""
    w = np.hanning(width + 2)[1:-1]; w = w / w.max()
    return np.stack([np.zeros(width), mag_g * w, np.zeros(width)])


def _stream(events, seconds=4.0, rest=(0.0, 0.0, 1.0)):
    """A still wearer (gravity `rest`) with strokes added at (t_s, peak_g) pairs. Returns (x_g, times)."""
    n = int(seconds * 25)
    x = np.tile(np.asarray(rest, float)[:, None], (1, n))
    for t_s, g in events:
        k = int(t_s * 25)
        s = _stroke(g)
        x[:, k:k + s.shape[1]] += s
    return x, np.arange(n) / 25.0


R = load_registry()


def test_a_single_at_the_cue_is_clean():
    x, t = _stream([(2.1, 4.0)])
    peak, onset, strokes = audit.audit_gesture(x, t, cue_at=2.0, label="flick", registry=R)
    assert peak == pytest.approx(4.0, abs=0.05)
    assert 0.0 <= onset < 0.2
    assert len(strokes) == 1


def test_two_strokes_are_counted_and_their_gap_and_ratio_measured():
    x, t = _stream([(2.1, 4.0), (2.7, 2.0)])
    _, _, strokes = audit.audit_gesture(x, t, cue_at=2.0, label="double_flick", registry=R)
    assert len(strokes) == 2
    (t0, g0), (t1, g1) = strokes
    assert t1 - t0 == pytest.approx(0.6, abs=0.05)
    assert g1 / g0 == pytest.approx(0.5, abs=0.05)


def test_a_noisy_crest_is_one_stroke_not_two():
    # two maxima 80 ms apart: closer than MIN_STROKE_SPACING_S, so one stroke
    x, t = _stream([(2.1, 4.0), (2.18, 3.5)])
    _, _, strokes = audit.audit_gesture(x, t, cue_at=2.0, label="flick", registry=R)
    assert len(strokes) == 1


def test_a_faint_second_bump_is_not_a_stroke():
    x, t = _stream([(2.1, 5.0), (2.6, 1.2)])   # 24% of the main stroke
    _, _, strokes = audit.audit_gesture(x, t, cue_at=2.0, label="flick", registry=R)
    assert len(strokes) == 1


def test_no_motion_and_late_onset_are_measured():
    x, t = _stream([])
    peak, onset, strokes = audit.audit_gesture(x, t, cue_at=2.0, label="flick", registry=R)
    assert peak < audit.STROKE_FLOOR_G and onset is None and strokes == []
    x, t = _stream([(3.3, 4.0)])
    _, onset, _ = audit.audit_gesture(x, t, cue_at=2.0, label="flick", registry=R)
    assert onset > audit.LATE_ONSET_S


def test_only_a_one_stroke_double_is_a_hard_flag(tmp_path):
    """A single with a recoil is not flagged: at 25 Hz a recoil and a weak second tap look alike."""
    assert "DOUBLE_WITH_ONE_STROKE" in __import__("probe.audit", fromlist=["HARD_FLAGS"]).HARD_FLAGS
    assert not any(f.startswith("STROKES_") for f in __import__("probe.audit", fromlist=["HARD_FLAGS"]).HARD_FLAGS)


def test_prompt_adherence_flags_a_soft_cue_done_hard():
    mk = lambda i, amp, peak: audit.GestureAudit(i, "flick", "up", amp, "natural", peak, 0.1, [(0.1, peak)])
    audits = [mk(0, "soft", 2.0), mk(1, "soft", 2.2), mk(2, "soft", 6.0),
              mk(3, "hard", 5.0), mk(4, "hard", 5.5), mk(5, "hard", 1.5)]
    audit._flag_prompt_adherence(audits)
    assert audits[2].flags == ["CUED_SOFT_DID_HARD"]
    assert audits[5].flags == ["CUED_HARD_DID_SOFT"]
    assert not any(a.flags for a in audits if a.index in (0, 1, 3, 4))


def test_summary_reports_doubles_and_whether_tempo_did_anything():
    mk = lambda i, tempo, gap: audit.GestureAudit(i, "double_flick", "up", "hard", tempo, 5.0, 0.1, [(0.1, 5.0), (0.1 + gap, 4.0)])
    s = audit.summary([mk(0, "brisk", 0.35), mk(1, "brisk", 0.37), mk(2, "deliberate", 0.36), mk(3, "deliberate", 0.38)])
    assert s["n"] == 4 and s["flagged"] == 0
    assert s["double_gap_s"]["p50"] == pytest.approx(0.365, abs=0.01)
    assert abs(s["double_gap_by_tempo"]["brisk"] - s["double_gap_by_tempo"]["deliberate"]) < 0.08
