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
    w = dataset.windows_from_session(cap)
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
    w = dataset.windows_from_session(cap)[0]
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
    positives = [x for x in w if x.label == "flag"]
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
    without = dataset.windows_from_session(cap)
    assert len(with_marks) < len(without), "some windows should have been dropped as ambiguous"


def test_labels_are_ordered_with_none_first():
    assert dataset.LABELS[0] == "none"
    assert dataset.LABEL_INDEX["none"] == 0


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
