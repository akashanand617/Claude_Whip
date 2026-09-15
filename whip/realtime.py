"""
Live gesture detection: the recorded-capture pipeline, one notification at a time.

The chain is deliberately identical to the offline one -- decode, despike,
window at stride 6, centre and scale exactly as `dataset` does, derive the
checkpoint's channels, forward, threshold, debounce -- because two pipelines
that "started identical" always drift. Where a step could not be shared
verbatim it is shared structurally:

- the debouncer IS `events.RunTracker`, the same object batch `detect()` loops
  over, so live and offline event logic cannot disagree;
- the window maths reproduces `dataset.windows_from_session` line for line
  (mean removal per window, division by COUNTS_PER_G), and the parity test in
  tests/test_realtime.py runs a real recorded capture through both and demands
  the *same events*;
- despiking uses `despike.StreamingHampel`, whose one honest difference from the
  batch filter (a running rather than whole-trace MAD floor) is documented there
  and tested separately.

The BLE notification callback still does nothing but stamp and append -- the
design rule that protects arrival timing survives live mode. The engine is fed
from a drain loop, not from inside the callback.

Latency budget, so nobody is surprised: 3 samples of despike lag (120 ms) + up
to one stride to complete a window (240 ms) + min_run strides of debounce
(720 ms for impulsive) + one stride to close the run (240 ms) ~= 1.3 s from
gesture end to event. Sustained gestures fire mid-run and feel faster.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from whip import accel, despike, events, protocol
from whip.dataset import STRIDE_SAMPLES, WINDOW_SAMPLES
from whip.registry import Registry, load_registry

DEFAULT_CONFIG_PATH = Path("data/app_config.json")
EVENT_LOG_DIR = Path("data/live")

DEFAULT_THRESHOLD = 0.6


@dataclass(frozen=True)
class GestureEvent:
    """One detected gesture, with everything a consumer needs to act on it."""

    name: str
    direction: str
    t_s: float                 # centre of the motion, engine clock
    confidence: float          # mean winning-class probability over the run
    run_length: int

    def as_dict(self) -> dict:
        return {"name": self.name, "direction": self.direction, "t_s": round(self.t_s, 3),
                "confidence": round(self.confidence, 3), "run_length": self.run_length}


class Engine:
    """
    Feed it accelerometer payloads; it returns gesture events.

    `feed(t_s, payload)` takes one BLE notification and returns a list of
    `GestureEvent` (usually empty). `finish()` flushes the tail of the stream.

    The model, its labels, its channels and the direction names all come from
    the checkpoint -- the engine has no opinions about the vocabulary, so adding
    a gesture never means editing this file.
    """

    def __init__(self, model, provenance: dict, threshold: float = DEFAULT_THRESHOLD,
                 registry: Registry | None = None):
        import torch

        self._torch = torch
        self.model = model.eval()
        self.labels = [str(l) for l in provenance["labels"]]
        self.channels = tuple(provenance.get("channels", ("shape", "scale")))
        self.direction_names = [str(d) for d in provenance.get(
            "direction_names", ["none", "up", "down", "left", "right"])]
        self.threshold = threshold
        registry = registry or load_registry()
        self.tracker = events.RunTracker(policies=registry.policies(self.labels))
        self._despike = despike.StreamingHampel()
        self._samples: list[np.ndarray] = []       # despiked, in counts
        self._times: list[float] = []
        self._pending_times: list[float] = []      # awaiting their despiked sample
        self._since_last_window = 0
        # (start_s, winning probability, direction name) per emitted window --
        # kept for the run in progress so a fired event can report confidence
        # and direction aggregated over its windows, not just the last one.
        self._run_meta: list[tuple[float, float, str]] = []
        self._last_probs: np.ndarray | None = None

    @classmethod
    def from_checkpoint(cls, path: Path, threshold: float = DEFAULT_THRESHOLD,
                        registry: Registry | None = None) -> "Engine":
        from whip import model as gm

        model, provenance = gm.load(path)
        return cls(model, provenance, threshold=threshold, registry=registry)

    # ------------------------------------------------------------------ feed

    def feed(self, t_s: float, payload: bytes) -> list[GestureEvent]:
        """One BLE notification in, zero or more events out."""
        if len(payload) < 8 or payload[0] != protocol.CMD_RAW_SENSOR \
                or payload[1] != protocol.SUBTYPE_ACCEL:
            return []
        sample = accel.decode(payload)
        # The despiker lags by half a window, so an emitted sample is not THIS
        # notification -- it is one from ~120 ms ago. Timestamps queue up on the
        # way in and pair with samples on the way out, or every window start
        # (and therefore every event time) would be 120 ms late against offline.
        self._pending_times.append(t_s)
        out: list[GestureEvent] = []
        for filtered in self._despike.push((sample.x, sample.y, sample.z)):
            self._times.append(self._pending_times.pop(0))
            self._samples.append(filtered)
            out.extend(self._advance())
        return out

    def feed_sample(self, t_s: float, xyz) -> list[GestureEvent]:
        """
        Already-decoded, already-despiked samples, for the parity test.

        This entry point skips the streaming despiker so the parity test can
        prove the window/model/tracker chain bit-identical to offline against a
        batch-despiked recording, independent of the despiker's documented
        running-floor difference.
        """
        self._times.append(t_s)
        self._samples.append(np.asarray(xyz, dtype="float64"))
        return self._advance()

    def _advance(self) -> list[GestureEvent]:
        self._since_last_window += 1
        if len(self._samples) < WINDOW_SAMPLES:
            return []
        if len(self._samples) > WINDOW_SAMPLES:
            self._samples.pop(0)
            self._times.pop(0)
        # The first window fires as soon as 50 samples exist (the counter is
        # already past the stride); thereafter every 6th sample -- which makes
        # the emitted window sequence exactly offline's [0:50], [6:56], ...
        if self._since_last_window < STRIDE_SAMPLES:
            return []
        self._since_last_window = 0
        return self._classify_window()

    def _classify_window(self) -> list[GestureEvent]:
        window = np.stack(self._samples, axis=1)                     # (3, 50)
        centred = (window - window.mean(axis=1, keepdims=True)) / accel.COUNTS_PER_G
        from whip import model as gm

        x = gm.to_model_input(centred[None, ...], self.channels)
        torch = self._torch
        with torch.no_grad():
            gesture_logits, direction_logits = self.model.forward_heads(
                torch.tensor(x, dtype=torch.float32))
            probs = torch.softmax(gesture_logits, dim=1)[0].numpy()
            dir_idx = int(torch.argmax(direction_logits, dim=1)[0])
        self._last_probs = probs

        k = int(np.argmax(probs))
        name = self.labels[k]
        label = name if name != "none" and probs[k] >= self.threshold else "none"

        start_s = self._times[0]
        if label != "none":
            self._run_meta.append((start_s, float(probs[k]), self.direction_names[dir_idx]))
        event = self.tracker.feed(label, start_s)
        out = []
        if event is not None:
            out.append(self._enrich(event))
        if label == "none":
            self._run_meta = []
        return out

    def finish(self) -> list[GestureEvent]:
        """End of stream: flush the tracker's open run."""
        tail = self.tracker.finish()
        return [self._enrich(tail)] if tail is not None else []

    def _enrich(self, event: events.Event) -> GestureEvent:
        meta = [(p, d) for s, p, d in self._run_meta
                if event.start_s - 1e-9 <= s <= event.end_s + 1e-9]
        confidence = float(np.mean([p for p, _ in meta])) if meta else 0.0
        directions = [d for _, d in meta if d != "none"]
        direction = max(set(directions), key=directions.count) if directions else "none"
        return GestureEvent(name=event.label, direction=direction,
                            t_s=event.centre_s, confidence=confidence,
                            run_length=event.run_length)

    @property
    def last_probabilities(self) -> dict[str, float]:
        """Most recent per-class probabilities, for a live display."""
        if self._last_probs is None:
            return {}
        return {name: float(p) for name, p in zip(self.labels, self._last_probs)}


