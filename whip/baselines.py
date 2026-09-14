"""
The numbers the CNN has to beat.

Both come from features measured before any model existed, on 33 real gestures:
duration separates the classes 73% of the time, oscillation count 85%. If a
network cannot clear those on a held-out session, it has learned nothing a
threshold could not, and reporting "94% accuracy" without them would hide that.

They are also a diagnostic. A model that beats duration but not peak count is
probably keying on the wrong thing -- duration is session-correlated (execution
speed drifts ~50% between sittings), so leaning on it scores well within a
session and collapses across days.
"""

from __future__ import annotations

import statistics

# Windows arrive gravity-removed and in g. A gesture reaches ~4.9 g while typing
# peaks near 2.0, so this sits between the two populations.
ACTIVITY_THRESHOLD_G = 0.6


def magnitude(window: list[list[float]]) -> list[float]:
    """Per-sample vector magnitude of a (3, N) window."""
    xs, ys, zs = window
    return [(x * x + y * y + z * z) ** 0.5 for x, y, z in zip(xs, ys, zs)]


def active_span(mag: list[float], threshold: float = ACTIVITY_THRESHOLD_G) -> tuple[int, int]:
    """First and last sample above threshold. (-1, -1) when nothing is."""
    above = [i for i, m in enumerate(mag) if m > threshold]
    return (above[0], above[-1]) if above else (-1, -1)


def duration_samples(window: list[list[float]], threshold: float = ACTIVITY_THRESHOLD_G) -> int:
    lo, hi = active_span(magnitude(window), threshold)
    return 0 if lo < 0 else hi - lo + 1


def peak_count(window: list[list[float]], threshold: float = ACTIVITY_THRESHOLD_G) -> int:
    """
    Local maxima above 40% of the window's peak, at least two samples apart.

    This is the feature that actually separates the classes: singles average 2
    oscillations, doubles 5. Duration overlaps completely and even inverts --
    in the fastest recorded session the doubles were shorter than the singles.
    """
    mag = magnitude(window)
    lo, hi = active_span(mag, threshold)
    if lo < 0:
        return 0
    cut = 0.4 * max(mag[lo:hi + 1])
    count, last = 0, -99
    for i in range(max(lo, 1), min(hi, len(mag) - 1)):
        if mag[i] > cut and mag[i] >= mag[i - 1] and mag[i] >= mag[i + 1] and i - last >= 2:
            count += 1
            last = i
    return count


# A gesture peaks around 4.9 g; typing peaks near 2.0 and idle motions lower.
# Without this the rule fires on almost every negative window -- amplitude was
# the strongest of the three features in the original event-level analysis, and
# leaving it out makes the baseline uselessly weak rather than honestly crude.
MIN_GESTURE_PEAK_G = 2.5


def predict(
    window: list[list[float]],
    min_duration: int = 8,
    single_max_peaks: int = 3,
    min_peak_g: float = MIN_GESTURE_PEAK_G,
) -> str:
    """
    A deliberately crude three-way rule, for comparison only.

    Quiet, brief or weak -> none. Otherwise single versus double by oscillation
    count, which is the feature that actually separates the two classes.
    """
    mag = magnitude(window)
    if max(mag) < min_peak_g:
        return "none"
    if duration_samples(window) < min_duration:
        return "none"
    return "flag" if peak_count(window) <= single_max_peaks else "approve"


# --- shape features, measured amplitude-matched ----------------------------
#
# These exist because they are *strong*, not for completeness. Restricted to
# windows whose peak lies in 3.6-7.0 g -- so amplitude is matched by construction
# and carries no information -- they separate flicks from waving at:
#
#     energy concentration   0.972
#     zero crossings         0.927
#     crest factor           0.870
#     peak amplitude         0.707   (the control, deliberately weak here)
#
# No model, no training. This is what refuted the claim that the distinction was
# absent from the data, and it means any network has to beat a hand-computed
# feature before its parameters are justified.
#
# The physical content: a flick is one impulsive lobe of 100-200 ms followed by
# quiet. A wave is periodic at 1-3 Hz for seconds. Those differ in how many times
# the signal crosses zero, and in how much of the window's energy sits near the
# single largest peak.

CONCENTRATION_HALF_WIDTH = 5
"""Samples either side of the peak, 400 ms total at 25 Hz -- about one lobe."""


