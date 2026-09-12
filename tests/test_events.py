import pytest

from whip import events


def run_of(label, n):
    return [label] * n


def starts_for(n, stride=events.STRIDE_S):
    return [i * stride for i in range(n)]


def test_event_centre_accounts_for_window_length():
    """
    Window timestamps are start times, so a window at T covers T..T+2.0 s.
    Averaging starts alone puts the event a full second early -- more than the
    matching tolerance -- so every detection missed and event F1 read 0.0%
    while the model was working fine.
    """
    ev = events.Event(label="flag", start_s=10.0, end_s=11.2, run_length=6)
    assert ev.centre_s == pytest.approx(10.6 + events.WINDOW_S / 2)


def test_isolated_flickers_are_rejected():
    preds = ["none"] * 5 + ["flag"] + ["none"] * 5
    assert events.detect(preds, starts_for(len(preds)), min_run=3) == []


def test_a_plausible_run_becomes_one_event():
    preds = ["none"] * 3 + run_of("flag", 6) + ["none"] * 3
    ev = events.detect(preds, starts_for(len(preds)))
    assert len(ev) == 1
    assert ev[0].label == "flag"
    assert ev[0].run_length == 6


def test_sustained_motion_is_rejected_by_the_upper_bound():
    """
    The reason debouncing is a band and not a floor. A gesture fires ~6
    consecutive windows; a three-second wave fires 15+. A `>= k` rule would make
    waving *more* likely to trigger, which is backwards.
    """
    preds = ["none"] * 3 + run_of("approve", 20) + ["none"] * 3
    assert events.detect(preds, starts_for(len(preds)), min_run=3, max_run=14) == []
    # with a floor instead of a band, the same input fires
    assert len(events.detect(preds, starts_for(len(preds)), min_run=3, max_run=999)) == 1


def test_adjacent_runs_of_different_classes_are_separate_events():
    preds = run_of("flag", 5) + run_of("approve", 5)
    ev = events.detect(preds, starts_for(len(preds)))
    assert [e.label for e in ev] == ["flag", "approve"]


def test_scoring_matches_a_detection_to_its_gesture():
    preds = ["none"] * 4 + run_of("flag", 6) + ["none"] * 4
    starts = starts_for(len(preds))
    ev = events.detect(preds, starts)
    truth = [(ev[0].centre_s, "flag")]

    r = events.score(ev, truth, hours=1.0)
    assert r["per_class"]["flag"]["tp"] == 1
    assert r["false_positives"] == 0
    assert r["per_class"]["flag"]["f1"] == pytest.approx(1.0)


def test_wrong_class_at_the_right_time_is_not_a_match():
    preds = ["none"] * 4 + run_of("flag", 6) + ["none"] * 4
    starts = starts_for(len(preds))
    ev = events.detect(preds, starts)
    r = events.score(ev, [(ev[0].centre_s, "approve")], hours=1.0)
    assert r["false_positives"] == 1
    assert r["per_class"]["approve"]["fn"] == 1


def test_one_detection_cannot_satisfy_two_gestures():
    preds = ["none"] * 4 + run_of("flag", 6) + ["none"] * 4
    starts = starts_for(len(preds))
    ev = events.detect(preds, starts)
    c = ev[0].centre_s
    r = events.score(ev, [(c, "flag"), (c + 0.1, "flag")], hours=1.0)
    assert r["per_class"]["flag"]["tp"] == 1
    assert r["per_class"]["flag"]["fn"] == 1


def test_false_positives_per_hour():
    """The number that decides usability, so it must be computed plainly."""
    preds = (run_of("flag", 6) + ["none"] * 6) * 3
    ev = events.detect(preds, starts_for(len(preds)))
    r = events.score(ev, truth=[], hours=0.5)
    assert r["false_positives"] == 3
    assert r["fp_per_hour"] == pytest.approx(6.0)


def test_no_detections_and_no_gestures_is_not_an_error():
    r = events.score([], [], hours=1.0)
    assert r["false_positives"] == 0
    assert r["fp_per_hour"] == 0.0
