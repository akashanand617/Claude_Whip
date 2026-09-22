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

DEFAULT_THRESHOLD = 0.5   # chosen on val 2026-09-21: recovers mid-run confidence dips, ambient still 0


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
        # A head trained with weight 0 emits deterministic garbage; routing a
        # "flick:up" mapping on it would fire the wrong action confidently.
        self.direction_trained = bool(provenance.get("direction_trained", True))
        self.threshold = threshold
        registry = registry or load_registry()
        self.registry = registry
        # Direction-split sub-classes collapse into their gesture before the
        # threshold and the tracker see them; the winning sub-class per window
        # is remembered so a fired event can report its direction.
        self.collapsed = registry.collapsed_names(self.labels)
        self.tracker = events.RunTracker(policies=registry.policies(self.collapsed))
        self._despike = despike.StreamingHampel(enabled=despike.ENABLED)
        self._samples: list[np.ndarray] = []       # despiked, in counts
        self._times: list[float] = []
        self._pending_times: list[float] = []      # awaiting their despiked sample
        self._since_last_window = 0
        # (start_s, winning probability, direction name) per emitted window --
        # kept for the run in progress so a fired event can report confidence
        # and direction aggregated over its windows, not just the last one.
        self._run_meta: list[tuple[float, float, str]] = []
        self._last_probs: np.ndarray | None = None
        # Ring frame. The model is trained in the canonical wearing (sensor
        # below the finger, finger axis pointing the known way). Worn back to
        # front, every flick failed live (2/20; 17/20 on the same bytes once
        # the frame was corrected). The frame is a proper rotation applied to
        # every decoded sample; it is set from a calibration pose, or found
        # automatically: with the fingers pointing at the floor, gravity lies
        # along the finger axis and its SIGN says which way the ring is on
        # (canonical: positive, 98-99% of hanging-arm windows in two ambient
        # hours). `auto_frame` watches for that pose in the live stream.
        self.frame = np.eye(3)
        self.frame_name = "identity"
        self.auto_frame = True
        self._pose: list[np.ndarray] = []          # recent raw samples, for auto-frame
        self.frame_changes: list[tuple[float, str]] = []

    # ------------------------------------------------------------------ frame

    FLIPS = {"identity": np.diag([1.0, 1.0, 1.0]), "flip_axis0": np.diag([1.0, -1.0, -1.0]),
             "flip_axis1": np.diag([-1.0, 1.0, -1.0]), "flip_axis2": np.diag([-1.0, -1.0, 1.0])}
    POSE_SAMPLES = 50            # 2 s of stillness with the fingers down
    POSE_MIN_ALONG = 0.90        # |g . finger| / |g| for "fingers pointing at the floor"
    POSE_MAX_MOTION_G = 0.25     # peak deviation from the mean, in g, for "still"

    def set_frame(self, name: str, t_s: float = 0.0) -> None:
        if name not in self.FLIPS:
            raise ValueError(f"unknown frame {name!r}; one of {sorted(self.FLIPS)}")
        if name != self.frame_name:
            self.frame_changes.append((t_s, name))
        self.frame, self.frame_name = self.FLIPS[name], name

    @staticmethod
    def pose_check(raw_samples) -> dict:
        """
        Judge a candidate fingers-at-the-floor pose: `raw_samples` (N, 3) in
        counts or g. Returns the two numbers the pose is judged on and the
        verdict, so a UI can say WHY a pose is not being accepted:

          along     gravity component along the finger axis, unit (sign = wearing)
          off_deg   angle between the finger and the vertical, degrees
          motion    peak deviation from the mean, in g
          still     motion within POSE_MAX_MOTION_G
          down      |along| at least POSE_MIN_ALONG
          frame     the frame name when still and down, else None
        """
        from whip.model import FINGER_AXIS
        x = np.asarray(raw_samples, dtype="float64")
        out = {"along": 0.0, "off_deg": 90.0, "motion": 0.0, "still": False, "down": False, "frame": None,
               "samples": int(len(x))}
        if len(x) < 10:
            return out
        g = x.mean(axis=0); n = np.linalg.norm(g)
        if n < 1e-6:
            return out
        along = float(g[FINGER_AXIS] / n)
        motion = float(np.linalg.norm(x - g, axis=1).max() / n)
        out.update(along=along, off_deg=float(np.degrees(np.arccos(min(1.0, abs(along))))), motion=motion,
                   still=motion <= Engine.POSE_MAX_MOTION_G, down=abs(along) >= Engine.POSE_MIN_ALONG)
        if out["still"] and out["down"]:
            out["frame"] = "identity" if along > 0 else "flip_axis0"
        return out

    @staticmethod
    def frame_from_pose(raw_samples) -> str | None:
        """
        Which frame puts a fingers-at-the-floor pose into the canonical
        wearing: `raw_samples` (N, 3) in counts or g, the ring held still with
        the fingers pointing down. None when the pose is not that (not
        still, or gravity not along the finger).
        """
        return Engine.pose_check(raw_samples)["frame"]

    def calibrate(self, raw_samples, t_s: float = 0.0) -> str | None:
        """Set the frame from a fingers-down pose; returns the frame name, or None if the pose was not held."""
        name = self.frame_from_pose(raw_samples)
        if name is not None:
            self.set_frame(name, t_s)
        return name

    def _watch_pose(self, xyz: np.ndarray, t_s: float) -> None:
        self._pose.append(xyz)
        if len(self._pose) > self.POSE_SAMPLES:
            self._pose.pop(0)
        if len(self._pose) == self.POSE_SAMPLES:
            name = self.frame_from_pose(self._pose)
            if name is not None and name != self.frame_name:
                self.set_frame(name, t_s)

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
        raw = np.array((sample.x, sample.y, sample.z), dtype="float64")
        if self.auto_frame:
            self._watch_pose(raw, t_s)
        xyz = self.frame @ raw
        # The despiker lags by half a window, so an emitted sample is not THIS
        # notification -- it is one from ~120 ms ago. Timestamps queue up on the
        # way in and pair with samples on the way out, or every window start
        # (and therefore every event time) would be 120 ms late against offline.
        self._pending_times.append(t_s)
        out: list[GestureEvent] = []
        for filtered in self._despike.push(xyz):
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
        means = window.mean(axis=1, keepdims=True)
        centred = (window - means) / accel.COUNTS_PER_G
        from whip import model as gm

        x = gm.to_model_input(centred[None, ...], self.channels,
                              gravity=(means[:, 0] / accel.COUNTS_PER_G)[None, :])
        torch = self._torch
        with torch.no_grad():
            gesture_logits, direction_logits = self.model.forward_heads(
                torch.tensor(x, dtype=torch.float32))
            probs = torch.softmax(gesture_logits, dim=1)[0].numpy()
            dir_idx = int(torch.argmax(direction_logits, dim=1)[0]) \
                if self.direction_trained else 0
        raw_k = int(np.argmax(probs))
        raw_base, raw_dir = self.registry.collapse(self.labels[raw_k])
        probs = self.registry.collapse_probabilities(probs[None, :], self.labels)[0]
        self._last_probs = probs

        k = int(np.argmax(probs))
        name = self.collapsed[k]
        label = name if name != "none" and probs[k] >= self.threshold else "none"

        start_s = self._times[0]
        if label != "none":
            # Direction: the split sub-class if there is one, else the head
            # (only when it was actually trained), else none.
            direction = raw_dir if raw_dir != "none" else self.direction_names[dir_idx]
            self._run_meta.append((start_s, float(probs[k]), direction))
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
        return {name: float(p) for name, p in zip(self.collapsed, self._last_probs)}