# ---------------------------------------------------------------- the app layer

@dataclass
class RouterConfig:
    """
    Which gestures mean what to the application.

    Keys are gesture names, optionally direction-qualified ("flick:up" wins over
    "flick" when both match). Values are action names the app understands --
    for Whip, "flag" and "approve". Unmapped gestures are still reported, just
    with no action: a general classifier's whole point is that other apps may
    care about events this one ignores.
    """

    mappings: dict[str, str] = field(default_factory=lambda: {
        "flick": "flag", "double_flick": "approve"})
    threshold: float = DEFAULT_THRESHOLD

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "RouterConfig":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls(mappings=dict(raw.get("mappings", {})),
                   threshold=float(raw.get("threshold", DEFAULT_THRESHOLD)))

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"mappings": self.mappings, "threshold": self.threshold}, indent=2))

    def action_for(self, event: GestureEvent) -> str | None:
        qualified = f"{event.name}:{event.direction}"
        if qualified in self.mappings:
            return self.mappings[qualified]
        return self.mappings.get(event.name)


class EventLog:
    """
    Append-only JSONL of events and resolved actions.

    This file is the artifact the preference-labeling loop (M2) consumes: each
    line is a gesture with its action, wall-clock stamped so it can be joined
    against whatever the model was doing at the time.
    """

    def __init__(self, directory: Path = EVENT_LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = directory / f"events_{stamp}.jsonl"
        self._handle = self.path.open("a")

    def write(self, event: GestureEvent, action: str | None) -> None:
        self._handle.write(json.dumps({
            **event.as_dict(), "action": action, "wall": time.time()}) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()
