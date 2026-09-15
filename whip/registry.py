"""
The gesture vocabulary: the one place that says what gestures exist.

Everything downstream -- labelling, the model's class count, event detection, the
live router, the frontend's probability bars -- reads its class list from here or
from a checkpoint that was built from here. Add a gesture in this file (or in
`data/gestures.json`) and record data for it; nothing else needs editing.

Two kinds of gesture, because they are detected differently:

**impulsive** -- a brief event: flick, double flick, snap, double snap. Cued at a
point in time and labelled `cue_at .. cue_at + duration_s`. Detected with a run
*band*: a real one fires ~5-8 consecutive windows, so a run shorter than
`min_run` is noise and one longer than `max_run` is sustained motion, not a
gesture. This is the debounce logic that already existed for flicks.

**sustained** -- an ongoing motion: waving, clapping. Cued as a *span*
(`cue_at .. until`) and labelled across it. The band is wrong here: a three-second
wave fires 15+ windows, and `max_run` exists precisely to *reject* that, so a
sustained gesture with a max would be literally unfirable. Instead it fires once
its run passes `min_run`, then a `refractory_s` window suppresses re-firing so one
long wave is one event, not ten.

**Direction: split classes or a head?** Both exist and both are measured.
`split_by_direction` trains `flick_up` / `flick_down` / ... as separate classes;
the direction head (see `whip/model.py`) predicts direction from a shared trunk.
Splitting costs windows per class but makes each class more homogeneous; the
head shares data but was measured to cost ~10 points of recall at 264 gestures.
Either way the split is invisible downstream: probabilities are summed back
into the gesture before thresholding and debouncing, and events carry direction
as an attribute, so `flick:up` routes the same regardless of which mechanism
produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Windows arrive gravity-removed and in g. A gesture reaches ~4.5 g; this is the
# measured span of a real gesture in seconds, used to place impulsive labels.
DEFAULT_DURATION_S = 1.2

# Impulsive default band, unchanged from when flick/approve were the only classes.
DEFAULT_MIN_RUN = 3
DEFAULT_MAX_RUN = 14

NONE_LABEL = "none"


@dataclass(frozen=True)
class GestureSpec:
    """One gesture: how it is cued, labelled, and turned into an event."""

    name: str
    kind: str  # "impulsive" | "sustained"
    aliases: tuple[str, ...] = ()
    duration_s: float = DEFAULT_DURATION_S
    min_run: int = DEFAULT_MIN_RUN
    # None means "no upper bound", which is what a sustained gesture needs.
    max_run: int | None = DEFAULT_MAX_RUN
    # Seconds to suppress re-firing after an event. 0 for impulsive (the band
    # already prevents double-counting); non-zero for sustained.
    refractory_s: float = 0.0
    # Train one class per direction (flick_up, flick_down, ...) instead of one
    # class plus a direction head. Costs windows per class, but each class is
    # more homogeneous -- which effect wins is measured, not argued. Purely a
    # training-time choice: the engine collapses sub-classes back to
    # (gesture, direction) before debouncing, so events and app config are
    # unchanged and the flag is reversible.
    split_by_direction: bool = False

    def __post_init__(self):
        if self.kind not in ("impulsive", "sustained"):
            raise ValueError(f"{self.name}: kind must be impulsive or sustained, not {self.kind!r}")
        if self.kind == "sustained" and self.max_run is not None:
            raise ValueError(
                f"{self.name}: a sustained gesture must have max_run=None; a bounded run "
                "would make it unfirable, since sustained motion is exactly what a max rejects"
            )
        if self.kind == "sustained" and self.min_run < 2:
            raise ValueError(f"{self.name}: sustained gestures need min_run >= 2")


# The declared vocabulary. Classes only reach the model once data exists for
# them; this list is what *may* exist, not what does.
#
# Legacy on-disk names: the first two sessions labelled gestures `flag` and
# `approve`, and the negative session cued spans as `waving` / `snapping` /
# `clapping`. Those map in via aliases so old captures need no rewriting.
DEFAULT_GESTURES: tuple[GestureSpec, ...] = (
    # split_by_direction defaults OFF, measured: on the held-out session the
    # split cost 6-9 recall points (2 seeds) and every up/down flick came out
    # as left/right -- a clean permutation, i.e. the ring sat rotated on the
    # finger between sessions. Direction learned from one placement does not
    # transfer to another; no class design fixes a rotated frame. The
    # mechanism stays for when placement is calibrated or recorded across.
    GestureSpec("flick", "impulsive", aliases=("flag",)),
    GestureSpec("double_flick", "impulsive", aliases=("approve",)),
    # "snapping" was cued as a 20 s span in the adversarial negative session.
    # Promoting it to a class converts a hard negative into a positive -- which
    # is exactly right here: instead of hoping the model treats snaps as `none`,
    # it is forced to learn the snap/flick boundary explicitly, and the app
    # simply does not map `snap` to any action unless asked to.
    GestureSpec("snap", "impulsive", aliases=("snapping",)),
    GestureSpec("double_snap", "impulsive"),
    GestureSpec("wave", "sustained", aliases=("waving",), min_run=3, max_run=None, refractory_s=2.0),
    GestureSpec("clap", "sustained", aliases=("clapping",), min_run=2, max_run=None, refractory_s=1.5),
)

DIRECTIONS = ("none", "up", "down", "left", "right")
DIRECTION_INDEX = {d: i for i, d in enumerate(DIRECTIONS)}
SPLIT_DIRECTIONS = ("up", "down", "left", "right")


def class_name(gesture: str, direction: str | None, split: bool) -> str:
    """The training label for a gesture window: `flick_up` if split, else `flick`."""
    if split and direction in SPLIT_DIRECTIONS:
        return f"{gesture}_{direction}"
    return gesture


@dataclass
class Registry:
    """The vocabulary as a queryable object."""

    gestures: tuple[GestureSpec, ...] = field(default_factory=lambda: DEFAULT_GESTURES)

    def __post_init__(self):
        self._by_name: dict[str, GestureSpec] = {}
        for spec in self.gestures:
            for key in (spec.name, *spec.aliases):
                if key in self._by_name and self._by_name[key].name != spec.name:
                    raise ValueError(f"duplicate gesture name/alias: {key!r}")
                self._by_name[key] = spec

    def resolve(self, name: str) -> GestureSpec | None:
        """Canonical spec for a name or a legacy alias; None if unknown."""
        return self._by_name.get(name)

    def canonical(self, name: str) -> str | None:
        spec = self.resolve(name)
        return spec.name if spec else None

    @property
    def names(self) -> list[str]:
        return [g.name for g in self.gestures]

    def training_names(self) -> list[str]:
        """Every label training may emit, in registry order, sub-classes expanded."""
        out = []
        for g in self.gestures:
            if g.split_by_direction:
                out.extend(f"{g.name}_{d}" for d in SPLIT_DIRECTIONS)
            else:
                out.append(g.name)
        return out

    def collapse(self, label: str) -> tuple[str, str]:
        """
        `flick_up` -> ("flick", "up"); anything else -> (label, "none").

        The one place a directional sub-class turns back into a gesture. Events,
        scoring truth and app mappings all speak in collapsed names.
        """
        for g in self.gestures:
            if g.split_by_direction:
                for d in SPLIT_DIRECTIONS:
                    if label == f"{g.name}_{d}":
                        return g.name, d
        return label, "none"

    def collapsed_names(self, labels) -> list[str]:
        """The vocabulary after collapsing sub-classes, order preserved, no dupes."""
        out: list[str] = []
        for name in labels:
            base, _ = self.collapse(str(name))
            if base not in out:
                out.append(base)
        return out

    def collapse_probabilities(self, probs, labels):
        """
        Sum sub-class probability mass into its gesture: (N, K) -> (N, K').

        `flick_up` at 0.3 and `flick_left` at 0.3 is a 0.6 flick -- which is
        how the direction split becomes invisible to thresholding and debouncing.
        The winning sub-class within a run is what reports the direction.
        """
        import numpy as np

        probs = np.asarray(probs)
        collapsed = self.collapsed_names(labels)
        out = np.zeros((probs.shape[0], len(collapsed)), dtype=probs.dtype)
        for k, name in enumerate(labels):
            base, _ = self.collapse(str(name))
            out[:, collapsed.index(base)] += probs[:, k]
        return out

    def labels_for(self, present: set[str]) -> list[str]:
        """
        The label list for a dataset, `none` first then declared classes that
        actually have data, in registry order. Classes materialise from data:
        declaring a gesture is not the same as having recorded one.
        """
        return [NONE_LABEL] + [n for n in self.training_names() if n in present]

    def policies(self, labels) -> dict:
        """RunPolicy per (collapsed) gesture label, for `events.detect` / `RunTracker`."""
        from whip.events import RunPolicy

        out = {}
        for name in labels:
            base, _ = self.collapse(str(name))
            spec = self.resolve(base)
            if spec is not None:
                out[spec.name] = RunPolicy(spec.min_run, spec.max_run, spec.refractory_s)
        return out



def load_registry(path: Path | None = None) -> Registry:
    """
    The default vocabulary, or an override from `data/gestures.json` if present.

    The override file is a list of gesture dicts with the GestureSpec fields, so a
    user can add or retune gestures without touching code. Malformed entries fail
    loudly rather than silently dropping a gesture the data expects.
    """
    path = path or Path("data/gestures.json")
    if not path.exists():
        return Registry()
    raw = json.loads(path.read_text())
    specs = tuple(
        GestureSpec(
            name=g["name"], kind=g["kind"], aliases=tuple(g.get("aliases", ())),
            duration_s=g.get("duration_s", DEFAULT_DURATION_S),
            min_run=g.get("min_run", DEFAULT_MIN_RUN),
            max_run=g.get("max_run", DEFAULT_MAX_RUN) if g["kind"] == "impulsive" else None,
            refractory_s=g.get("refractory_s", 0.0),
            split_by_direction=bool(g.get("split_by_direction", False)),
        )
        for g in raw
    )
    return Registry(specs)
