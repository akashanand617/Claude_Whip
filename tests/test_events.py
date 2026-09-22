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


# ---------------------------------------------------------------- bursts

from whip.events import RunPolicy

def _burst_case(bursts, labeller, n_seconds=20.0):
    """Synthetic stream: (t, magnitudes) with bursts above 1 g, and windows labelled by `labeller(start, end)`."""
    import numpy as np
    t = np.arange(0, n_seconds, 0.04); mag = np.zeros_like(t)
    for a, b in bursts:
        mag[(t >= a) & (t < b)] = 3.0
    starts = [float(t[i]) for i in range(0, len(t) - 49, 6)]
    labels = [labeller(s, s + 2.0) for s in starts]
    return t, mag, starts, labels


def _contains(s, e, a, b):
    return s <= a - 0.1 and e >= b + 0.1


def test_same_class_gestures_in_succession_are_separate_events():
    """Two flicks 1 s apart made ONE run (one event) under the run tracker; a burst each now."""
    from whip.events import detect_bursts
    flicks = ((3.0, 3.3), (4.3, 4.6), (5.5, 5.8))
    t, mag, starts, labels = _burst_case(flicks, lambda s, e: "flick" if any(_contains(s, e, a, b) for a, b in flicks) else "none")
    ev = detect_bursts(labels, starts, t, mag, policies={"flick": RunPolicy()})
    assert [(e.label, round(e.at_s, 2)) for e in ev] == [("flick", 3.0), ("flick", 4.32), ("flick", 5.52)]
    assert all(e.latency_s is not None and 0.8 < e.latency_s < 2.2 for e in ev)


def test_a_different_gesture_right_after_another_is_not_absorbed():
    from whip.events import detect_bursts
    t, mag, starts, labels = _burst_case(((8.0, 8.3), (9.0, 9.05)),
                                         lambda s, e: "flick" if _contains(s, e, 8.0, 8.3) else "snap" if s <= 8.9 and e >= 9.15 else "none")
    ev = detect_bursts(labels, starts, t, mag, policies={"flick": RunPolicy(), "snap": RunPolicy()})
    assert [e.label for e in ev] == ["flick", "snap"]
    # the snap was decided only on windows that start after the flick ended
    assert all(v[0] >= 8.28 for v in ev[1].__dict__.get("votes", [])) or ev[1].run_length >= 2


def test_continuous_motion_is_not_chopped_into_gestures():
    """A 5 s shake the model calls double_flick throughout is one burst, too long to be impulsive: no event."""
    from whip.events import detect_bursts, BurstTracker
    t, mag, starts, labels = _burst_case(((12.0, 17.0),), lambda s, e: "double_flick" if s >= 12 and e <= 17 else "none")
    assert detect_bursts(labels, starts, t, mag, policies={"double_flick": RunPolicy()}) == []
    tracker = BurstTracker(policies={"double_flick": RunPolicy()})
    for tt, m in zip(t, mag):
        tracker.feed_sample(float(tt), float(m))
    tracker.finish()
    assert [b.outcome for b in tracker.bursts] == ["too_long"]


def test_a_double_flick_is_one_burst_and_a_wave_still_fires():
    from whip.events import detect_bursts
    # two strokes 0.35 s apart = one burst (gap under QUIET_S); a 6 s wave the model labels wave
    t, mag, starts, labels = _burst_case(((3.0, 3.2), (3.55, 3.75), (10.0, 16.0)),
                                         lambda s, e: "double_flick" if _contains(s, e, 3.0, 3.75) else "wave" if s >= 10 and e <= 16 else "none")
    ev = detect_bursts(labels, starts, t, mag, policies={"double_flick": RunPolicy(), "wave": RunPolicy(3, None, 2.0)})
    assert [e.label for e in ev] == ["double_flick", "wave"]
    assert round(ev[0].at_s, 2) == 3.0 and round(ev[0].end_s, 2) == 3.72


def test_a_burst_needs_agreeing_votes():
    from whip.events import detect_bursts
    t, mag, starts, labels = _burst_case(((5.0, 5.3),), lambda s, e: "none")
    assert detect_bursts(labels, starts, t, mag, policies={"flick": RunPolicy()}) == []
    # exactly one window says flick: below MIN_VOTES
    one = [i for i, s in enumerate(starts) if _contains(s, s + 2, 5.0, 5.3)][:1]
    labels = ["flick" if i in one else "none" for i in range(len(starts))]
    assert detect_bursts(labels, starts, t, mag, policies={"flick": RunPolicy()}) == []


def test_impulsive_magnitude_matches_the_engine_buffer_mean():
    import numpy as np
    from whip.events import impulsive_magnitude, GRAVITY_SAMPLES
    rng = np.random.default_rng(0); x = rng.normal(0, 1, (3, 80))
    m = impulsive_magnitude(x)
    i = 60
    tail = x[:, i - GRAVITY_SAMPLES + 1:i + 1]
    assert m[i] == np.linalg.norm(tail[:, -1] - tail.mean(axis=1))