# ------------------------------------------------------------- calibration

class PoseCalibrator:
    """
    The fingers-at-the-floor gate, one sample at a time, with progress and a
    reason. The console runs one at the start of every tracking session and
    again whenever the ring changes hands (`reset`).

    The pose is judged on a rolling 2 s buffer (`Engine.POSE_SAMPLES`): still,
    and gravity along the finger. Progress only accrues while the buffer is
    good and restarts from zero when it stops being good -- so "held for 3 s"
    means three seconds of an accepted pose, not three seconds since the
    button. Every `feed` returns a status dict:

      status    "collecting" | "hold" | "retry" | "ok"
      held_s    seconds of accepted pose so far (0 when retrying)
      hold_s    what is required
      reason    "moving" | "not_down" | None (why the pose is not accepted)
      off_deg   how far the finger is from vertical (guidance for not_down)
      motion    peak motion in g (guidance for moving)
      frame     set on "ok": the frame name the pose implies
      wearing   set on "ok": "canonical" | "reversed"

    Live-console lesson (2026-09-21): the one-line countdown said "hold
    still" whether the wearer was moving or simply had the fingers 40
    degrees off vertical, and a second wearer never got a pose at all
    because tracking only calibrated once. The reason and the reset exist
    for those two cases.
    """

    HOLD_S = 3.0

    def __init__(self, hold_s: float = HOLD_S):
        self.hold_s = float(hold_s)
        self.reset()

    def reset(self) -> None:
        self._buf: list[np.ndarray] = []
        self._good_since: float | None = None
        self._buffer_s = Engine.POSE_SAMPLES * events.STRIDE_S / 6.0   # 50 samples at 25 Hz = 2 s
        self.result: dict | None = None
        self.done = False

    def feed(self, t_s: float, xyz) -> dict:
        if self.done and self.result is not None:
            return self.result
        self._buf.append(np.asarray(xyz, dtype="float64"))
        if len(self._buf) > Engine.POSE_SAMPLES:
            self._buf.pop(0)
        base = {"type": "calibration", "hold_s": self.hold_s, "held_s": 0.0, "reason": None,
                "off_deg": None, "motion": None, "frame": None, "wearing": None}
        if len(self._buf) < Engine.POSE_SAMPLES:
            base["status"] = "collecting"
            base["held_s"] = round(len(self._buf) / Engine.POSE_SAMPLES * min(self._buffer_s, self.hold_s), 2)
            return base
        chk = Engine.pose_check(self._buf)
        base.update(off_deg=round(chk["off_deg"], 1), motion=round(chk["motion"], 2))
        if chk["frame"] is None:
            self._good_since = None
            base["status"] = "retry"
            base["reason"] = "moving" if not chk["still"] else "not_down"
            return base
        if self._good_since is None:
            self._good_since = t_s
        held = min(self.hold_s, self._buffer_s + (t_s - self._good_since))
        base["held_s"] = round(held, 2)
        if held + 1e-9 < self.hold_s:
            base["status"] = "hold"
            return base
        base.update(status="ok", frame=chk["frame"], along=round(chk["along"], 3),
                    wearing="canonical" if chk["frame"] == "identity" else "reversed")
        self.result, self.done = base, True
        return base


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
