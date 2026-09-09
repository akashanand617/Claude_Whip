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
