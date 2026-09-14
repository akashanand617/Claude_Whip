import numpy as np
import pytest

from whip import baselines, sampling


def impulse(n=50, centre=25, width=9, height=4.5, hz=6.0):
    """
    A flick: one lobe of oscillation, then quiet.

    The carrier is in quadrature across two axes, because a flick is a wrist
    *rotation* -- the magnitude envelope is smooth rather than dipping to zero
    between half-cycles the way a single-axis sine would.
    """
    t = np.arange(n)
    env = height * np.exp(-0.5 * ((t - centre) / (width / 2.355)) ** 2)
    phase = 2 * np.pi * hz * t / 25
    return [(env * np.sin(phase)).tolist(), (env * np.cos(phase)).tolist(), [0.0] * n]


def periodic(n=50, hz=2.0, height=4.5):
    """A wave: sustained oscillation for the whole window."""
    t = np.arange(n)
    phase = 2 * np.pi * hz * t / 25
    return [(height * np.sin(phase)).tolist(), (height * np.cos(phase)).tolist(), [0.0] * n]


# --- weighting --------------------------------------------------------------

def test_only_loud_negatives_are_upweighted():
    peaks = np.array([0.5, 3.0, 0.5, 3.0])
    labels = np.array([0, 0, 1, 1])
    w = sampling.loud_negative_weights(peaks, labels, loud_g=2.48, factor=10.0)
    assert list(w) == [1.0, 10.0, 1.0, 1.0], "gestures keep weight 1 whatever their amplitude"


def test_the_share_being_upweighted_is_tiny_which_is_the_whole_point():
    """
    Two percent of the negative set. Under a plain cross-entropy, getting every
    one of them wrong is inside the noise of the other ninety-eight -- which is
    why the model learned amplitude and fired whenever a hand moved sharply.
    """
    rng = np.random.default_rng(0)
    peaks = np.concatenate([rng.uniform(0, 2.0, 980), rng.uniform(2.6, 5.0, 20)])
    labels = np.zeros(1000, dtype=int)
    assert sampling.loud_negative_fraction(peaks, labels) == pytest.approx(0.02, abs=0.005)


def test_weighting_lifts_the_loud_share_of_the_loss_without_letting_it_dominate():
    rng = np.random.default_rng(0)
    peaks = np.concatenate([rng.uniform(0, 2.0, 980), rng.uniform(2.6, 5.0, 20)])
    labels = np.zeros(1000, dtype=int)
    w = sampling.loud_negative_weights(peaks, labels, factor=10.0)
    share = w[peaks >= sampling.DEFAULT_LOUD_G].sum() / w.sum()
    assert 0.10 < share < 0.30, f"loud negatives should matter, not take over (got {share:.2f})"


def test_the_loud_boundary_is_derived_from_the_gestures_not_hardcoded():
    peaks = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    labels = np.array([0, 0, 1, 1, 1, 1])
    assert sampling.gesture_peak_percentile(peaks, labels, 0.0) == pytest.approx(3.0)


def test_describe_surfaces_the_overlap_that_explains_the_failure():
    peaks = np.array([1.0, 1.2, 3.0, 4.5, 5.0])
    labels = np.array([0, 0, 0, 1, 1])
    d = sampling.describe(peaks, labels)
    assert d["n_negatives"] == 3 and d["n_loud_negatives"] == 1
    assert "gesture_p10_g" in d and "negative_p90_g" in d


# --- two-stage gate ---------------------------------------------------------

def test_the_gate_is_set_for_recall_because_what_it_drops_is_lost_for_good():
    rng = np.random.default_rng(0)
    peaks = np.concatenate([rng.uniform(0, 1.5, 500), rng.uniform(2.5, 6.0, 100)])
    labels = np.concatenate([np.zeros(500, dtype=int), np.ones(100, dtype=int)])
    thr = sampling.amplitude_gate_threshold(peaks, labels, keep_gesture_fraction=0.99)
    kept = sampling.gate_mask(peaks, thr)
    assert kept[labels > 0].mean() >= 0.98
    assert kept[labels == 0].mean() < 0.2, "the quiet majority should be discarded cheaply"


