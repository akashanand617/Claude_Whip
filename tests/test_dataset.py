import json

import pytest

from probe.simulate import make_accel_payload
from whip import dataset


def write_capture(path, seconds=20.0, gestures=(), rate=25.0):
    """A synthetic session: quiet, with bursts at the given (time, label) marks."""
    n = int(seconds * rate)
    lines = [json.dumps({"kind": "header", "device": {"name": "sim"}})]
    for i in range(n):
        t = i / rate
        active = any(g_t <= t < g_t + dataset.GESTURE_DURATION_S for g_t, _ in gestures)
        amp = 900 if active else 20
        lines.append(json.dumps({
            "t": round(t, 6),
            "p": make_accel_payload(x=amp, y=1024, z=amp // 2).hex(),
        }))
    path.write_text("\n".join(lines) + "\n")


def write_notes(path, session_id, gestures):
    path.write_text(json.dumps({
        "session_id": session_id, "started_wall": 0.0, "kind": "prompted",
        "hand": "left", "ring_position": "middle", "note": "",
        "marks": [{"label": lab, "direction": "extension", "amplitude": "normal",
                   "windup": "none", "posture": "raised", "tempo": "natural",
                   "index": i, "cue_at": t} for i, (t, lab) in enumerate(gestures)],
    }))


def test_windowing_geometry():
    assert dataset.WINDOW_SAMPLES == 50
    assert dataset.STRIDE_SAMPLES == 6
    # 88% overlap is why the split must be by session
    overlap = 1 - dataset.STRIDE_SAMPLES / dataset.WINDOW_SAMPLES
    assert overlap > 0.85


def test_windows_are_extracted_at_the_right_stride(tmp_path):
    cap = tmp_path / "s.jsonl"
    write_capture(cap, seconds=10.0)
    w = dataset.windows_from_session(cap, declared_negative=True)
    expected = (250 - dataset.WINDOW_SAMPLES) // dataset.STRIDE_SAMPLES + 1
    assert len(w) == expected
    assert all(len(x.axes) == 3 for x in w)
    assert all(len(x.axes[0]) == dataset.WINDOW_SAMPLES for x in w)


def test_gravity_is_removed_but_amplitude_is_not(tmp_path):
    """
    Subtracting the per-axis mean kills DC orientation so it cannot be a
    shortcut. Dividing by the standard deviation would also kill amplitude,
    which genuinely separates deliberate gestures from incidental motion.
    """
    cap = tmp_path / "s.jsonl"
    write_capture(cap, seconds=6.0)
    w = dataset.windows_from_session(cap, declared_negative=True)[0]
    for axis in w.axes:
        assert abs(sum(axis) / len(axis)) < 1e-6      # mean removed
    spread = max(w.axes[0]) - min(w.axes[0])
    assert spread < 1.0                                # quiet stays quiet


def test_a_gesture_produces_several_positive_windows(tmp_path):
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    gestures = [(5.0, "flag")]
    write_capture(cap, seconds=20.0, gestures=gestures)
    write_notes(notes, "s", gestures)

    w = dataset.windows_from_session(cap, notes)
    positives = [x for x in w if x.label == "flick"]   # canonical name, not the legacy alias
    assert 3 <= len(positives) <= 8, f"expected ~5 positive windows, got {len(positives)}"


def test_ambiguous_windows_are_dropped_not_guessed(tmp_path):
    """
    Windows holding between 30% and 70% of a gesture get no label. Forcing one
    teaches noise; the debouncer covers the gap because a real gesture still
    sits cleanly inside several windows.
    """
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    gestures = [(5.0, "approve")]
    write_capture(cap, seconds=20.0, gestures=gestures)
    write_notes(notes, "s", gestures)

    with_marks = dataset.windows_from_session(cap, notes)
    without = dataset.windows_from_session(cap, declared_negative=True)
    assert len(with_marks) < len(without), "some windows should have been dropped as ambiguous"


def test_labels_are_ordered_with_none_first():
    from whip.registry import Registry

    labels = Registry().labels_for({"flick", "wave"})
    assert labels[0] == "none"
    assert labels == ["none", "flick", "wave"], "registry order, not discovery order"


def test_split_is_by_session(tmp_path):
    a = dataset.Window(session_id="day1", start_s=0, label="flag", axes=[[0] * 50] * 3)
    b = dataset.Window(session_id="day2", start_s=0, label="none", axes=[[0] * 50] * 3)
    parts = dataset.split_by_session([a, b], test_sessions={"day2"})
    assert parts["train"] == [a]
    assert parts["test"] == [b]


def test_split_never_puts_one_session_in_two_partitions():
    ws = [dataset.Window(session_id=f"s{i % 3}", start_s=i, label="none", axes=[[0] * 50] * 3)
          for i in range(30)]
    parts = dataset.split_by_session(ws, test_sessions={"s0"}, val_sessions={"s1"})
    for name, expected in (("test", "s0"), ("val", "s1"), ("train", "s2")):
        assert {w.session_id for w in parts[name]} == {expected}


def test_summary_reports_imbalance():
    ws = ([dataset.Window(session_id="s", start_s=0, label="none", axes=[[0] * 50] * 3)] * 90
          + [dataset.Window(session_id="s", start_s=0, label="flag", axes=[[0] * 50] * 3)] * 10)
    s = dataset.summarise(ws)
    assert s["total"] == 100
    assert s["counts"]["none"] == 90
    assert s["balance"]["flag"] == pytest.approx(0.1)


def test_unlabelled_capture_is_refused(tmp_path):
    """
    "No notes means negative" put 33 real gestures into the `none` class. A
    capture is negative only if it says so.
    """
    cap = tmp_path / "mystery.jsonl"
    write_capture(cap, seconds=6.0)
    with pytest.raises(dataset.UnlabelledCapture):
        dataset.windows_from_session(cap)
    assert dataset.windows_from_session(cap, declared_negative=True)


def test_wrong_sample_rate_is_refused(tmp_path):
    """
    50 samples is 2.0 s at 25 Hz and 1.0 s at 50 Hz -- same tensor shape, half
    the time span, and nothing downstream would notice.
    """
    cap = tmp_path / "fast.jsonl"
    write_capture(cap, seconds=6.0, rate=50.0)
    with pytest.raises(dataset.WrongSampleRate):
        dataset.windows_from_session(cap, declared_negative=True)


def test_load_all_reports_why_it_skipped(tmp_path):
    write_capture(tmp_path / "unknown.jsonl", seconds=6.0)
    write_capture(tmp_path / "fast.jsonl", seconds=6.0, rate=50.0)
    windows, skipped = dataset.load_all(tmp_path)
    assert windows == []
    assert len(skipped) == 2
    assert any("not declared negative" in s for s in skipped)
    assert any("Hz" in s for s in skipped)


def write_span_notes(path, session_id, spans, kind="negative"):
    """Cued motion blocks, as SessionNotes.add_cue writes them."""
    import json

    path.write_text(json.dumps({
        "session_id": session_id, "started_wall": 0.0, "kind": kind,
        "hand": "left", "ring_position": "middle", "note": "",
        "marks": [{"label": "none", "motion": m, "cue_at": lo, "until": hi}
                  for lo, hi, m in spans],
    }))


def test_a_cued_span_labels_its_windows_with_the_gesture(tmp_path):
    """A 'waving' span from the negative session becomes wave training data."""
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    write_capture(cap, seconds=30.0, gestures=[(8.0, "x"), (9.5, "x"), (11.0, "x"),
                                               (12.5, "x"), (14.0, "x")])
    write_span_notes(notes, "s", [(8.0, 16.0, "waving")])
    w = dataset.windows_from_session(cap, notes)
    labels = {x.label for x in w}
    assert "wave" in labels, "the alias 'waving' must resolve to the wave class"
    assert "waving" not in labels, "classes are canonical names"


def test_unrecognised_motions_stay_attribution_only(tmp_path):
    """
    'dismissive flick' and 'so-so wobble' were recorded as deliberate
    near-gesture NEGATIVES. Promoting every cued motion to a class would
    quietly convert hard negatives into positives.
    """
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    write_capture(cap, seconds=20.0, gestures=[(6.0, "x"), (8.0, "x")])
    write_span_notes(notes, "s", [(5.0, 12.0, "dismissive flick")])
    w = dataset.windows_from_session(cap, notes)
    assert {x.label for x in w} == {"none"}


def test_quiet_windows_inside_a_span_stay_none(tmp_path):
    """
    The hygiene floor. A 20 s 'keep waving' block contains pauses, and labelling
    silence as wave teaches exactly the wrong thing. This is not the removed
    amplitude->class rule: the label source is the human cue, amplitude only
    gates whether the cued motion was happening at that moment.
    """
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    # motion only in the middle of the span; the rest of the span is still
    write_capture(cap, seconds=30.0, gestures=[(12.0, "x"), (13.5, "x")])
    write_span_notes(notes, "s", [(5.0, 25.0, "waving")])
    w = dataset.windows_from_session(cap, notes)
    labels = [x.label for x in w]
    assert "wave" in labels
    assert "none" in labels, "the quiet stretches of the span must stay none"


def test_windows_straddling_a_span_edge_are_dropped(tmp_path):
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    write_capture(cap, seconds=20.0, gestures=[(7.5, "x"), (9.0, "x")])
    write_span_notes(notes, "s", [(8.0, 14.0, "waving")])
    with_span = dataset.windows_from_session(cap, notes)
    without = dataset.windows_from_session(cap, declared_negative=True)
    assert len(with_span) < len(without), "edge windows are ambiguous, not guessed at"


def test_gesture_names_excludes_only_none():
    assert dataset.gesture_names(["none", "flick", "wave"]) == ["flick", "wave"]
    assert dataset.gesture_names(["none"]) == []


def test_legacy_labels_resolve_to_canonical_names(tmp_path):
    """Old sessions on disk say flag/approve; classes are flick/double_flick."""
    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    gestures = [(5.0, "flag"), (10.0, "approve")]
    write_capture(cap, seconds=20.0, gestures=gestures)
    write_notes(notes, "s", gestures)
    labels = {x.label for x in dataset.windows_from_session(cap, notes)}
    assert "flick" in labels and "double_flick" in labels
    assert "flag" not in labels and "approve" not in labels


def test_prompted_windows_carry_their_direction(tmp_path):
    import json

    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    write_capture(cap, seconds=15.0, gestures=[(5.0, "flag")])
    notes.write_text(json.dumps({
        "session_id": "s", "started_wall": 0.0, "kind": "prompted",
        "hand": "left", "ring_position": "middle", "note": "",
        "marks": [{"label": "flag", "direction": "up", "amplitude": "hard",
                   "windup": "none", "posture": "raised", "tempo": "natural",
                   "index": 0, "cue_at": 5.0}],
    }))
    positives = [x for x in dataset.windows_from_session(cap, notes) if x.label == "flick"]
    assert positives
    assert all(x.direction == "up" for x in positives)


def test_a_direction_outside_the_canonical_set_becomes_none(tmp_path):
    """'any' from generic gesture schedules, free text from early sessions."""
    import json

    cap, notes = tmp_path / "s.jsonl", tmp_path / "s.notes.json"
    write_capture(cap, seconds=15.0, gestures=[(5.0, "flag")])
    notes.write_text(json.dumps({
        "session_id": "s", "started_wall": 0.0, "kind": "prompted",
        "hand": "left", "ring_position": "middle", "note": "",
        "marks": [{"label": "snap", "direction": "any", "amplitude": "hard",
                   "windup": "none", "posture": "raised", "tempo": "natural",
                   "index": 0, "cue_at": 5.0}],
    }))
    positives = [x for x in dataset.windows_from_session(cap, notes) if x.label == "snap"]
    assert positives
    assert all(x.direction == "none" for x in positives)


def test_format_version_rejects_stale_exports():
    import numpy as np

    for old in (1, 2, 3):
        with pytest.raises(dataset.StaleDataset):
            dataset.check_format_version({"format_version": np.array(old)})
