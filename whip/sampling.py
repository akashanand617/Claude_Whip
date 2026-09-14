"""
Make the loss care about the 2% of negatives that decide deployability.

Peak amplitude alone separates gesture from not-gesture at AUC 0.953 on this
corpus. That is not a statement about the sensor; it is a statement about what
was recorded. Negatives have a p90 of 2.53 g and gestures a p10 of 2.48 g, so the
distributions barely touch, and of 6555 negative windows only about 134 are as
loud as a typical gesture -- nearly all from one 1.7-minute waving clip.

Under a plain cross-entropy, getting **every one of those 134 wrong costs almost
nothing**. Two percent of the negative term is inside the noise of the other
ninety-eight. So the network learns amplitude, which is the correct answer to the
question the loss is asking, and then fires whenever your hand moves sharply.

The diagnosis this replaces was that the distinction is absent from the data.
That was wrong, and circular: it rested on architectures failing on waving while
the waving clip was held out of their training. Amplitude-matched, a single
hand-computed feature separates flicks from waves at AUC 0.972. The information
is there. The objective was ignoring it.

Two ways to stop ignoring it, both offered here because the choice should be
measured rather than argued:

**Reweighting** -- `loud_negative_weights` -- keeps one model and one pass, and
simply makes a loud negative worth many quiet ones.

**Two-stage** -- `amplitude_gate_threshold` -- puts a cheap amplitude gate first
and trains a shape classifier only on what survives it. The classifier then sees
a balanced problem where amplitude is nearly useless by construction, which is
the condition under which it is forced to learn shape.
"""

from __future__ import annotations

import numpy as np

# A negative this loud is inside the gesture distribution, so it is the kind the
# model must reject on shape rather than on amplitude. The default is the 10th
# percentile of measured gesture peaks: 2.48 g.
DEFAULT_LOUD_G = 2.48

# How much more a loud negative is worth than a quiet one.
#
# Loud negatives are ~2% of the negative set. A factor of 10 lifts them to ~17%
# of the negative loss term -- enough to matter, short of letting 134 windows
# dominate training. Tuned by ablation, not taste; see probe/ablate.py.
DEFAULT_LOUD_FACTOR = 10.0


def window_peaks(x) -> np.ndarray:
    """Peak vector magnitude per window, in g. Input (N, 3, W) or (N, C, W)."""
    x = np.asarray(x)
    return np.sqrt((x[:, :3] ** 2).sum(axis=1)).max(axis=1)


def gesture_peak_percentile(peaks, labels, percentile: float = 10.0) -> float:
    """
    The amplitude below which gestures rarely fall.

    Used as the boundary of the overlap region. Derived from the data rather than
    fixed, because it moves with the despike filter and with any future change to
    the accelerometer range.
    """
    gesture = np.asarray(peaks)[np.asarray(labels) > 0]
    return float(np.percentile(gesture, percentile)) if len(gesture) else DEFAULT_LOUD_G


def loud_negative_weights(
    peaks,
    labels,
    loud_g: float = DEFAULT_LOUD_G,
    factor: float = DEFAULT_LOUD_FACTOR,
) -> np.ndarray:
    """
    Per-sample loss weights that make loud negatives expensive to get wrong.

    Returns 1.0 everywhere except negatives at or above `loud_g`, which get
    `factor`. Multiply these into a per-sample loss; they are deliberately
    independent of the class weights, which correct a different imbalance (there
    are eight times more `none` windows than gesture windows) and would otherwise
    be entangled with this one.
    """
    peaks = np.asarray(peaks, dtype="float64")
    labels = np.asarray(labels)
    weights = np.ones(len(peaks))
    weights[(labels == 0) & (peaks >= loud_g)] = factor
    return weights


def loud_negative_fraction(peaks, labels, loud_g: float = DEFAULT_LOUD_G) -> float:
    """What share of the negative set is in the overlap region. ~2% as recorded."""
    labels = np.asarray(labels)
    negatives = np.asarray(peaks)[labels == 0]
    return float((negatives >= loud_g).mean()) if len(negatives) else 0.0


def amplitude_gate_threshold(peaks, labels, keep_gesture_fraction: float = 0.99) -> float:
    """
    Amplitude below which nothing is worth examining.

    Deliberately set for recall, not precision: the gate's job is to discard the
    overwhelmingly quiet majority cheaply, and any gesture it drops is lost for
    good because the second stage never sees it. Everything that survives is then
    a problem where amplitude is nearly useless, which is exactly the condition
    that forces a classifier onto shape.
    """
    gesture = np.asarray(peaks)[np.asarray(labels) > 0]
    if not len(gesture):
        return 0.0
    return float(np.percentile(gesture, (1.0 - keep_gesture_fraction) * 100))


def gate_mask(peaks, threshold: float) -> np.ndarray:
    return np.asarray(peaks) >= threshold


def describe(peaks, labels, loud_g: float = DEFAULT_LOUD_G) -> dict:
    """
    The numbers worth printing before training, because they explain the result.

    If `loud_negative_share` is a couple of percent, an unweighted loss is very
    nearly indifferent to the windows that decide the false-positive rate, and no
    amount of architecture will change that.
    """
    peaks = np.asarray(peaks)
    labels = np.asarray(labels)
    return {
        "loud_g": loud_g,
        "n_negatives": int((labels == 0).sum()),
        "n_loud_negatives": int(((labels == 0) & (peaks >= loud_g)).sum()),
        "loud_negative_share": loud_negative_fraction(peaks, labels, loud_g),
        "gesture_p10_g": gesture_peak_percentile(peaks, labels, 10.0),
        "negative_p90_g": float(np.percentile(peaks[labels == 0], 90))
        if (labels == 0).any() else float("nan"),
    }
