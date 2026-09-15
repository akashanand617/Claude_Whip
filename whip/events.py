"""
Turn per-window predictions into gesture events, and score them.

Window accuracy is not the deliverable and is actively misleading here. One
gesture spans ~6 overlapping windows, so window metrics count it six times; and
a single isolated negative window scored as a failure may never survive
debouncing to become a real false positive.

What the build spec asks for is event-level: did a gesture get detected, and how
many false detections occur per hour of normal wear.

**Debouncing needs a band, not a floor.** A gesture fires roughly 6-8 consecutive
windows. Sustained motion -- a three-second wave -- fires 15 or more. Requiring
`>= k consecutive` therefore makes waving *more* likely to trigger, not less,
which is the opposite of the intent. Accepting only a plausible run length
rejects isolated noise and sustained oscillation with one mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass

from whip.dataset import GESTURE_LABELS

STRIDE_S = 0.24   # 6 samples at 25 Hz
WINDOW_S = 2.0    # 50 samples at 25 Hz

# A 1.2 s gesture inside a 2.0 s window at 0.24 s stride produces ~6 positive
# windows. Sustained motion produces far more.
MIN_RUN = 3
MAX_RUN = 14

# How close a detection must be to a labelled gesture to count as finding it.
MATCH_TOLERANCE_S = 0.75


@dataclass(frozen=True)
class Event:
    label: str
    start_s: float
    end_s: float
    run_length: int

    @property
    def centre_s(self) -> float:
        """
        Centre of the detected motion, not of the window indices.

        Window timestamps are *start* times, so a window at T covers T..T+2.0 s.
        Averaging start times alone puts the event a full second early -- more
        than the matching tolerance, so every detection missed and event F1 read
        zero while the model was working.
        """
        return (self.start_s + self.end_s) / 2 + WINDOW_S / 2


def detect(
    predictions: list[str],
    starts: list[float],
    min_run: int = MIN_RUN,
    max_run: int = MAX_RUN,
) -> list[Event]:
    """
    Collapse consecutive same-class positive windows into events.

    Runs shorter than `min_run` are isolated flickers; runs longer than `max_run`
    are sustained motion, not a gesture. Both are discarded.
    """
    events: list[Event] = []
    i = 0
    while i < len(predictions):
        label = predictions[i]
        # Only the gesture classes fire. `motion` is a real prediction -- the
        # wearer is moving -- but it is not a thing the ring reports, so it is
        # skipped here exactly like `none`. Testing `!= "none"` would make every
        # wave an event.
        if label not in GESTURE_LABELS:
            i += 1
            continue
        j = i
        while j + 1 < len(predictions) and predictions[j + 1] == label:
            j += 1
        run = j - i + 1
        if min_run <= run <= max_run:
            events.append(Event(label=label, start_s=starts[i], end_s=starts[j], run_length=run))
        i = j + 1
    return events


def score(
    events: list[Event],
    truth: list[tuple[float, str]],
    hours: float,
    tolerance_s: float = MATCH_TOLERANCE_S,
) -> dict:
    """
    Match detections to labelled gestures, greedily and one-to-one.

    Returns per-class precision/recall/F1 plus false positives per hour, which
    is the number that decides whether the thing is usable: a classifier that
    fires while you type poisons every downstream label.
    """
    unmatched = list(truth)
    tp: dict[str, int] = {}
    fp: dict[str, int] = {}

    for ev in sorted(events, key=lambda e: e.centre_s):
        hit = None
        for cand in unmatched:
            t, label = cand
            if abs(ev.centre_s - t) <= tolerance_s and label == ev.label:
                hit = cand
                break
        if hit is not None:
            unmatched.remove(hit)
            tp[ev.label] = tp.get(ev.label, 0) + 1
        else:
            fp[ev.label] = fp.get(ev.label, 0) + 1

    classes = sorted({lab for _, lab in truth} | set(tp) | set(fp))
    per_class = {}
    for c in classes:
        t = tp.get(c, 0)
        f = fp.get(c, 0)
        missed = sum(1 for _, lab in unmatched if lab == c)
        precision = t / (t + f) if (t + f) else 0.0
        recall = t / (t + missed) if (t + missed) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[c] = {"tp": t, "fp": f, "fn": missed,
                        "precision": precision, "recall": recall, "f1": f1}

    total_fp = sum(fp.values())
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(per_class) if per_class else 0.0

    return {
        "per_class": per_class,
        "false_positives": total_fp,
        "fp_per_hour": total_fp / hours if hours > 0 else float("inf"),
        "macro_f1": macro_f1,
        "hours": hours,
    }
