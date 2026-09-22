"""
Turn per-window predictions into gesture events, and score them.

Window accuracy is not the deliverable and is actively misleading here. One
gesture spans ~6 overlapping windows, so window metrics count it six times; and
a single isolated negative window scored as a failure may never survive
debouncing to become a real false positive.

**Impulsive gestures need a band, not a floor.** A flick fires roughly 6-8
consecutive windows. Requiring `>= k consecutive` alone would make sustained
motion *more* likely to trigger, not less; the upper bound rejects it.

**Sustained gestures need the opposite.** A wave IS sustained motion -- the very
thing `max_run` rejects -- so a bounded band makes it unfirable by construction.
A sustained policy fires once its run passes `min_run`, stays silent for the
rest of that run, and a refractory period absorbs brief dips so one long wave is
one event rather than one per dip.

Both behaviours live in one incremental `RunTracker`, and the batch `detect()`
is a loop over it. That is deliberate: the realtime engine uses the same tracker
sample by sample, so live and offline cannot drift apart -- they are one
implementation, not two that started identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field

STRIDE_S = 0.24   # 6 samples at 25 Hz
WINDOW_S = 2.0    # 50 samples at 25 Hz
# Consecutive windows arrive one stride apart. A step longer than this is a
# hole in the stream, and a run does not continue across a hole.
MAX_RUN_STEP_S = 2 * STRIDE_S
# After an impulsive event fires, a run that STARTS within this of the fired
# run's end is its tail, not a new gesture: as a double flick's first stroke
# leaves the window the remaining windows hold one stroke and read as a
# single flick -- live, "double_flick up" was followed 1.1 s later by
# "flick up" (2026-09-21, 2 of 20 cues). The tail run starts ONE STRIDE after
# the fired run ends; a real next gesture in a blocked session starts about
# 1 s after, so the dead time is 0.5 s -- 1.0 s absorbed a genuine snap
# whose run began 0.97 s after the previous one's.
DEAD_TIME_S = 0.5

# The impulsive default band: a 1.2 s gesture inside a 2.0 s window at 0.24 s
# stride produces ~6 positive windows; sustained motion produces far more.
MIN_RUN = 3
MAX_RUN = 14

# How close a detection must be to a labelled gesture to count as finding it.
MATCH_TOLERANCE_S = 0.75

NONE_LABEL = "none"


@dataclass(frozen=True)
class RunPolicy:
    """How a run of same-class windows becomes (or fails to become) an event."""

    min_run: int = MIN_RUN
    max_run: int | None = MAX_RUN      # None = unbounded, for sustained gestures
    refractory_s: float = 0.0

    def __post_init__(self):
        # A sustained run fires mid-stream; a fresh run always has length 1, so
        # min_run >= 2 guarantees a fire can never coincide with the close of
        # the previous run inside one RunTracker.feed call.
        if self.max_run is None and self.min_run < 2:
            raise ValueError("a sustained policy needs min_run >= 2")

    @property
    def sustained(self) -> bool:
        return self.max_run is None


DEFAULT_POLICY = RunPolicy()


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


@dataclass
class RunTracker:
    """
    Incremental run-to-event logic, one prediction at a time.

    `feed(label, start)` returns an Event when one fires, else None. Call
    `finish()` after the last prediction: an impulsive run is only judged when it
    *ends* (its length is unknowable before that), so a run still open at the end
    of the stream is closed and judged there.

    Timing note for impulsive gestures: the event is emitted one stride after the
    run breaks, because that is the earliest its length -- and therefore whether
    it is inside the band -- is known. Sustained gestures fire mid-run at
    `min_run`, because waiting for a wave to end would mean a 20-second latency.
    """

    policies: dict[str, RunPolicy] = field(default_factory=dict)
    default: RunPolicy = DEFAULT_POLICY

    _label: str | None = None
    _starts: list[float] = field(default_factory=list)
    _judged_this_run: bool = False
    # Last time a fired run ended, per label. Refractory is measured from run
    # end, not from the fire: a dip in the middle of one wave breaks the run,
    # and measuring from the fire would let a long wave re-fire after its own
    # refractory while still in progress.
    _suppressed_until: dict[str, float] = field(default_factory=dict)
    # End of the last fired impulsive run + DEAD_TIME_S; impulsive runs
    # starting before this are absorbed as that event's tail.
    _dead_until: float = float("-inf")

    def policy_for(self, label: str) -> RunPolicy:
        return self.policies.get(label, self.default)

    def feed(self, label: str, start_s: float) -> Event | None:
        # A run is a sequence of CONSECUTIVE windows. A hole in the stream --
        # a BLE dropout live, or offline the windows of an excluded gesture --
        # ends the run just as a different label would. Without this, two
        # same-class gestures on either side of an excluded one fused into a
        # single 12-window run centred on the hole, and both read as misses.
        gap_closed = None
        if self._starts and start_s - self._starts[-1] > MAX_RUN_STEP_S:
            gap_closed = self._close_run(end_at=self._starts[-1] + STRIDE_S)
            # _close_run leaves no open run, so the branch below starts a
            # fresh one for this window. At most one event per feed still
            # holds: the fresh run has length 1 and cannot fire (sustained
            # policies need min_run >= 2), and the label-change close below
            # finds nothing open.
        if label != self._label:
            closed = self._close_run(end_at=start_s) or gap_closed
            self._label = label
            self._starts = [start_s]
            self._judged_this_run = False
            if closed is not None:
                # A close and a sustained fire cannot coincide: a fresh run has
                # length 1 and sustained policies require min_run >= 2 (enforced
                # in RunPolicy), so returning the closed event loses nothing.
                return closed
        else:
            self._starts.append(start_s)

        if self._label != NONE_LABEL and not self._judged_this_run:
            policy = self.policy_for(self._label)
            # Judged exactly once, at min_run. Re-evaluating on every later
            # window would let a run outlive its suppression and fire anyway --
            # a mid-wave dip would then split one wave into two events, which is
            # the exact failure the refractory exists to prevent. A run that is
            # suppressed at its judgement moment is *absorbed*: it never fires,
            # and on close it extends the suppression, so a long dip-riddled
            # wave stays one event however long it lasts.
            if policy.sustained and len(self._starts) == policy.min_run:
                self._judged_this_run = True
                if start_s >= self._suppressed_until.get(self._label, float("-inf")):
                    return Event(self._label, self._starts[0], start_s, len(self._starts))
        return None

    def finish(self) -> Event | None:
        """Close the stream: judge any still-open impulsive run."""
        end = self._starts[-1] + STRIDE_S if self._starts else 0.0
        return self._close_run(end_at=end)

    def _close_run(self, end_at: float) -> Event | None:
        label, starts, judged = self._label, self._starts, self._judged_this_run
        self._label, self._starts, self._judged_this_run = None, [], False
        if label is None or label == NONE_LABEL or not starts:
            return None

        policy = self.policy_for(label)
        if policy.sustained:
            if judged:
                # This run either fired or was absorbed into a previous event;
                # either way the refractory rolls forward from its end, so a
                # dip-riddled wave stays one event however long it lasts.
                self._suppressed_until[label] = end_at + policy.refractory_s
            return None

        run = len(starts)
        if starts[0] < self._dead_until:
            return None
        if policy.min_run <= run <= (policy.max_run or run):
            self._dead_until = end_at + DEAD_TIME_S
            return Event(label, starts[0], starts[-1], run)
        return None


def detect(
    predictions: list[str],
    starts: list[float],
    min_run: int = MIN_RUN,
    max_run: int | None = MAX_RUN,
    policies: dict[str, RunPolicy] | None = None,
) -> list[Event]:
    """
    Collapse per-window predictions into events.

    `policies` gives each label its own rule (from `registry.policies()`); labels
    without one use the (`min_run`, `max_run`) band, preserving the original
    behaviour for impulsive gestures. Any label other than `none` can fire.
    """
    tracker = RunTracker(policies=policies or {}, default=RunPolicy(min_run, max_run))
    events: list[Event] = []
    for label, start in zip(predictions, starts):
        event = tracker.feed(label, start)
        if event is not None:
            events.append(event)
    tail = tracker.finish()
    if tail is not None:
        events.append(tail)
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


def span_hits(events: list[Event], spans: list[tuple[float, float, str]]) -> list[bool]:
    """
    One boolean per cued span: did at least one matching event fire inside it?

    Event-recall F1 is only meaningful for impulsive gestures -- a 20 s wave is
    one cue but has no single "moment" to match against. For sustained gestures
    the honest question is per span: was the wave noticed at all.
    """
    hits = []
    for lo, hi, label in spans:
        hits.append(any(e.label == label and lo <= e.centre_s <= hi for e in events))
    return hits
