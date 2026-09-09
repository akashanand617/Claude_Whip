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
from dataclasses import dataclass, asdict, field
from pathlib import Path

CLASSES = ("flag", "approve")

DIRECTIONS = ("flexion", "extension", "ulnar", "radial")
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
# `approve` IS two flicks, so two `flag`s inside one 2.0 s window look exactly
# like an `approve` and no label for that window is correct. The gap therefore
# has to guarantee that no window ever holds two gestures: gesture-end to next
# gesture-start >= the window length. With gestures reaching 1.4 s and a 2 s
# countdown, 2.5 s of settle clears it.
#
# Randomised rather than fixed: a constant gap makes "quiet, then motion"
# correlate with the label, which is the windup leak in another form.
MIN_GAP_S = 2.5
MAX_GAP_S = 4.5


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
        """The instruction, ordered so the class is heard first and last."""
        kind = "SINGLE" if self.label == "flag" else "DOUBLE"
        return f"{kind}  |  {self.amplitude}, {self.direction}, {self.windup} windup, {self.posture}, {self.tempo}"


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
    data = json.loads(Path(path).read_text())
    marks = data.pop("marks", [])
    notes = SessionNotes(**data)
    notes.marks = marks
    return notes