def test_the_gate_leaves_a_problem_amplitude_cannot_solve():
    """
    The point of the two stages. After the gate, the survivors are all loud, so
    amplitude is nearly useless by construction and the classifier has to use
    shape.
    """
    rng = np.random.default_rng(0)
    peaks = np.concatenate([rng.uniform(0, 1.5, 500), rng.uniform(2.5, 6.0, 100),
                            rng.uniform(2.5, 6.0, 40)])
    labels = np.concatenate([np.zeros(500, dtype=int), np.ones(100, dtype=int),
                             np.zeros(40, dtype=int)])
    thr = sampling.amplitude_gate_threshold(peaks, labels)
    kept = sampling.gate_mask(peaks, thr)
    before = sampling.loud_negative_fraction(peaks, labels, thr)
    after = (labels[kept] == 0).mean()
    assert after > before * 3, "the gate concentrates the hard negatives"


def test_window_peaks_ignores_extra_channels():
    """Works on a stored (N,3,W) window set and on derived (N,C,W) model input."""
    x = np.zeros((2, 6, 50), dtype="float32")
    x[:, 0, 10] = 3.0
    x[:, 4, :] = 99.0          # a scale channel must not be read as acceleration
    assert np.allclose(sampling.window_peaks(x), 3.0)


# --- shape features ---------------------------------------------------------

def test_energy_concentration_separates_an_impulse_from_oscillation():
    """The strongest amplitude-matched discriminator measured: 0.972 vs waving."""
    assert baselines.energy_concentration(impulse()) > baselines.energy_concentration(periodic())


def test_zero_crossings_separate_a_flick_from_a_wave():
    """Measured medians, amplitude-matched: 6 for a flick, 17 for waving."""
    assert baselines.zero_crossings(impulse()) < baselines.zero_crossings(periodic(hz=6.0))


def test_zero_crossings_ignore_noise_around_the_resting_level():
    """
    Without hysteresis a window that is 90% silence out-scores a genuine wave,
    because sensor noise straddles zero constantly. That would make the feature
    measure how close the trace sits to zero rather than how often it reverses.
    """
    rng = np.random.default_rng(0)
    quiet = [(rng.normal(0, 0.01, 50)).tolist(), [0.0] * 50, [0.0] * 50]
    quiet[0][25] = 5.0
    assert baselines.zero_crossings(quiet) <= 2
    assert baselines.zero_crossings(periodic(hz=6.0)) > 5


def test_crest_factor_is_higher_for_impulsive_motion():
    assert baselines.crest_factor(impulse()) > baselines.crest_factor(periodic())


def test_burst_duration_is_amplitude_relative():
    """
    An absolute threshold would just re-measure amplitude. A soft flick and a
    hard one are the same gesture and must measure the same duration.
    """
    soft = baselines.burst_duration_samples(impulse(height=2.3))
    hard = baselines.burst_duration_samples(impulse(height=6.0))
    assert soft == hard


def test_burst_duration_tells_a_gesture_from_an_artifact():
    spike = [[0.0] * 50, [0.0] * 50, [0.0] * 50]
    spike[0][25] = 6.0
    assert baselines.burst_duration_samples(spike) == 1
    assert baselines.burst_duration_samples(impulse()) >= 5, "a rotation has a smooth envelope"


def test_shape_features_returns_all_of_them():
    f = baselines.shape_features(impulse())
    assert set(f) == {"energy_concentration", "zero_crossings", "crest_factor",
                      "burst_duration", "peak_g"}


def test_shape_features_of_silence_do_not_divide_by_zero():
    silent = [[0.0] * 50] * 3
    f = baselines.shape_features(silent)
    assert all(np.isfinite(v) for v in f.values())
