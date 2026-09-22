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
    """
    Two different classes back to back: the second is a new event only once
    the dead time after the first has passed (a run starting one stride after
    a fired run is that event's tail, see DEAD_TIME_S). Here the second run
    starts 0.72 s after the first ends: two events.
    """
    preds = run_of("flag", 5) + run_of("none", 3) + run_of("approve", 5)
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


def wave_policy(refractory_s=2.0):
    return {"wave": events.RunPolicy(min_run=3, max_run=None, refractory_s=refractory_s)}


def test_a_sustained_gesture_fires_mid_run_not_at_the_end():
    """
    A wave IS sustained motion -- the very thing max_run rejects -- so the band
    would make it unfirable, and waiting for the run to end would mean a
    20-second latency. It fires once its run passes min_run.
    """
    preds = ["none"] * 3 + run_of("wave", 80) + ["none"] * 3   # ~19 s of waving
    ev = events.detect(preds, starts_for(len(preds)), policies=wave_policy())
    assert len(ev) == 1, "one long wave is one event"
    assert ev[0].run_length == 3, "fired at min_run, not at run end"


def test_a_brief_dip_does_not_split_one_wave_into_two():
    """Refractory is measured from run end, so a mid-wave dip cannot re-fire."""
    preds = run_of("wave", 10) + ["none"] * 2 + run_of("wave", 10)
    ev = events.detect(preds, starts_for(len(preds)), policies=wave_policy(refractory_s=2.0))
    assert len(ev) == 1


def test_a_new_wave_after_the_refractory_fires_again():
    gap = int(3.0 / events.STRIDE_S)   # well past a 2 s refractory
    preds = run_of("wave", 10) + ["none"] * gap + run_of("wave", 10)
    ev = events.detect(preds, starts_for(len(preds)), policies=wave_policy(refractory_s=2.0))
    assert len(ev) == 2


def test_without_a_policy_a_sustained_run_is_still_rejected_by_the_band():
    """The default band is unchanged: an unregistered label over max_run drops."""
    preds = ["none"] * 3 + run_of("mystery", 20) + ["none"] * 3
    assert events.detect(preds, starts_for(len(preds))) == []


def test_a_sustained_policy_requires_a_plausible_min_run():
    import pytest

    with pytest.raises(ValueError):
        events.RunPolicy(min_run=1, max_run=None)


def test_impulsive_and_sustained_policies_coexist():
    preds = run_of("flag", 5) + ["none"] * 2 + run_of("wave", 8)
    ev = events.detect(preds, starts_for(len(preds)), policies=wave_policy())
    assert [e.label for e in ev] == ["flag", "wave"]


def test_a_hole_in_the_stream_breaks_a_run():
    """
    Two same-class gestures on either side of a hole (an excluded gesture's
    windows offline, a dropout live) must be two events, not one long run
    centred on the hole -- that fusion read both gestures as misses.
    """
    stride = events.STRIDE_S
    a = [(i * stride, "flick") for i in range(6)]                 # run of 6 at 0..1.2 s
    b = [(20.0 + i * stride, "flick") for i in range(6)]          # run of 6 at 20..21.2 s
    preds = [l for _, l in a + b]; starts = [t for t, _ in a + b]
    got = events.detect(preds, starts)
    assert [(e.run_length, round(e.start_s, 2)) for e in got] == [(6, 0.0), (6, 20.0)]
    # and a normal one-stride step does not break anything
    c = [(i * stride, "flick") for i in range(12)]
    assert [e.run_length for e in events.detect([l for _, l in c], [t for t, _ in c])] == [12]


def test_a_tail_run_right_after_an_event_is_absorbed_and_a_later_gesture_is_not():
    """A double flick's second stroke, alone in the window after the event fires, is not a new single flick."""
    st = events.STRIDE_S
    seq = [(i * st, "double_flick") for i in range(6)] + [((6 + i) * st, "flick") for i in range(4)]   # tail starts one stride after
    seq += [(5.0 + i * st, "flick") for i in range(5)]                                                   # a real flick 3 s later
    got = events.detect([l for _, l in seq], [t for t, _ in seq])
    assert [(e.label, round(e.start_s, 2)) for e in got] == [("double_flick", 0.0), ("flick", 5.0)]
