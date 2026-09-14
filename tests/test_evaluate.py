import numpy as np
import pytest

from whip import dataset, evaluate, events

CLASSES = ["none", "flag", "approve"]


def probs(calls, confidence=0.9):
    """Per-window probability rows from a list of intended class names."""
    out = []
    for name in calls:
        row = np.full(3, (1 - confidence) / 2)
        row[CLASSES.index(name)] = confidence
        out.append(row)
    return np.array(out)


def starts(n, stride=events.STRIDE_S):
    return [i * stride for i in range(n)]


def test_a_rate_below_one_event_is_not_measurable():
    """
    Ten minutes cannot demonstrate 1 false positive per hour: that is 0.167
    events, which the session can only show by showing none -- and none over ten
    minutes is equally consistent with five per hour.
    """
    assert evaluate.min_measurable_rate_per_minute(10.0) == pytest.approx(0.1)
    assert evaluate.min_measurable_rate_per_minute(60.0) == pytest.approx(1 / 60)


def test_calibrate_refuses_a_budget_the_recording_cannot_support():
    p = probs(["none"] * 40)
    with pytest.raises(evaluate.NotMeasurable):
        evaluate.calibrate(p, starts(40), minutes=10.0, class_names=CLASSES,
                           budget_per_minute=1 / 60)


def test_calibrate_returns_a_threshold_that_meets_a_supportable_budget():
    # two events at 0.6 confidence, against a budget of one event per ten minutes
    calls = ["none"] * 5 + ["flag"] * 6 + ["none"] * 5 + ["approve"] * 6 + ["none"] * 18
    p = probs(calls, confidence=0.6)
    thr = evaluate.calibrate(p, starts(40), minutes=10.0, class_names=CLASSES,
                             budget_per_minute=0.1)
    assert thr > 0.6, "must climb above the confidence of the windows it has to suppress"


def test_zero_events_in_ten_minutes_is_not_evidence_of_a_low_rate():
    """
    The rule of three. This is the number that stops a clean-looking zero from
    being quoted as if it settled the build spec's <1/hour criterion.
    """
    point = evaluate.CurvePoint(threshold=0.5, hits=0, total=1,
                                false_positives=0, negative_minutes=10.0)
    assert point.fp_per_minute == 0.0
    assert point.fp_upper_bound_per_minute == pytest.approx(0.3)   # 18 per hour
    assert point.fp_upper_bound_per_minute * 60 > 1.0, "10 min cannot show <1/hour"


def test_demonstrating_under_one_per_hour_needs_over_three_hours():
    """
    The rule of three again, pointed at the build spec. Zero events in an hour
    gives an upper bound of 3/hour, so a clean hour of ambient wear cannot show
    <1/hour however clean it is. It takes more than three hours.

    This corrects an earlier recommendation in this project that one hour of
    ambient recording would settle the criterion. It would not have.
    """
    one_hour = evaluate.CurvePoint(0.5, 0, 1, false_positives=0, negative_minutes=60.0)
    assert one_hour.fp_upper_bound_per_minute * 60 == pytest.approx(3.0)

    three_hours = evaluate.CurvePoint(0.5, 0, 1, false_positives=0, negative_minutes=180.0)
    assert three_hours.fp_upper_bound_per_minute * 60 == pytest.approx(1.0)

    four_hours = evaluate.CurvePoint(0.5, 0, 1, false_positives=0, negative_minutes=240.0)
    assert four_hours.fp_upper_bound_per_minute * 60 < 1.0


def test_gesture_hits_are_returned_per_gesture_not_aggregated():
    """The bootstrap needs individual outcomes to resample."""
    ev = [events.Event(label="flag", start_s=10.0, end_s=11.0, run_length=5)]
    truth = [(ev[0].centre_s, "flag"), (100.0, "approve")]
    hits = evaluate.gesture_hits(ev, truth)
    assert hits == [True, False]


def test_one_detection_cannot_satisfy_two_gestures():
    ev = [events.Event(label="flag", start_s=10.0, end_s=11.0, run_length=5)]
    c = ev[0].centre_s
    assert evaluate.gesture_hits(ev, [(c, "flag"), (c + 0.05, "flag")]) == [True, False]


def test_bootstrap_interval_widens_as_the_sample_shrinks():
    """
    The variance the tables never had. At 64 gestures the interval on 70% recall
    is about +/-11 points -- wider than nearly every architecture difference
    claimed in this project.
    """
    many = [True] * 45 + [False] * 19          # ~70% of 64
    few = [True] * 7 + [False] * 3             # ~70% of 10
    lo_m, hi_m = evaluate.bootstrap_recall_ci(many)
    lo_f, hi_f = evaluate.bootstrap_recall_ci(few)
    assert (hi_f - lo_f) > (hi_m - lo_m)
    assert (hi_m - lo_m) > 0.15, "64 gestures is not a tight measurement"


def test_bootstrap_of_nothing_is_nan_not_zero():
    lo, hi = evaluate.bootstrap_recall_ci([])
    assert np.isnan(lo) and np.isnan(hi)


