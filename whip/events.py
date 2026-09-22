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

import math
from dataclasses import dataclass, field

STRIDE_S = 0.24   # 6 samples at 25 Hz
WINDOW_S = 2.0    # 50 samples at 25 Hz
WINDOW_SAMPLES = 50
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
    # Burst-anchored events know exactly when the motion began (`at_s`, the
    # burst onset) and when the decision was made (`judged_s`, stream clock),
    # so latency is a measured number rather than a design estimate. Run-based
    # events leave both None and fall back to the window arithmetic below.
    at_s: float | None = None
    judged_s: float | None = None
    confidence: float = 0.0
    direction: str = "none"

    @property
    def centre_s(self) -> float:
        """
        Time of the detected motion.

        Burst events: the onset. Run events: the centre of the run's windows,
        not of the window indices -- window timestamps are *start* times, so a
        window at T covers T..T+2.0 s. Averaging start times alone puts the
        event a full second early -- more than the matching tolerance, so
        every detection missed and event F1 read zero while the model was
        working.
        """
        if self.at_s is not None:
            return self.at_s
        return (self.start_s + self.end_s) / 2 + WINDOW_S / 2

    @property
    def latency_s(self) -> float | None:
        """Decision time minus motion onset, when both are known."""
        if self.at_s is None or self.judged_s is None:
            return None
        return self.judged_s - self.at_s


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


# ------------------------------------------------------------ burst-anchored
#
# Decoding gestures as runs of same-label windows has three failure modes,
# all seen live on 2026-09-21: two gestures of the same class in succession
# make ONE run (one event, or none past `MAX_RUN`); a different gesture whose
# windows abut a fired run starts inside its dead time and is dropped; and
# continuous motion -- a wave, a shaken hand -- is chopped into whatever the
# model calls each stretch of it. The tracker never knew where one movement
# ended and the next began, because it only saw labels.
#
# The signal itself says. Impulsive magnitude (|a - gravity|) crosses 1 g at
# the start of every gesture in the corpus and stays below it between
# gestures; a double flick's inter-stroke gap (0.20-0.50 s by definition) is
# shorter than the quiet a wearer leaves between gestures. So: segment the
# stream into BURSTS (above ONSET_G, merged across gaps under QUIET_S), and
# decode one event per burst from the windows that contain that burst and
# no other. Same-class succession counts; a gesture right after another is
# judged on windows that start after the first one ended; a burst longer
# than a window is not impulsive and is left to the sustained classes.

ONSET_G = 1.0            # impulsive magnitude that opens a burst (the audit's stroke floor)
QUIET_S = 0.6            # this long below ONSET_G closes a burst; a double's gap is at most 0.5 s
MAX_IMPULSIVE_S = 2.0    # a burst longer than a window is sustained motion, not a gesture...
SPLIT_QUIET_S = 0.35     # ...unless it holds a lull this long below ONSET_G: then it is two gestures that
                         # came too fast for QUIET_S (live: consecutive flicks 0.40-0.56 s apart, both lost).
                         # Only bursts over MAX_IMPULSIVE_S are split, so a double clap (internal lull up to
                         # 0.5 s, whole burst under 1.3 s) is never cut in two.
CORE_S = 1.3             # the part of a burst a vote window must contain (two strokes and a recoil)
MARGIN_S = 0.08          # two samples of context either side of the core
MIN_VOTES = 2            # agreeing windows containing the core; the ablation put min_run 2 at zero ambient cost
MIN_BLIP_PEAK_G = 1.5    # a single sample above ONSET_G but under this is a blip, not a movement (the audit's WEAK floor)
GRAVITY_SAMPLES = 25     # causal moving average for the impulsive magnitude, 1 s


def impulsive_magnitude(stream_g: "np.ndarray") -> "np.ndarray":
    """
    |a - gravity| per sample for a (3, N) stream in g, gravity being the
    causal 1 s moving average. Computed as the plain mean of the last
    GRAVITY_SAMPLES samples, in the same order the live engine averages its
    buffer, so offline bursts are bit-identical to live bursts.
    """
    import numpy as np
    x = np.asarray(stream_g, dtype="float64")
    n = x.shape[1]
    ma = np.empty_like(x)
    for i in range(n):
        ma[:, i] = x[:, max(0, i - GRAVITY_SAMPLES + 1):i + 1].mean(axis=1)
    return np.linalg.norm(x - ma, axis=0)


