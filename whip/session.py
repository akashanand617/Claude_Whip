"""
Gesture collection sessions: prompt schedules and on-disk format.

Two rules shape this file.

**Never pre-segment.** The capture is one continuous stream; gestures are marked
by timestamp in a sidecar. Window alignment, label coverage thresholds and event
boundaries are all decisions we have already changed once, and every one of them
can be revisited against a stored raw stream but not against pre-cut clips.

**Randomise the factors, do not cross them.** Two classes x four directions x
three amplitudes x three windups x five postures is 360 cells. Marginal balance
is what decorrelates a factor from the label, and randomisation gives that at a
fraction of the cost. See docs/COLLECTION.md.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path

CLASSES = ("flag", "approve")

DIRECTIONS = ("up", "down", "left", "right")
AMPLITUDES = ("soft", "normal", "hard")
WINDUPS = ("none", "minimal", "deliberate")
POSTURES = ("on keyboard", "on mouse", "raised", "flat on desk", "at side")
TEMPOS = ("brisk", "natural", "deliberate")

# A gesture reaches 1.4 s and the analysis window is 2.0 s, so gestures closer
# than ~3.4 s cue-to-cue can both fall inside one window -- which then has no
# defined label. 3 s of quiet after a ~3 s countdown clears that comfortably.
#
# The gap is randomised between these bounds rather than fixed: a constant gap
# makes "quiet, then motion" correlate with the label, which is the windup leak
# in another form. Real gestures emerge from ongoing activity, not a metronome.
# What the pacing must guarantee: a *positive* window for one gesture must never
# contain the next one. `approve` is two flicks, so two `flag`s in one window
# would look exactly like an `approve` and no label for it would be correct.
#
#   a positive window holds >= MIN_POSITIVE_COVERAGE of the gesture, so the
#   latest one starts (1 - 0.70) * 1.4 s = 0.42 s into it, and ends 2.0 s later
#   -> the next gesture must begin at least 2.42 s after this one
#
# An earlier version required 3.4 s, which was sized so that *negative* windows
# could also sit cleanly in the quiet between gestures. That is not needed:
# prompted sessions exist to produce positives, negatives come from ambient
# wear, and windows straddling the gap are dropped as ambiguous anyway.
#
# Randomised rather than fixed: a constant gap makes "quiet, then motion"
# correlate with the label, which is the windup leak in another form.
MIN_CUE_TO_CUE_S = 2.5

MIN_GAP_S = 0.5
MAX_GAP_S = 2.0


@dataclass(frozen=True)
class Prompt:
    """One cued gesture: what to do, and when it was cued."""

    index: int
    label: str
    direction: str
    amplitude: str
    windup: str
    posture: str
    tempo: str
    cue_at: float = 0.0

    def spoken(self) -> str:
        """
        The instruction. Class first and in caps because it is the only part
        that must not be got wrong -- the rest is variation, and a factor
        slightly off is harmless since the point is decorrelating them from the
        label, not teaching them.
        """
        legacy = {"flag": "SINGLE", "approve": "DOUBLE"}
        kind = legacy.get(self.label, self.label.upper().replace("_", " "))
        where = ("" if self.posture in ("", "as you are") or self.posture.startswith("block:")
                 else f"   [{self.posture.upper()}]")
        if self.direction == "any":
            return f"{kind}  |  {self.amplitude}{where}"
        return f"{kind}  |  {self.amplitude}, {self.direction}{where}"


def build_structured_schedule(
    per_class_per_cell: dict[str, int] | None = None,
    directions: tuple[str, ...] = DIRECTIONS,
    seed: int | None = None,
) -> list[Prompt]:
    """
    A blocked design: work through one direction at a time, with a fixed number
    of each amplitude, and both classes interleaved inside every block.

    Blocking by direction is deliberate and safe. The confound that matters is
    anything correlating with the *label*, and direction is not the label -- so
    grouping by it costs nothing, while making the session far easier to execute
    than a fully randomised draw.

    Interleaving the classes inside each block is the part that is not optional.
    Doing 25 `flag` then 25 `approve` would let fatigue and ring settling
    separate the classes for free, which is the session-oracle problem in
    miniature.

    Windup and posture are not varied here. That costs generalisation to
    postures you did not train in; it does not create a confound, because both
    classes share whatever posture you happen to use.
    """
    per_class_per_cell = per_class_per_cell or {"soft": 10, "hard": 15}
    rng = random.Random(seed)

    prompts: list[Prompt] = []
    index = 0
    for direction in directions:
        block: list[tuple[str, str]] = []
        for amplitude, n in per_class_per_cell.items():
            for _ in range(n):
                block.append(("flag", amplitude))
                block.append(("approve", amplitude))

        # Shuffle amplitudes within the block but keep classes alternating, so
        # neither amplitude nor position in the block predicts the class.
        rng.shuffle(block)
        fixed: list[tuple[str, str]] = []
        pending = {"flag": [b for b in block if b[0] == "flag"],
                   "approve": [b for b in block if b[0] == "approve"]}
        want = "flag" if rng.random() < 0.5 else "approve"
        while pending["flag"] or pending["approve"]:
            other = "approve" if want == "flag" else "flag"
            src = pending[want] or pending[other]
            fixed.append(src.pop())
            want = other if pending[other] else want

        for label, amplitude in fixed:
            prompts.append(Prompt(
                index=index, label=label, direction=direction, amplitude=amplitude,
                windup="natural", posture="as you are", tempo=rng.choice(TEMPOS),
            ))
            index += 1

    return prompts


def build_blocked_schedule(gestures: list[str], per_gesture: int, seed: int | None = None) -> list[Prompt]:
    """
    Every gesture in its own block -- all the snaps, then all the double
    snaps, ... -- so the wearer settles into one motion and does it `per_gesture`
    times. The opposite of `build_gesture_schedule`'s interleaving, chosen
    when speed of recording matters more than decorrelating drift from the
    label (2026-09-16). Amplitude alternates soft/hard within a block, tempo
    fixed. The block name goes on the prompt's `posture` field so the
    collector announces it and pauses, exactly as it does for a hand posture.
    """
    rng = random.Random(seed)
    out: list[Prompt] = []
    for g in gestures:
        amps = ["soft", "hard"] * (per_gesture // 2) + (["hard"] if per_gesture % 2 else [])
        rng.shuffle(amps)
        for amp in amps:
            out.append(Prompt(index=len(out), label=g, direction="any", amplitude=amp, windup="natural",
                              posture=f"block: {g}", tempo="natural"))
    return out


def build_gesture_schedule(
    gestures: list[str], count: int, seed: int | None = None
) -> list[Prompt]:
    """
    An interleaved prompt schedule over arbitrary registry gestures.

    This is how data for a new gesture class gets made -- e.g.
    `--gestures snap,double_snap --prompts 100` -- with the same discipline the
    flick sessions used: classes interleaved in shuffled groups so session
    drift cannot correlate with the label, amplitude varied, direction marked
    "any" because a snap has no meaningful direction to cue.
    """
    rng = random.Random(seed)
    labels: list[str] = []
    while len(labels) < count:
        group = list(gestures)
        rng.shuffle(group)
        labels.extend(group)
    labels = labels[:count]

    return [
        Prompt(index=i, label=label, direction="any",
               amplitude=rng.choice(("soft", "hard")), windup="natural",
               posture="as you are", tempo=rng.choice(TEMPOS))
        for i, label in enumerate(labels)
    ]


def build_schedule(count: int, seed: int | None = None) -> list[Prompt]:
    """
    Draw a randomised, class-balanced prompt schedule.

    Classes alternate in shuffled pairs rather than being drawn independently:
    that guarantees interleaving (no accidental run of twelve `flag`s, which
    would let session drift correlate with the label) while keeping every other
    factor freely random.
    """
    rng = random.Random(seed)

    labels: list[str] = []
    for _ in range((count + 1) // 2):
        pair = list(CLASSES)
        rng.shuffle(pair)
        labels.extend(pair)
    labels = labels[:count]

    return [
        Prompt(
            index=i,
            label=label,
            direction=rng.choice(DIRECTIONS),
            amplitude=rng.choice(AMPLITUDES),
            windup=rng.choice(WINDUPS),
            posture=rng.choice(POSTURES),
            tempo=rng.choice(TEMPOS),
        )
        for i, label in enumerate(labels)
    ]


@dataclass
class SessionNotes:
    """Everything about a session that is not in the signal itself."""

    session_id: str
    started_wall: float
    kind: str  # "prompted" | "naturalistic" | "negative" | "probe"
    hand: str
    ring_position: str
    note: str = ""
    marks: list[dict] = field(default_factory=list)

    def add_mark(self, prompt: Prompt, cue_at: float) -> None:
        entry = asdict(prompt)
        entry["cue_at"] = cue_at
        self.marks.append(entry)

    def add_cue(self, motion: str, cue_at: float, until: float) -> None:
        """
        Mark a stretch of a negative session as a named motion.

        The label stays `none` -- these are all negatives. The point is
        attribution: knowing that waving produced four flick-like events while
        chin-on-hand produced none tells you which habit actually threatens the
        false-positive budget, which a single undifferentiated negative session
        cannot.
        """
        self.marks.append({"label": "none", "motion": motion,
                           "cue_at": cue_at, "until": until})

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))


def load_notes(path: Path) -> SessionNotes:
    """
    Read a notes file, tolerating fields this version does not know about.

    Notes accumulate metadata over a project's life -- recovery records,
    annotations, whatever a later tool adds. Refusing to load because of an
    unrecognised key makes old sessions unreadable by new code and new sessions
    unreadable by old, for no benefit.
    """
    data = json.loads(Path(path).read_text())
    marks = data.pop("marks", [])
    known = {f.name for f in fields(SessionNotes)} - {"marks"}
    notes = SessionNotes(**{k: v for k, v in data.items() if k in known})
    notes.marks = marks
    return notes


def build_fill_schedule(shortfall: dict[str, int], seed: int | None = None) -> list[Prompt]:
    """
    Exactly the gestures a corpus is short of, from `audit.shortfall` --
    `{"flick_left": 10, "double_flick_down": 6, ...}` -- interleaved so the
    label never runs in a streak, half soft and half hard within each class.

    Keys are `<gesture>_<direction>` for directed classes and bare gesture
    names otherwise. Tempo is fixed at "natural": the audit measured the tempo
    words changing nothing, and a double is two quick taps by definition.
    """
    rng = random.Random(seed)
    items: list[tuple[str, str, str]] = []
    for key, n in shortfall.items():
        label, direction = key, "any"
        for d in DIRECTIONS:
            if key.endswith("_" + d):
                label, direction = key[: -len(d) - 1], d
                break
        amps = ["soft", "hard"] * (n // 2) + (["soft"] if n % 2 else [])
        rng.shuffle(amps)
        items += [(label, direction, amp) for amp in amps]
    # Interleave: repeatedly draw from the class with the most remaining, ties
    # broken at random, so no class is ever cued twice in a row while another
    # is still owed.
    remaining: dict[tuple[str, str], list[str]] = {}
    for label, direction, amp in items:
        remaining.setdefault((label, direction), []).append(amp)
    order: list[tuple[str, str, str]] = []
    last = None
    while remaining:
        keys = sorted(remaining, key=lambda k: (-len(remaining[k]), rng.random()))
        pick = next((k for k in keys if k != last), keys[0])
        amp = remaining[pick].pop()
        if not remaining[pick]:
            del remaining[pick]
        order.append((pick[0], pick[1], amp))
        last = pick
    return [Prompt(index=i, label=label, direction=direction, amplitude=amp, windup="natural",
                   posture="as you are", tempo="natural") for i, (label, direction, amp) in enumerate(order)]


# Hand orientations for the posture x direction matrix. "as you are" is the
# ordinary schedules' value and is never spoken.
MATRIX_POSTURES = ("palm down", "palm up", "palm left", "palm right")


def build_matrix_schedule(
    gestures: tuple[str, ...] = ("flick",),
    postures: tuple[str, ...] = MATRIX_POSTURES,
    directions: tuple[str, ...] = DIRECTIONS,
    reps: int = 1,
    amplitude: str = "hard",
    seed: int | None = None,
) -> list[Prompt]:
    """
    Every posture x direction cell, `reps` times each, per gesture -- the
    factorial that separates which way the hand FACES from which way it
    FLICKED (2026-09-16). Grouped by posture so the wearer reorients the hand
    once per block, with directions shuffled inside each block; block order
    is shuffled too.
    """
    rng = random.Random(seed)
    blocks = list(postures)
    rng.shuffle(blocks)
    out: list[Prompt] = []
    for posture in blocks:
        cells = [(g, d) for g in gestures for d in directions for _ in range(reps)]
        rng.shuffle(cells)
        for g, d in cells:
            out.append(Prompt(index=len(out), label=g, direction=d, amplitude=amplitude,
                              windup="natural", posture=posture, tempo="natural"))
    return out