def test_curve_returns_a_point_per_threshold_not_a_single_estimate():
    n = 40
    gp = probs(["none"] * 10 + ["flag"] * 6 + ["none"] * 24, confidence=0.8)
    ng = probs(["none"] * n)
    pts = evaluate.curve(gp, starts(n), [(10 * events.STRIDE_S + 2.0, "flag")],
                         [(ng, starts(n))], 5.0, CLASSES,
                         thresholds=(0.4, 0.6, 0.9, 0.99))
    assert len(pts) == 4
    assert [p.threshold for p in pts] == [0.4, 0.6, 0.9, 0.99]


def test_raising_the_threshold_never_increases_recall():
    n = 60
    gp = probs(["none"] * 10 + ["flag"] * 6 + ["none"] * 44, confidence=0.7)
    ng = probs(["none"] * n)
    pts = evaluate.curve(gp, starts(n), [(10 * events.STRIDE_S + 2.0, "flag")],
                         [(ng, starts(n))], 5.0, CLASSES, thresholds=(0.4, 0.75, 0.95))
    recalls = [p.recall for p in pts]
    assert recalls == sorted(recalls, reverse=True)


def test_recall_at_budget_returns_none_when_nothing_meets_it():
    """A real answer that must not be quietly replaced by the nearest point."""
    pts = [evaluate.CurvePoint(0.5, hits=5, total=10, false_positives=50,
                               negative_minutes=1.0)]
    assert evaluate.recall_at_budget(pts, budget_per_minute=0.1) is None


def test_recall_at_budget_picks_the_most_permissive_qualifying_point():
    pts = [evaluate.CurvePoint(0.4, 8, 10, false_positives=9, negative_minutes=10.0),
           evaluate.CurvePoint(0.6, 6, 10, false_positives=1, negative_minutes=10.0),
           evaluate.CurvePoint(0.9, 2, 10, false_positives=0, negative_minutes=10.0)]
    best = evaluate.recall_at_budget(pts, budget_per_minute=0.1)
    assert best.threshold == 0.6 and best.recall == pytest.approx(0.6)


def test_rates_are_per_minute_of_the_activity():
    """
    Nobody waves for an hour. "73 false positives per hour of waving" was never
    a meaningful unit; per-hour is for ambient wear only.
    """
    assert evaluate.rate_per_minute(2, 1.7) == pytest.approx(2 / 1.7)


def test_labels_at_suppresses_low_confidence_gestures_only():
    p = probs(["flag", "none", "approve"], confidence=0.5)
    assert evaluate.labels_at(p, CLASSES, 0.9) == ["none", "none", "none"]
    assert evaluate.labels_at(p, CLASSES, 0.4) == ["flag", "none", "approve"]


# --- the split that makes calibration honest --------------------------------

def a_window(sid, t):
    return dataset.Window(session_id=sid, start_s=t, label="none", axes=[[0.0] * 50] * 3)


def test_split_by_time_produces_disjoint_halves():
    ws = [a_window("typing", i * 0.24) for i in range(500)]
    first, second = dataset.split_session_by_time(ws, "typing")
    assert first and second
    assert not ({w.start_s for w in first} & {w.start_s for w in second})


def test_split_by_time_leaves_a_guard_band_so_halves_do_not_share_samples():
    """
    Windows span 2.0 s and overlap 88%. Without a guard band the last window of
    one half and the first of the other share most of their samples, which is
    exactly the leak the split exists to close.
    """
    ws = [a_window("typing", i * 0.24) for i in range(500)]
    first, second = dataset.split_session_by_time(ws, "typing")
    gap = second[0].start_s - first[-1].start_s
    assert gap >= dataset.WINDOW_SAMPLES / dataset.SAMPLE_RATE_HZ


def test_split_by_time_ignores_other_sessions():
    ws = [a_window("typing", i * 0.24) for i in range(100)]
    ws += [a_window("walking", i * 0.24) for i in range(100)]
    first, second = dataset.split_session_by_time(ws, "typing")
    assert all(w.session_id == "typing" for w in first + second)


def test_split_by_time_of_a_missing_session_is_empty_not_an_error():
    assert dataset.split_session_by_time([], "nope") == ([], [])


def test_negative_segments_are_counted_separately_not_concatenated():
    """
    events.detect collapses *consecutive* windows into a run and has no notion of
    time. Concatenating two sessions lets the tail of one and the head of the
    other form a run that never happened -- silently inventing a false positive
    at every threshold, once per session boundary.
    """
    tail = probs(["flag"] * 2, confidence=0.9)
    head = probs(["flag"] * 2, confidence=0.9)
    st = starts(2)

    separate = evaluate.count_false_positives([(tail, st), (head, st)], CLASSES, 0.5)
    joined = evaluate.count_false_positives(
        [(np.concatenate([tail, head]), starts(4))], CLASSES, 0.5)

    assert separate == 0, "two runs of 2 are each below the debounce floor"
    assert joined == 1, "concatenating them fabricates a run of 4"


def test_false_positives_sum_across_segments():
    run = probs(["none"] * 3 + ["flag"] * 6 + ["none"] * 3, confidence=0.9)
    st = starts(12)
    assert evaluate.count_false_positives([(run, st)], CLASSES, 0.5) == 1
    assert evaluate.count_false_positives([(run, st), (run, st)], CLASSES, 0.5) == 2