@dataclass
class Burst:
    on_s: float
    off_s: float | None = None          # last sample above ONSET_G so far
    closed_s: float | None = None       # stream time the burst was closed (off + QUIET_S)
    votes: list = field(default_factory=list)   # (start_s, label, confidence, direction)
    outcome: str | None = None          # event label, or why not: "too_long" | "no_consensus" | "no_votes"
    judged_s: float | None = None
    peak_g: float = 0.0
    n_above: int = 0                    # samples at or above ONSET_G
    lull: tuple[float, float, float] = (0.0, 0.0, 0.0)   # longest internal stretch below ONSET_G: (length, from, to)

    @property
    def duration_s(self) -> float:
        return (self.off_s if self.off_s is not None else self.on_s) - self.on_s

    def as_dict(self) -> dict:
        return {"on_s": round(self.on_s, 3), "off_s": round(self.off_s, 3) if self.off_s is not None else None,
                "duration_s": round(self.duration_s, 3), "outcome": self.outcome, "peak_g": round(self.peak_g, 2),
                "votes": len(self.votes), "judged_s": round(self.judged_s, 3) if self.judged_s is not None else None}


@dataclass
class BurstTracker:
    """
    One event per movement. Feed every sample's impulsive magnitude
    (`feed_sample`) and every scored window (`feed_window`); events come back
    from either call as soon as they can be decided, `finish()` flushes.

    Impulsive gestures are decided per burst from its vote windows: windows
    that start after the previous burst ended, start before the onset, and
    reach past the burst's core. The winner is the most voted impulsive
    label (ties by confidence) with at least MIN_VOTES; a burst longer than
    MAX_IMPULSIVE_S gets no impulsive event. Sustained gestures (wave) keep
    the run policy from `RunTracker`, fed only their own labels, so a long
    burst can still be a wave and nothing else.

    Decision time: a burst is judged once it is closed AND a window starting
    after its last vote window has arrived (all votes are in), or at finish.
    Votes are gathered at that moment from the recent windows, because a
    burst's extent is only known once it has closed.
    """

    policies: dict[str, RunPolicy] = field(default_factory=dict)
    default: RunPolicy = DEFAULT_POLICY
    onset_g: float = ONSET_G
    quiet_s: float = QUIET_S
    min_votes: int = MIN_VOTES

    bursts: list[Burst] = field(default_factory=list)
    _open: Burst | None = None
    _last_above_s: float | None = None
    _pending: list[Burst] = field(default_factory=list)     # closed, awaiting their last vote window
    _windows: list[tuple[float, str, float, str]] = field(default_factory=list)   # recent scored windows
    _last_window_start: float = float("-inf")
    _sustained: RunTracker | None = None
    _last_t: float = float("-inf")

    KEEP_WINDOWS_S = 6.0

    def __post_init__(self):
        self._sustained = RunTracker(policies={k: v for k, v in self.policies.items() if v.sustained},
                                     default=self.default)

    def policy_for(self, label: str) -> RunPolicy:
        return self.policies.get(label, self.default)

    # ---------------------------------------------------------------- samples

    def feed_sample(self, t_s: float, mag_g: float) -> list[Event]:
        self._last_t = t_s
        if mag_g >= self.onset_g:
            if self._open is None:
                self._open = Burst(on_s=t_s, off_s=t_s)
            else:
                gap = t_s - self._open.off_s
                if gap > self._open.lull[0]:
                    self._open.lull = (gap, self._open.off_s, t_s)
                self._open.off_s = t_s
            self._open.peak_g = max(self._open.peak_g, mag_g)
            self._open.n_above += 1
            self._last_above_s = t_s
        elif self._open is not None and t_s - self._last_above_s >= self.quiet_s:
            b, self._open = self._open, None
            b.closed_s = t_s
            # A lone sample just over the floor is sensor chatter or a windup,
            # not a movement: it must neither be judged nor isolate the
            # gesture that follows it (live, a 1 g blip 0.7 s before a double
            # flick took that gesture's windows and fired in its place).
            if not (b.n_above == 1 and b.peak_g < MIN_BLIP_PEAK_G):
                for part in self._split(b):
                    self.bursts.append(part)
                    self._pending.append(part)
        return self._judge_ready(t_s)

    @staticmethod
    def _split(b: Burst) -> list[Burst]:
        """A too-long burst with a real lull inside is two gestures; cut it there, once."""
        if b.duration_s <= MAX_IMPULSIVE_S or b.lull[0] < SPLIT_QUIET_S:
            return [b]
        length, lo, hi = b.lull
        first = Burst(on_s=b.on_s, off_s=lo, closed_s=b.closed_s, peak_g=b.peak_g, n_above=b.n_above)
        second = Burst(on_s=hi, off_s=b.off_s, closed_s=b.closed_s, peak_g=b.peak_g, n_above=b.n_above)
        return [first, second]

    # ---------------------------------------------------------------- windows

    def feed_window(self, start_s: float, label: str, confidence: float = 1.0,
                    direction: str = "none") -> list[Event]:
        out: list[Event] = []
        sustained = label != NONE_LABEL and self.policy_for(label).sustained
        if label != NONE_LABEL and not sustained:
            self._windows.append((start_s, label, float(confidence), direction))
        while self._windows and self._windows[0][0] < start_s - self.KEEP_WINDOWS_S:
            self._windows.pop(0)
        # The sustained tracker sees the same label stream the run tracker
        # did (impulsive labels as `none`), so a wave still fires at min_run
        # and a label change still breaks its run.
        ev = self._sustained.feed(label if sustained else NONE_LABEL, start_s)
        if ev is not None:
            out.append(ev)
        self._last_window_start = start_s
        out.extend(self._judge_ready(max(self._last_t, start_s + WINDOW_S)))
        return out

    def finish(self) -> list[Event]:
        out: list[Event] = []
        if self._open is not None:
            self._open.closed_s = self._last_t
            self.bursts.append(self._open); self._pending.append(self._open); self._open = None
        for b in list(self._pending):
            ev = self._judge(b, self._last_t)
            if ev is not None:
                out.append(ev)
        self._pending.clear()
        tail = self._sustained.finish()
        if tail is not None:
            out.append(tail)
        return out

    # ---------------------------------------------------------------- votes

    def _previous_off(self, b: Burst) -> float:
        prev = [x for x in self.bursts if x is not b and x.on_s < b.on_s]
        return prev[-1].off_s if prev else float("-inf")

    def _next_on(self, b: Burst) -> float:
        later = [x for x in self.bursts if x is not b and x.on_s > b.on_s]
        if self._open is not None and self._open is not b:
            later.append(self._open)
        return min(x.on_s for x in later) if later else float("inf")

    @staticmethod
    def _core_end(b: Burst) -> float:
        return min(b.off_s, b.on_s + CORE_S)

    def vote_windows(self, b: Burst) -> list[tuple[float, str, float, str]]:
        """
        Windows that contain this burst's core and NO other movement: they
        start after the previous burst ended and end before the next one
        begins. One movement per window is what "hold it isolated" means.
        When gestures come so fast that fewer than MIN_VOTES windows are
        clean on both sides, the windows may run into the NEXT movement's
        start (never back into the previous one's tail, which is what read
        as a double): a vote with some contamination beats no vote.
        """
        lo, hi = self._previous_off(b), self._next_on(b)
        mine = [w for w in self._windows
                if lo <= w[0] <= b.on_s - MARGIN_S and w[0] + WINDOW_S >= self._core_end(b) + MARGIN_S]
        clean = [w for w in mine if w[0] + WINDOW_S <= hi]
        return clean if len(clean) >= self.min_votes else mine

    def _judge_ready(self, now_s: float) -> list[Event]:
        out: list[Event] = []
        for b in list(self._pending):
            votes_in = (self._last_window_start > b.on_s - MARGIN_S
                        or now_s >= b.on_s - MARGIN_S + WINDOW_S + 2 * STRIDE_S)
            if votes_in or self._decided_early(b):
                ev = self._judge(b, now_s)
                self._pending.remove(b)
                if ev is not None:
                    out.append(ev)
        return out

    def _decided_early(self, b: Burst) -> bool:
        """
        The vote windows still to come cannot change the outcome: the leader
        is ahead of the runner-up by more than the number of windows left.
        For a snap or single flick this decides ~1 s after the onset instead
        of 2 s; a double flick's vote windows all arrive at the end anyway.
        """
        if b.duration_s > MAX_IMPULSIVE_S:
            return True
        if not math.isfinite(self._last_window_start):
            return False
        remaining = math.ceil(max(0.0, b.on_s - MARGIN_S - self._last_window_start) / STRIDE_S)
        votes = self.vote_windows(b)
        if len(votes) < self.min_votes:
            return False
        tally: dict[str, int] = {}
        for _, label, _, _ in votes:
            tally[label] = tally.get(label, 0) + 1
        ranked = sorted(tally.values(), reverse=True)
        runner = ranked[1] if len(ranked) > 1 else 0
        if ranked[0] > runner + remaining:
            return True
        # Three or more votes, all agreeing, on a burst that has already closed:
        # decided. Measured on the test part and two 20-cue live tests it
        # changes no outcome and brings the median decision from 1.56 s to
        # 1.40 s after onset.
        return b.closed_s is not None and len(votes) >= 3 and len(tally) == 1

    def _judge(self, b: Burst, now_s: float) -> Event | None:
        b.judged_s = now_s
        if b.duration_s > MAX_IMPULSIVE_S:
            b.outcome = "too_long"
            return None
        b.votes = self.vote_windows(b)
        if not b.votes:
            b.outcome = "no_votes"
            return None
        tally: dict[str, list[float]] = {}
        for _, label, conf, _ in b.votes:
            tally.setdefault(label, []).append(conf)
        label, confs = max(tally.items(), key=lambda kv: (len(kv[1]), sum(kv[1])))
        if len(confs) < self.min_votes:
            b.outcome = "no_consensus"
            return None
        dirs = [d for _, l, _, d in b.votes if l == label and d != NONE_LABEL]
        direction = max(set(dirs), key=dirs.count) if dirs else NONE_LABEL
        b.outcome = label
        return Event(label, b.on_s, b.off_s, len(confs), at_s=b.on_s, judged_s=now_s,
                     confidence=float(sum(confs) / len(confs)), direction=direction)