def energy_concentration(window: list[list[float]], half_width: int = CONCENTRATION_HALF_WIDTH) -> float:
    """
    Share of the window's total magnitude lying within ~400 ms of its peak.

    High for an impulse, low for sustained oscillation. The strongest single
    amplitude-matched discriminator measured: 0.972 against waving.
    """
    mag = magnitude(window)
    total = sum(mag)
    if total <= 0:
        return 0.0
    k = max(range(len(mag)), key=lambda i: mag[i])
    lo, hi = max(0, k - half_width), min(len(mag), k + half_width + 1)
    return sum(mag[lo:hi]) / total


ZERO_CROSSING_HYSTERESIS = 0.1
"""Fraction of peak the signal must reach before a reversal counts."""


def zero_crossings(window: list[list[float]],
                   hysteresis: float = ZERO_CROSSING_HYSTERESIS) -> int:
    """
    How many times the most active axis genuinely reverses direction.

    Medians measured amplitude-matched: 6 for a flick, 17 for waving. Windows
    arrive with the DC term removed, so zero is the resting level.

    **Hysteresis is not optional.** Counting raw sign changes makes a quiet
    stretch of sensor noise look like violent oscillation -- noise straddles zero
    constantly, so a window that is 90% silence can out-score a genuine wave. The
    signal must reach a tenth of its own peak on one side before a crossing to
    the other is counted, which is what makes this a measure of reversals rather
    than of how close the trace sits to zero.
    """
    axis = max(window, key=lambda a: statistics.pstdev(a) if len(a) > 1 else 0.0)
    cut = hysteresis * max((abs(v) for v in axis), default=0.0)
    if cut <= 0:
        return 0

    count, state = 0, 0
    for value in axis:
        if value > cut:
            if state == -1:
                count += 1
            state = 1
        elif value < -cut:
            if state == 1:
                count += 1
            state = -1
    return count


def crest_factor(window: list[list[float]]) -> float:
    """Peak over mean magnitude. Impulsive motion is peaky; sustained motion is not."""
    mag = magnitude(window)
    mean = sum(mag) / len(mag) if mag else 0.0
    return max(mag) / mean if mean > 0 else 0.0


def burst_duration_samples(window: list[list[float]], threshold_fraction: float = 0.5) -> int:
    """
    Width of the main excursion, measured above a fraction of its own peak.

    Amplitude-relative rather than absolute, so a soft flick and a hard one
    measure the same -- which is the point, since an absolute threshold would
    just re-measure amplitude. ~9 samples for a flick, ~1 for a BLE artifact.
    """
    mag = magnitude(window)
    if not mag or max(mag) <= 0:
        return 0
    cut = threshold_fraction * max(mag)
    return sum(1 for m in mag if m > cut)


def shape_features(window: list[list[float]]) -> dict[str, float]:
    """All of the above at once, for scoring a corpus without four passes."""
    return {
        "energy_concentration": energy_concentration(window),
        "zero_crossings": float(zero_crossings(window)),
        "crest_factor": crest_factor(window),
        "burst_duration": float(burst_duration_samples(window)),
        "peak_g": max(magnitude(window)) if window[0] else 0.0,
    }


def evaluate(windows: list[list[list[float]]], labels: list[str]) -> dict:
    """Accuracy overall and per class, plus the confusion matrix."""
    names = ("none", "flag", "approve")
    confusion = {a: {b: 0 for b in names} for a in names}
    for w, truth in zip(windows, labels):
        confusion[truth][predict(w)] += 1

    total = len(labels) or 1
    correct = sum(confusion[n][n] for n in names)
    per_class = {}
    for n in names:
        seen = sum(confusion[n].values())
        per_class[n] = confusion[n][n] / seen if seen else 0.0

    return {"accuracy": correct / total, "per_class": per_class, "confusion": confusion}


def summarise_features(windows: list[list[list[float]]], labels: list[str]) -> dict:
    """Median duration and peak count per class -- the shape of the problem."""
    out: dict[str, dict] = {}
    for name in ("none", "flag", "approve"):
        chosen = [w for w, l in zip(windows, labels) if l == name]
        if not chosen:
            continue
        out[name] = {
            "n": len(chosen),
            "duration_samples": statistics.median([duration_samples(w) for w in chosen]),
            "peaks": statistics.median([peak_count(w) for w in chosen]),
        }
    return out
