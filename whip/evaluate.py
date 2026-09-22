"""
Scoring that cannot flatter itself.

Every "recall at 1 false positive per hour" figure this project reported before
this module existed was wrong in the same way: the threshold was chosen by
looking at the evaluation negative. That is tuning on test, and it does not
merely make the false-positive number optimistic -- it makes the *recall* number
optimistic too, by a different amount for each model, which silently reorders any
ranking built on it.

It is also unstable in a way that masquerades as model variance. Typing is ten
minutes, so a 1/hour budget permits 0.167 events, i.e. none. The chosen threshold
is then the lowest value at which no run of windows survives debouncing -- an
extreme-order statistic over a single session. It moves sharply between seeds,
and a large share of the seed spread previously attributed to architectures was
this number jumping around.

Three rules follow, and this module exists to make them hard to break.

**Calibrate on data you do not report on.** `calibrate()` takes a calibration
negative; the caller reports on a different one. `split_by_time` makes that
possible without new recordings.

**Report a curve, not a point.** A single operating point is hostage to one
window. `curve()` returns the whole recall-versus-false-positive trade-off.

**Report both variances.** Seed spread and *sampling* spread are different
quantities and the tables only ever had the first. At 64 held-out gestures the
binomial interval on 70% recall is about +/-11 points, which is wider than nearly
every architecture difference ever claimed here.

And a unit rule: a rate is per minute **of the activity being measured**. Nobody
waves for an hour, so "73 false positives per hour of waving" was never a
meaningful number. Per-hour is reserved for ambient wear, where it is what the
build spec actually asks for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from whip import events

# Operating points to evaluate. Below ~0.34 an argmax over three classes cannot
# be thresholded at all, so starting there covers the full usable range.
DEFAULT_THRESHOLDS = tuple(round(t, 3) for t in np.arange(0.34, 0.99, 0.01)) + (0.995, 0.999)

BOOTSTRAP_SAMPLES = 2000


class NotMeasurable(Exception):
    """A rate the recording is too short to support."""


def min_measurable_rate_per_minute(minutes: float) -> float:
    """
    The smallest non-zero rate a recording of this length can demonstrate.

    One event is the quantum. Asking a 10-minute session to show 1 false
    positive per hour means asking it to show 0.167 events, which it can only do
    by showing none -- and "none" over ten minutes is equally consistent with
    5/hour. Anything at or below this bound is an assertion, not a measurement.
    """
    return 1.0 / minutes if minutes > 0 else float("inf")


def rate_per_minute(n_events: int, minutes: float) -> float:
    return n_events / minutes if minutes > 0 else float("inf")


def labels_at(probabilities, class_names: list[str], threshold: float) -> list[str]:
    """
    Per-window class calls at a confidence threshold.

    A window is a gesture only if the winning class is a gesture *and* it wins by
    more than `threshold`. Below that it is `none`, which is what lets one model
    be moved along its own precision/recall trade-off.
    """
    out = []
    for row in np.asarray(probabilities):
        k = int(np.argmax(row))
        name = class_names[k]
        # Membership by name, never by index: the `motion`-class episode proved
        # that any `k > 0 means gesture` test rots the moment the label set
        # changes. With the registry vocabulary, everything except `none` is a
        # gesture -- but the comparison stays on the name.
        out.append(name if name != "none" and row[k] >= threshold else "none")
    return out


def calibrate(
    probabilities,
    starts: list[float],
    minutes: float,
    class_names: list[str],
    budget_per_minute: float,
    thresholds=DEFAULT_THRESHOLDS,
    min_run: int = events.MIN_RUN,
    max_run: int = events.MAX_RUN,
    strict: bool = True,
    policies: dict | None = None,
) -> float:
    """
    Lowest threshold whose false-positive rate on *this* session meets the budget.

    The session passed here must not be the one results are reported on. Nothing
    in Python can enforce that, so it is stated in every docstring that touches
    it and tested in `tests/test_evaluate.py`.

    Raises `NotMeasurable` when the budget is below what the recording length can
    demonstrate, rather than returning a threshold that merely means "no events
    happened to occur in this particular ten minutes".
    """
    if strict and budget_per_minute < min_measurable_rate_per_minute(minutes):
        raise NotMeasurable(
            f"a budget of {budget_per_minute:.4f}/min needs more than {minutes:.1f} min "
            f"to demonstrate; the smallest measurable non-zero rate here is "
            f"{min_measurable_rate_per_minute(minutes):.4f}/min"
        )

    for threshold in thresholds:
        found = events.detect(
            labels_at(probabilities, class_names, threshold), starts,
            min_run=min_run, max_run=max_run, policies=policies)
        if rate_per_minute(len(found), minutes) <= budget_per_minute:
            return float(threshold)
    return float(thresholds[-1])


def gesture_hits(
    detected: list[events.Event],
    truth: list[tuple[float, str]],
    tolerance_s: float = events.MATCH_TOLERANCE_S,
    require_class: bool = True,
    early_s: float | None = None,
) -> list[bool]:
    """
    One boolean per labelled gesture: was it detected?

    Returned per gesture rather than aggregated, because the bootstrap needs the
    individual outcomes to resample. A mean of this list is the recall.

    `early_s` widens the window BEFORE the cue: burst events are timed at the
    motion's onset, and a wearer on a predictable schedule starts up to 1.4 s
    before the cue (the split's own `MARK_BEFORE_S`); the run decoder's
    centre-of-run estimate landed inside +/-0.75 s by construction, an onset
    does not. Defaults to the symmetric tolerance.
    """
    early = tolerance_s if early_s is None else early_s
    remaining = list(detected)
    hits = []
    for t, label in truth:
        match = next(
            (e for e in remaining
             if -early <= e.centre_s - t <= tolerance_s and (e.label == label or not require_class)),
            None)
        if match is not None:
            remaining.remove(match)
        hits.append(match is not None)
    return hits


def bootstrap_recall_ci(
    hits: list[bool],
    n_samples: int = BOOTSTRAP_SAMPLES,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """
    Sampling interval on recall, by resampling gestures with replacement.

    This is the variance that comes from having recorded 64 gestures rather than
    6400, and it is *not* what a seed-to-seed standard deviation measures. Both
    belong in a results table; only the second was ever reported here.
    """
    if not hits:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    arr = np.asarray(hits, dtype=float)
    draws = rng.integers(0, len(arr), size=(n_samples, len(arr)))
    means = arr[draws].mean(axis=1)
    return (float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2)))


@dataclass(frozen=True)
class CurvePoint:
    threshold: float
    hits: int
    total: int
    false_positives: int
    negative_minutes: float

    @property
    def recall(self) -> float:
        return self.hits / self.total if self.total else float("nan")

    @property
    def fp_per_minute(self) -> float:
        return rate_per_minute(self.false_positives, self.negative_minutes)

    @property
    def fp_upper_bound_per_minute(self) -> float:
        """
        95% upper bound on the false-positive rate, given how little was observed.

        This is the number that stops a short recording sounding conclusive.
        Zero events in ten minutes is not evidence of a low rate: by the rule of
        three the upper bound is 3/10 per minute, i.e. **18 per hour**. So ten
        minutes of typing cannot demonstrate the build spec's <1/hour no matter
        what it shows -- a fact worth printing next to every clean-looking zero.
        """
        if self.negative_minutes <= 0:
            return float("inf")
        k = self.false_positives
        if k == 0:
            return 3.0 / self.negative_minutes           # rule of three
        # Poisson upper bound, normal approximation. Adequate here; the k == 0
        # case is the one that decides whether a claim is supportable.
        return (k + 1.96 * (k ** 0.5) + 2.0) / self.negative_minutes


def count_false_positives(
    segments,
    class_names: list[str],
    threshold: float,
    min_run: int = events.MIN_RUN,
    max_run: int = events.MAX_RUN,
    policies: dict | None = None,
) -> int:
    """
    False positives across several negative stretches, counted per stretch.

    `segments` is a list of (probabilities, starts). They must be counted
    separately and summed, never concatenated: `events.detect` collapses
    *consecutive* windows into a run and has no notion of time, so joining two
    sessions end to end lets the last windows of one and the first of the other
    form a run that never happened. With four sessions that silently invents up
    to three false positives at every threshold.
    """
    return sum(
        len(events.detect(labels_at(probs, class_names, threshold), starts,
                          min_run=min_run, max_run=max_run, policies=policies))
        for probs, starts in segments
    )


def curve(
    gesture_probabilities,
    gesture_starts: list[float],
    truth: list[tuple[float, str]],
    negative_segments,
    negative_minutes: float,
    class_names: list[str],
    thresholds=DEFAULT_THRESHOLDS,
    min_run: int = events.MIN_RUN,
    max_run: int = events.MAX_RUN,
    require_class: bool = True,
    policies: dict | None = None,
) -> list[CurvePoint]:
    """
    The whole recall-versus-false-positive trade-off, one point per threshold.

    `negative_segments` is a list of (probabilities, starts) -- the **reporting**
    negatives, which must differ from whatever `calibrate` was given. Several are
    accepted because a false-positive budget is a claim about mixed realistic
    wear rather than about one activity, and because they must be counted
    separately (see `count_false_positives`).

    Comparing two models at a single operating point compares their confidence
    calibration as much as their discriminative power -- which is how a merely
    reluctant model came to look precise in an earlier version of this project's
    architecture table. Read recall at a matched false-positive rate instead.
    """
    points = []
    for threshold in thresholds:
        found = events.detect(
            labels_at(gesture_probabilities, class_names, threshold), gesture_starts,
            min_run=min_run, max_run=max_run, policies=policies)
        hits = gesture_hits(found, truth, require_class=require_class)
        fp = count_false_positives(negative_segments, class_names, threshold,
                                   min_run=min_run, max_run=max_run, policies=policies)
        points.append(CurvePoint(
            threshold=float(threshold), hits=sum(hits), total=len(hits),
            false_positives=fp, negative_minutes=negative_minutes))
    return points


def recall_at_budget(points: list[CurvePoint], budget_per_minute: float) -> CurvePoint | None:
    """
    The most permissive operating point that still meets a false-positive budget.

    Returns None when no threshold meets it, which is a real answer and must not
    be silently replaced by the closest one.
    """
    ok = [p for p in points if p.fp_per_minute <= budget_per_minute]
    return max(ok, key=lambda p: p.recall) if ok else None


def area_under_curve(points: list[CurvePoint], max_fp_per_minute: float) -> float:
    """
    Mean recall across the usable part of the curve.

    A single-number summary that is not hostage to one threshold. Use it to rank
    models; use the curve itself to understand them.
    """
    usable = sorted((p for p in points if p.fp_per_minute <= max_fp_per_minute),
                    key=lambda p: p.fp_per_minute)
    if not usable:
        return 0.0
    return float(np.mean([p.recall for p in usable]))