def detect_bursts(
    predictions: list[str],
    starts: list[float],
    times: "np.ndarray",
    magnitudes: "np.ndarray",
    policies: dict[str, RunPolicy] | None = None,
    confidences: list[float] | None = None,
    directions: list[str] | None = None,
) -> list[Event]:
    """
    Batch burst-anchored decoding: the samples' (times, impulsive magnitudes)
    and the windows' (start, label[, confidence, direction]) interleaved in
    time order through one `BurstTracker`, exactly as the live engine feeds it.
    """
    import numpy as np
    tracker = BurstTracker(policies=policies or {})
    out: list[Event] = []
    confidences = confidences if confidences is not None else [1.0] * len(predictions)
    directions = directions if directions is not None else [NONE_LABEL] * len(predictions)
    times = np.asarray(times, dtype="float64")
    # A window is scored the moment its 50th sample arrives -- the sample at
    # index start+49, not the clock time start + 2.0 s -- exactly as live.
    due = np.searchsorted(times, np.asarray(starts, dtype="float64")) + WINDOW_SAMPLES - 1
    wi = 0
    for i, (t, m) in enumerate(zip(times, magnitudes)):
        while wi < len(starts) and due[wi] <= i:
            out.extend(tracker.feed_window(float(starts[wi]), predictions[wi], confidences[wi], directions[wi]))
            wi += 1
        out.extend(tracker.feed_sample(float(t), float(m)))
    while wi < len(starts):
        out.extend(tracker.feed_window(starts[wi], predictions[wi], confidences[wi], directions[wi]))
        wi += 1
    out.extend(tracker.finish())
    return sorted(out, key=lambda e: e.centre_s)
