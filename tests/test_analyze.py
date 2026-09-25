from probe.simulate import generate, make_accel_payload, make_other_payload
from whip import analyze, protocol


def clean_stream(rate_hz: float, duration: float) -> list[tuple[float, bytes]]:
    """Perfectly regular accel-only stream."""
    interval = 1.0 / rate_hz
    n = int(duration * rate_hz)
    return [(i * interval, make_accel_payload(10, 1024, 20)) for i in range(n)]


def test_rate_is_measured_correctly():
    stats = analyze.analyze(clean_stream(50.0, 10.0), duration_s=10.0)
    assert abs(stats.accel_rate_hz - 50.0) < 0.5
    assert abs(stats.interval_median_ms - 20.0) < 0.5


def test_clean_stream_has_no_implied_loss():
    stats = analyze.analyze(clean_stream(50.0, 10.0), duration_s=10.0)
    assert stats.implied_loss < 0.001


def test_dropped_samples_show_up_as_loss():
    records = clean_stream(50.0, 10.0)
    # Drop every tenth sample: 10% loss.
    thinned = [r for i, r in enumerate(records) if i % 10 != 0]
    stats = analyze.analyze(thinned, duration_s=10.0)
    assert 0.05 < stats.implied_loss < 0.15


def test_gate_passes_on_a_good_stream():
    stats = analyze.analyze(clean_stream(50.0, 10.0), duration_s=10.0)
    assert stats.passes_rate
    assert stats.passes_loss
    assert stats.passes_gate


def test_gate_fails_below_25hz():
    stats = analyze.analyze(clean_stream(21.0, 10.0), duration_s=10.0)
    assert not stats.passes_rate
    assert not stats.passes_gate


def test_channel_split_counts_all_three_subtypes():
    records = []
    for i in range(30):
        t = i * 0.02
        records.append((t, make_accel_payload(0, 1024, 0)))
        records.append((t + 0.005, make_other_payload(protocol.SUBTYPE_PPG, 10000)))
        records.append((t + 0.010, make_other_payload(protocol.SUBTYPE_SPO2, 97)))

    stats = analyze.analyze(records, duration_s=0.6)
    names = {s.name: s.count for s in stats.subtypes}
    assert names == {"accel": 30, "ppg": 30, "spo2": 30}

    accel_share = next(s.share for s in stats.subtypes if s.name == "accel")
    assert abs(accel_share - 1 / 3) < 0.01


def test_stalls_contaminate_gesture_windows():
    """A stall longer than half a second breaks the 1.5s window it lands in."""
    records = generate(
        rate_hz=50.0, duration=30.0, accel_only=True, dropout_rate=0.0, stall_every=10.0, stall_len=1.0, seed=1
    )
    stats = analyze.analyze(records, duration_s=30.0)
    assert stats.windows_contaminated > 0
    assert stats.gap_max_ms > 500


def test_empty_capture_does_not_crash():
    stats = analyze.analyze([], duration_s=10.0)
    assert stats.total_packets == 0
    assert not stats.passes_gate


def test_report_renders():
    stats = analyze.analyze(clean_stream(50.0, 10.0), duration_s=10.0)
    text = analyze.format_report(stats)
    assert "OVERALL: PASS" in text
    assert "accelerometer" in text


def test_failing_report_suggests_next_steps():
    records = []
    for i in range(200):
        t = i * 0.05
        records.append((t, make_accel_payload(0, 1024, 0)))
        records.append((t + 0.01, make_other_payload(protocol.SUBTYPE_PPG, 1)))
        records.append((t + 0.02, make_other_payload(protocol.SUBTYPE_SPO2, 1)))

    stats = analyze.analyze(records, duration_s=10.0)
    text = analyze.format_report(stats)
    assert "OVERALL: FAIL" in text
    assert "sweep.py" in text


def _varying_stream(rate_hz: float, duration: float, start: float = 0.0) -> list[tuple[float, bytes]]:
    """A stream whose low bits toggle every frame, as sensor noise does."""
    interval = 1.0 / rate_hz
    n = int(duration * rate_hz)
    return [(start + i * interval, make_accel_payload(10 + (i % 3), 1024, 20 - (i % 2))) for i in range(n)]


def test_frozen_runs_are_counted_by_duration_not_by_frame():
    """
    A run of byte-identical frames at least FROZEN_RUN_S long is the STK8321's
    cached sample being repeated after the driver idled the chip; shorter
    identical runs are ordinary quiet noise and do not count.
    """
    fresh = _varying_stream(25.0, 10.0)
    frozen = [(10.0 + i * 0.04, make_accel_payload(7, 7, 7)) for i in range(75)]  # 3 s identical
    tail = _varying_stream(25.0, 5.0, start=13.0)
    stats = analyze.analyze(fresh + frozen + tail, duration_s=18.0)

    assert stats.frozen_runs == 1
    assert 2.9 < stats.longest_frozen_s < 3.1
    assert 2.9 < stats.frozen_s < 3.1
    assert 0.15 < stats.frozen_fraction < 0.18
    assert stats.distinct_fraction < 1.0

    # Rate and loss are blind to it: the stream kept its cadence throughout.
    assert stats.passes_rate
    assert stats.implied_loss < 0.001


def test_short_identical_runs_are_not_frozen():
    records = _varying_stream(25.0, 10.0)
    still = [(10.0 + i * 0.04, make_accel_payload(7, 7, 7)) for i in range(10)]  # 0.36 s
    stats = analyze.analyze(records + still, duration_s=10.4)
    assert stats.frozen_runs == 0
    assert stats.frozen_s == 0.0
    assert 0.3 < stats.longest_frozen_s < 0.4


def test_frozen_audit_handles_tiny_inputs():
    assert analyze.frozen_sample_audit([]) == (0, 0.0, 0.0, 0.0)
    assert analyze.frozen_sample_audit([(0.0, make_accel_payload(1, 2, 3))]) == (0, 0.0, 0.0, 1.0)
