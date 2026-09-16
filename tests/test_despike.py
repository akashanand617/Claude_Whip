import numpy as np

from whip import despike


def quiet(n=40, level=0.2, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(0, level, n)


def flick(n=40, centre=20, width=9, height=4.5):
    """A gesture-shaped peak: ~9 samples above half height, as measured."""
    t = np.arange(n)
    return height * np.exp(-0.5 * ((t - centre) / (width / 2.355)) ** 2)


def test_a_single_sample_spike_is_removed():
    x = quiet()
    x[20] = 6.0
    out = despike.hampel(x)
    assert out[20] < 1.0, "the spike should be pulled down to the local level"
    assert np.allclose(out[:18], x[:18], atol=1e-9), "quiet samples untouched"


def test_a_real_gesture_peak_survives():
    """
    The whole reason for Hampel over a median filter. median-3 removes the
    artifacts but costs 17% of real gesture peak amplitude; this must cost
    almost nothing, because the peak is the signal.
    """
    x = flick()
    out = despike.hampel(x)
    assert out.max() >= 0.97 * x.max()


def test_the_measured_case_that_forced_leave_one_out():
    """
    A real neighbourhood from the typing session. Including the sample under
    test in its own baseline lets the spike inflate the MAD it is judged
    against: threshold 3.56 versus a deviation of 2.70, so it survived.
    """
    x = np.array([0.55, 0.17, 0.90, 1.10, 3.60, 0.30, 0.14, 0.28, 0.21])
    out = despike.hampel(x)
    assert out[4] < 1.0, "the 3.60 g spike must be replaced"


def test_filtering_runs_along_the_last_axis_for_any_shape():
    for shape in ((40,), (3, 40), (5, 3, 40)):
        x = np.zeros(shape)
        x[..., 20] = 9.0
        out = despike.hampel(x)
        assert out.shape == shape
        assert np.all(out[..., 20] < 1.0)


def test_axes_are_filtered_independently():
    x = np.zeros((3, 40))
    x[1, 20] = 9.0
    out = despike.hampel(x)
    assert out[1, 20] < 1.0
    assert np.allclose(out[0], 0.0) and np.allclose(out[2], 0.0)


def test_a_spike_in_perfect_quiet_is_still_caught():
    """
    An earlier version exempted zero-MAD neighbourhoods, on the theory that it
    protected a gesture starting from rest. That was backwards: with
    leave-one-out, a real onset has elevated *following* neighbours so its MAD
    is never zero. The exemption only ever protected genuine artifacts.
    """
    x = np.zeros(40)
    x[20] = 9.0
    assert despike.hampel(x)[20] < 1.0


def test_edges_are_not_hypersensitive():
    """
    Edge-replicate padding puts identical values in the boundary neighbourhood,
    collapsing the MAD and the threshold with it. Measured, it "corrected" an
    ordinary sample by 0.05 g purely for sitting at index 1.
    """
    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.2, 40)
    out = despike.hampel(x)
    assert np.allclose(out[:4], x[:4], atol=1e-9)
    assert np.allclose(out[-4:], x[-4:], atol=1e-9)


def test_too_short_to_filter_is_returned_unchanged():
    x = np.array([1.0, 5.0, 1.0])
    assert np.allclose(despike.hampel(x, half_window=3), x)


def test_peak_width_separates_an_artifact_from_a_gesture():
    """
    The statistic the whole diagnosis rests on: ~1 sample for a glitch, ~9 for
    a real flick.
    """
    spike = np.zeros(40)
    spike[20] = 6.0
    assert despike.peak_width_samples(spike) == 1
    assert despike.peak_width_samples(flick()) >= 7


def test_peak_width_of_nothing_is_zero():
    assert despike.peak_width_samples(np.zeros(10)) == 0
    assert despike.peak_width_samples(np.array([])) == 0


def test_count_replaced_reports_what_the_filter_touched():
    x = quiet()
    x[10] = 8.0
    x[25] = -8.0
    assert despike.count_replaced(x) >= 2


def test_defaults_are_the_conservative_end_of_the_passing_range():
    """
    Several parameter settings clear the acceptance criteria. The defaults are
    the most conservative of them -- the filter should intervene as little as
    possible while still removing the artifacts.
    """
    assert despike.HALF_WINDOW == 3
    assert despike.N_SIGMAS == 8.0
    # the neighbourhood must stay narrower than the gesture peak it protects
    assert 2 * despike.HALF_WINDOW + 1 < 9 + 2


def test_a_two_sample_shock_survives_and_a_one_sample_glitch_does_not():
    """
    A snap at the ring is a 1-2 sample shock at 5-7 g, the width of a BLE
    glitch; the filter must keep a shock whose neighbour is also elevated and
    still remove a lone sample. Same rule in the streaming filter.
    """
    import numpy as np
    from whip import despike

    quiet = np.zeros((3, 60)) + 0.02 * np.random.default_rng(0).standard_normal((3, 60))
    glitch = quiet.copy(); glitch[1, 30] = 4.0
    shock = quiet.copy(); shock[1, 30] = 5.0; shock[1, 31] = -3.0
    assert abs(despike.hampel(glitch)[1, 30]) < 0.5
    out = despike.hampel(shock)
    assert out[1, 30] == 5.0 and out[1, 31] == -3.0
    for trace, keep in ((glitch, False), (shock, True)):
        f = despike.StreamingHampel(); got = []
        for k in range(trace.shape[1]):
            got.extend(f.push(trace[:, k]))
        got.extend(f.drain())
        got = np.stack(got, axis=1)
        assert (abs(got[1, 30]) > 4.0) == keep
