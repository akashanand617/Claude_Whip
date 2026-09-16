"""
The gesture classifier, and the augmentation that trains it.

This lives in the repo rather than only in the notebook for two reasons. A
checkpoint that pickles a class defined in a notebook can only ever be loaded by
that notebook -- `probe.rollout` could not read it. And the C++ daemon has to
reproduce these exact layer shapes, so there needs to be one definition to port
from rather than a cell somebody edited afterwards.

The notebook still shows the process. It imports this.

Input is (C, 50) -- two seconds at 25 Hz. Which channels, and why the split is
not cosmetic, is `to_model_input`; the default is three unit-amplitude waveform
channels plus one carrying log peak amplitude.

`GestureNet` is an InceptionTime-style multi-scale stack. `CompactNet` is the
smaller design it replaced, kept because it is the honest comparison point.

**Why the first design was wrong.** CompactNet pools 2x twice, taking 50 samples
to 12, then pools globally over time. The measured discriminator between the two
gesture classes is *oscillation count* -- singles average 2 peaks, doubles 5. A
1.4 s double flick is ~35 samples, which is ~8 after pooling, so fitting five
distinguishable peaks into eight bins sits at the Nyquist limit. Worse, global
average and global max cannot count at all: one reports total activation, the
other the single largest. The architecture was discarding the exact feature the
classes differ on.

**Measured, seven seeds, every model calibrated to the same 1 false-positive-per-
hour budget before recall was read off** -- otherwise the comparison ranks
confidence calibration rather than discriminative power, and a model that is
merely reluctant to fire looks precise:

    architecture                  recall @ 1 FP/hour
    CompactNet (pool + global)        57.1 +/- 13.6
    + std pooling                     62.1 +/-  6.3
    dilated, no pooling               62.3 +/-  8.9
    dilated + attention pooling       63.8 +/- 15.4
    resnet1d (499k params)            59.4 +/-  4.9
    conv + biGRU (DeepConvLSTM)       56.2 +/- 12.4
    GestureNet (inception)            69.9 +/-  7.4

Two things that ranking settles. Removing the pooling helps, which is the
predicted direction. And recurrence *loses* -- the biGRU is worst on recall, so
the one architecture that would have forced a painful hand-written C++ port is
also the one not worth porting. GestureNet is pure convolution.

The winner also reaches its budget at a threshold of 0.57, among the lowest in
the field. It is not buying precision by being timid; it separates the classes
well enough to sit at a relaxed operating point.

~226k parameters, 12x CompactNet. Size was traded for reliability deliberately:
seed-to-seed spread roughly halves against the baseline's +/-13.6.

**What architecture did not fix:** false positives on waving, 39-69/hour across
every design tried, with no trend. That is a data gap -- there are 1.7 minutes of
waving in the corpus -- and no architecture search will close it.
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn

N_CLASSES = 4
N_AXES = 3
WINDOW_SAMPLES = 50

# Shape on three channels plus peak amplitude on a fourth.
N_CHANNELS = 4

SCALE_FLOOR_G = 1e-3


# Samples in the moving average that estimates the gravity component. 9 samples
# at 25 Hz is roughly a 2.8 Hz cutoff -- below the 4-8 Hz oscillation of a flick,
# above the 1-3 Hz of a wave and the rate at which the wrist actually reorients.
GRAVITY_WINDOW = 9

# signed16 full scale divided by the measured counts per g.
FULL_SCALE_G = 32767 / 8005.0

DEFAULT_CHANNELS = ("shape", "scale")

# Which ring axis runs along the finger. MEASURED 2026-09-16 from the resting
# gravity vector in three known palm orientations (`probe.collect --matrix`):
# palm up puts gravity on axis 0 (so axis 0 is the palm normal), palm left /
# palm right put it on -/+ axis 2 (so axis 2 is the thumb-pinky line), which
# leaves axis 1 along the finger. An earlier assumption that axis 0 was the
# finger came from the flick's ROTATION axis being axis 0 -- which is right:
# a wrist flick rotates about the palm normal / thumb line, not the finger.
FINGER_AXIS = 1

CHANNEL_WIDTHS = {"shape": 3, "gravity": 3, "linear": 3, "scale": 1, "saturation": 1,
                  "posture": 3, "invariant": 3, "gref": 2, "room": 3}


def _moving_average(x, width: int):
    """Centred moving average along the last axis, reflect-padded at the edges."""
    import numpy as np

    pad = width // 2
    padded = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(pad, pad)], mode="reflect")
    kernel = np.ones(width) / width
    return np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), -1, padded)


def n_channels_for(channels=DEFAULT_CHANNELS) -> int:
    return sum(CHANNEL_WIDTHS[c] for c in channels)


def to_model_input(x, channels=DEFAULT_CHANNELS, gravity=None):
    """
    Derive model channels from a stored window.

    Input is (N, 3, W) in g with the DC term already removed by `dataset`.
    Output is (N, C, W) where C is `n_channels_for(channels)`.

    Groups, each independently selectable so ablations can move one factor at a
    time -- conflating several changes into one comparison is the specific
    mistake this project's architecture table made:

    - `shape` (3): the waveform, scaled to unit peak amplitude.
    - `scale` (1): log peak amplitude, constant across the window.
    - `gravity` (3): the low-frequency component, which is the gravity vector
      swinging as the wrist rotates. A flick is a rotation; waving and walking
      are mostly translation. Static attitude is already gone -- `dataset` strips
      the DC term -- so what survives here is rotation *dynamics*.
    - `linear` (3): what is left after removing the gravity component.
    - `saturation` (1): fraction of samples at the +/-4.09 g rail. Hard flicks
      clip, which flat-tops the shape channel exactly where shape matters most,
      and without this the model cannot tell a flat top from a real plateau.
    - `posture` (3): the window's mean gravity vector as a unit vector, constant
      over time -- needs `gravity` (N, 3) from the export. This is the hand's
      orientation in the ring's frame. A palm-down flick and a hand-vertical
      flick are the same wrist flexion; only gravity tells them apart, and a
      direction model without it was measured to permute directions between
      sessions (down->right, up->left: same sense, different posture).
    - `invariant` (3): |a|, the along-finger component, and the magnitude in
      the plane perpendicular to the finger. Exactly invariant to the ring
      spinning on the finger, with no reference needed -- for gesture TYPE,
      where orientation is a nuisance rather than the signal.
    - `gref` (2): the impulsive part of the motion along gravity and
      perpendicular to it -- needs `gravity`. Invariant to any rotation of the
      ring frame, because a and g rotate together. This is the physically
      right way to tell a vertical flick from a horizontal one: `posture`
      encodes the same fact as an absolute vector that drifts between days.
    - `room` (3): the impulsive motion in a frame built from gravity and the
      finger: along gravity (signed: up vs down), lateral = along
      gravity x finger (signed: room-left vs room-right), and forward (the
      finger's direction with gravity removed). Needs `gravity`. Invariant to
      the ring spinning on the finger, NOT to the ring being worn back to
      front -- that flips the lateral sign, and it is the one bit a room-frame
      left/right needs (decided 2026-09-16: every direction is the direction
      the hand moved in the room, in any posture). Requires the wear rule.

    `gravity + linear == shape` exactly, so passing all three is redundant; the
    useful comparison is `("shape", "scale")` against
    `("gravity", "linear", "scale")` -- same information, told apart by frequency.

    Everything is normalised by the same peak, so amplitude stays confined to the
    scale channel rather than leaking back into the waveform channels.

    `dataset` stores windows in g with gravity removed, which is the right
    physical record. It is the wrong *model* input, and measurement says so:
    trained on raw g, the network keys on amplitude, because amplitude is the
    easiest feature available. That single choice causes both failure modes at
    once. Soft flicks peak near 2.3 g and typing peaks near 2.0 g, so a model
    thresholding on amplitude misses half the soft gestures *and* fires while
    you type -- 28% soft recall at 10 false positives an hour.

    Dividing the amplitude out entirely is worse in the other direction: a quiet
    window normalises sensor noise up to full scale and starts looking like a
    gesture, which cost 6 points of recall on hard flicks.

    Keeping both, separately, beat raw amplitude on every axis over five seeds --
    soft 28 -> 35%, hard 61 -> 73%, typing false positives 10 -> 4/hour -- and
    roughly halved the seed-to-seed variance. The network can still use amplitude
    as evidence; it just can't let it drown the waveform.

    """
    import numpy as np

    unknown = set(channels) - set(CHANNEL_WIDTHS)
    if unknown:
        raise ValueError(f"unknown channel group(s): {sorted(unknown)}")

    x = np.asarray(x, dtype="float32")
    peak = np.maximum(np.sqrt((x ** 2).sum(axis=1)).max(axis=1)[:, None, None], SCALE_FLOOR_G)
    if "posture" in channels and gravity is None:
        raise ValueError("the 'posture' channel group needs the per-window gravity vectors "
                         "(export format v5+)")

    parts = []
    for name in channels:
        if name == "shape":
            parts.append(x / peak)
        elif name == "gravity":
            # No further mean removal: `dataset` already stripped the DC term, so
            # this is a no-op that would only introduce edge-effect error and
            # break the exact `gravity + linear == shape` decomposition.
            parts.append(_moving_average(x, GRAVITY_WINDOW) / peak)
        elif name == "linear":
            parts.append((x - _moving_average(x, GRAVITY_WINDOW)) / peak)
        elif name == "scale":
            # log, because gesture amplitude spans roughly 0.1 g to 7 g and a
            # linear channel would let the loud end dominate the gradient.
            parts.append(np.repeat(np.log10(peak), x.shape[2], axis=2))
        elif name == "saturation":
            clipped = (np.abs(x) >= 0.98 * FULL_SCALE_G).any(axis=1, keepdims=True)
            parts.append(np.repeat(clipped.mean(axis=2, keepdims=True), x.shape[2], axis=2))
        elif name == "posture":
            g = np.asarray(gravity, dtype="float32")
            g = g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), SCALE_FLOOR_G)
            parts.append(np.repeat(g[:, :, None], x.shape[2], axis=2))
        elif name == "invariant":
            mag = np.sqrt((x ** 2).sum(axis=1, keepdims=True))
            perp = np.sqrt((x[:, 1:3] ** 2).sum(axis=1, keepdims=True))
            parts.append(np.concatenate([mag, x[:, 0:1], perp], axis=1) / peak)
        elif name == "room":
            if gravity is None:
                raise ValueError("the 'room' channel group needs the per-window gravity "
                                 "vectors (export format v5+)")
            g = np.asarray(gravity, dtype="float32")
            g = g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), SCALE_FLOOR_G)
            finger = np.zeros_like(g); finger[:, FINGER_AXIS] = 1.0
            lateral = np.cross(g, finger)
            lat_norm = np.linalg.norm(lateral, axis=1, keepdims=True)
            # Fingers pointing straight at the floor or ceiling: no lateral
            # direction exists. The channel goes to zero rather than to noise.
            lateral = np.where(lat_norm > 0.05, lateral / np.maximum(lat_norm, 1e-6), 0.0)
            forward = np.cross(lateral, g)
            lin = x - _moving_average(x, GRAVITY_WINDOW)
            parts.append(np.stack([np.einsum("ntw,nt->nw", lin, g),
                                   np.einsum("ntw,nt->nw", lin, lateral),
                                   np.einsum("ntw,nt->nw", lin, forward)], axis=1) / peak)
        elif name == "gref":
            # Gravity-referenced: the impulsive (linear) part of the motion
            # resolved along the window's gravity vector and perpendicular to
            # it. "Vertical motion or horizontal motion" is a relation between
            # a and g measured in one frame, so it does not care how the ring
            # sits on the finger or which way its axes point -- unlike
            # `posture`, which hands the model an absolute vector that moves
            # 23-55 degrees between days. Measured without any training: the
            # fraction of impulsive energy along g is 0.49-0.69 for up/down and
            # 0.10-0.16 for left/right in every session, and one fixed cut
            # separates the pairs at 95% over three sessions.
            if gravity is None:
                raise ValueError("the 'gref' channel group needs the per-window gravity "
                                 "vectors (export format v5+)")
            g = np.asarray(gravity, dtype="float32")
            g = g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), SCALE_FLOOR_G)
            lin = x - _moving_average(x, GRAVITY_WINDOW)
            along = np.einsum("ntw,nt->nw", lin, g)[:, None, :]
            perp = np.sqrt(np.maximum((lin ** 2).sum(axis=1, keepdims=True) - along ** 2, 0.0))
            parts.append(np.concatenate([along, perp], axis=1) / peak)

    return np.concatenate(parts, axis=1).astype("float32")


class CompactNet(nn.Module):
    """
    The original 18k-parameter design. Superseded -- see the module docstring for
    the measurement -- but kept as the comparison point, and because old
    checkpoints reference it.
    """

    def __init__(self, n_classes: int = N_CLASSES, dropout: float = 0.3,
                 n_channels: int = N_CHANNELS):
        super().__init__()
        self.n_channels = n_channels
        self.block1 = nn.Sequential(
            nn.Conv1d(n_channels, 16, 5, padding=2), nn.BatchNorm1d(16), nn.ReLU(), nn.MaxPool1d(2))
        self.block2 = nn.Sequential(
            nn.Conv1d(16, 32, 5, padding=2), nn.BatchNorm1d(32), nn.ReLU(), nn.MaxPool1d(2))
        self.block3 = nn.Sequential(
            nn.Conv1d(32, 64, 7, padding=3), nn.BatchNorm1d(64), nn.ReLU())
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(128, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.block3(self.block2(self.block1(x)))
        pooled = torch.cat([x.mean(dim=2), x.amax(dim=2)], dim=1)
        return self.head(self.dropout(pooled))


# Kernel widths in samples at 25 Hz: 9 = 360 ms, 19 = 760 ms, 39 = 1560 ms.
# One branch sees a single oscillation, one sees the gap between two, one spans
# the whole gesture. Committing to a single kernel size means choosing which of
# those to be blind to.
INCEPTION_KERNELS = (9, 19, 39)
INCEPTION_CHANNELS = 32
INCEPTION_BLOCKS = 3


class InceptionBlock(nn.Module):
    """
    Parallel convolutions at several time scales, concatenated.

    The bottleneck 1x1 keeps the parameter count of the wide branches down. The
    max-pool branch runs on the block input rather than the bottleneck so a
    strong short transient survives the dimensionality reduction.
    """

    def __init__(self, in_channels: int, channels: int = INCEPTION_CHANNELS,
                 kernels: tuple[int, ...] = INCEPTION_KERNELS):
        super().__init__()
        self.bottleneck = nn.Conv1d(in_channels, channels, 1)
        self.branches = nn.ModuleList(
            [nn.Conv1d(channels, channels, k, padding=k // 2) for k in kernels])
        self.pool_branch = nn.Sequential(
            nn.MaxPool1d(3, stride=1, padding=1), nn.Conv1d(in_channels, channels, 1))
        self.norm = nn.BatchNorm1d(channels * (len(kernels) + 1))
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        bottled = self.bottleneck(x)
        parts = [branch(bottled) for branch in self.branches] + [self.pool_branch(x)]
        return self.relu(self.norm(torch.cat(parts, dim=1)))


class GestureNet(nn.Module):
    """
    Multi-scale convolution, no temporal pooling, statistics pooling at the end.

    No MaxPool1d anywhere in the trunk: full 50-sample resolution is preserved
    all the way through, because that resolution is what counting oscillations
    depends on.

    Pooling reports mean, max *and* standard deviation. Std is the one of the
    three that carries variation over time, which is the closest cheap proxy for
    oscillation count; mean and max both discard it. On its own, adding std to
    the old architecture was worth 5 points.
    """

    def __init__(self, n_classes: int = N_CLASSES, dropout: float = 0.3,
                 n_channels: int = N_CHANNELS, channels: int = INCEPTION_CHANNELS,
                 kernels: tuple[int, ...] = INCEPTION_KERNELS,
                 blocks: int = INCEPTION_BLOCKS, n_directions: int = 5):
        super().__init__()
        self.n_channels = n_channels
        width = channels * (len(kernels) + 1)
        self.blocks = nn.ModuleList([
            InceptionBlock(n_channels if i == 0 else width, channels, kernels)
            for i in range(blocks)])
        # Residual path from the raw input, as in InceptionTime. With only a few
        # hundred gestures the shortcut matters: it gives the classifier a route
        # to the signal that does not depend on the stack having trained well.
        self.shortcut = nn.Sequential(nn.Conv1d(n_channels, width, 1), nn.BatchNorm1d(width))
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(width * 3, n_classes)
        # Direction is a second head, not extra classes. Splitting flick by
        # direction would make eight classes at ~200 windows each -- a 4x data
        # starvation of the two best-supported gestures -- while a head shares
        # every flick window and still lets events carry (gesture, direction).
        # It also acts as free regularisation: the trunk must encode WHICH WAY
        # the wrist rotated, not just that it did, which is structure a
        # 264-gesture corpus cannot afford to leave on the table.
        self.direction_head = nn.Linear(width * 3, n_directions)

    def _pooled(self, x: torch.Tensor) -> torch.Tensor:
        z = x
        for block in self.blocks:
            z = block(z)
        z = torch.relu(z + self.shortcut(x))
        return torch.cat([z.mean(dim=2), z.amax(dim=2), z.std(dim=2)], dim=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.dropout(self._pooled(x)))

    def forward_heads(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Gesture and direction logits off one trunk pass, for training."""
        pooled = self.dropout(self._pooled(x))
        return self.head(pooled), self.direction_head(pooled)


# Settled by ablation, not by taste. The first version scaled amplitude +/-30%,
# rotated +/-30 degrees, jittered heavily and time-warped; it cost more than ten
# points and manufactured false positives on the adversarial session. Time warp
# was harmful at every level tried, because interpolating between samples smooths
# exactly the oscillation peaks that distinguish a single flick from a double.
AMPLITUDE_RANGE = 0.2      # +/-20%
ROTATION_DEGREES = 10.0
NOISE_G = 0.02


# The four ways a ring can sit on a finger that keep the frame right-handed:
# as-is, or turned half a turn about any one of its axes. Worn the other way
# round (2026-09-15 evening: the along-finger gravity sign flipped for 93-97%
# of two sessions) the deployed model scored 0/44 exact on a session that
# scored 37/44 once the frame was turned back. Training sees every flip so
# the model stops depending on which way the ring went on.
FRAME_FLIPS = (
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
    ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),
    ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
)


def random_frames(n: int, rng, flips: bool = True, spin_deg: float = ROTATION_DEGREES):
    """
    (n, 3, 3) proper rotations of the ring frame: a random half-turn flip
    (when `flips`) composed with a random spin of up to `spin_deg` about the
    finger axis. Every matrix has determinant +1, so rotation SENSE is
    preserved; a mirror would silently relabel directions.

    Two regimes. `flips=True, spin_deg=10` makes the model blind to which way
    the ring is on -- and therefore blind to room-left vs room-right.
    `flips=False, spin_deg=180` (the `room` regime) covers every way the ring
    can SPIN on the finger while keeping the finger axis, the one bit that a
    room-frame left/right needs; the wear rule supplies it.
    """
    import numpy as np

    theta = (rng.random(n) * 2 - 1) * np.radians(spin_deg) if spin_deg else np.zeros(n)
    c, s = np.cos(theta), np.sin(theta)
    spin = np.zeros((n, 3, 3), dtype="float32")
    # rotation about FINGER_AXIS: the other two axes turn into each other
    a, b = [k for k in range(3) if k != FINGER_AXIS]
    spin[:, FINGER_AXIS, FINGER_AXIS] = 1; spin[:, a, a] = c; spin[:, a, b] = -s; spin[:, b, a] = s; spin[:, b, b] = c
    if not flips:
        return spin
    flip = np.asarray(FRAME_FLIPS, dtype="float32")[rng.integers(0, len(FRAME_FLIPS), n)]
    return np.einsum("nij,njk->nik", flip, spin)


def rotate_frame(x, gravity, frames):
    """Apply per-window frame rotations to (n, 3, W) windows and (n, 3) gravity vectors together."""
    import numpy as np

    xr = np.einsum("nij,njw->niw", frames, np.asarray(x, dtype="float32"))
    gr = None if gravity is None else np.einsum("nij,nj->ni", frames, np.asarray(gravity, dtype="float32"))
    return xr, gr


def augment(batch: torch.Tensor,
            amplitude: float = AMPLITUDE_RANGE,
            rotation_deg: float = ROTATION_DEGREES,
            noise_g: float = NOISE_G) -> torch.Tensor:
    """
    Amplitude scale, small rotation about the finger axis, light noise.

    Rotation is applied to axes 1 and 2 only: axis 0 is the finger axis, and
    rotating the ring on the finger spins the other two around it. Rotating all
    three would model the ring being worn on a different finger, which is not a
    thing that happens mid-session.
    """
    out = batch.clone()
    if amplitude:
        factor = 1.0 - amplitude + 2 * amplitude * torch.rand(len(batch), 1, 1, device=batch.device)
        if batch.shape[1] > N_AXES:
            # On a shape+scale input, "louder" means moving the scale channel,
            # not stretching a waveform that is unit-amplitude by construction.
            # Multiplying the shape here would desynchronise it from the scale
            # channel and teach the two to disagree.
            out[:, N_AXES:] = out[:, N_AXES:] + torch.log10(factor)
        else:
            out = out * factor
    if rotation_deg:
        theta = (torch.rand(len(batch), device=batch.device) * 2 - 1) * (rotation_deg * math.pi / 180)
        cos, sin = torch.cos(theta)[:, None], torch.sin(theta)[:, None]
        y, z = out[:, 1].clone(), out[:, 2].clone()
        out[:, 1], out[:, 2] = cos * y - sin * z, sin * y + cos * z
    if noise_g:
        out[:, :N_AXES] = out[:, :N_AXES] + noise_g * torch.randn_like(out[:, :N_AXES])
    return out


def save(model, path, trained_on: list[str], held_out: list[str],
         labels: list[str], channels=DEFAULT_CHANNELS,
         direction_names=("none", "up", "down", "left", "right"),
         direction_trained: bool = True) -> None:
    """
    State dict plus provenance -- never the pickled module.

    `trained_on` is not decoration. Recall on a session the model trained on is
    memorisation, and every report that omits which sessions those were has
    quietly inflated its own headline number.

    `labels` makes the checkpoint self-describing: the server, the frontend and
    the realtime engine all read the class list from here rather than assuming
    one, so adding a gesture never means editing them.
    """
    torch.save({
        "state_dict": model.state_dict(),
        "architecture": type(model).__name__,
        "n_channels": model.n_channels,
        "channels": list(channels),
        "labels": [str(l) for l in labels],
        "direction_names": list(direction_names),
        # An untrained direction head still produces argmaxes -- deterministic
        # garbage. Consumers must know not to route on them.
        "direction_trained": bool(direction_trained),
        "trained_on": sorted(trained_on),
        "held_out": sorted(held_out),
        "window_samples": WINDOW_SAMPLES,
    }, path)


def load(path) -> tuple[nn.Module, dict]:
    obj = torch.load(path, map_location="cpu", weights_only=False)
    if "labels" not in obj:
        raise ValueError(
            f"{path} predates self-describing checkpoints (no labels). "
            "Retrain: python -m probe.train --held-out <session> ..."
        )
    # Checkpoints name their architecture. Without this a CompactNet checkpoint
    # silently fails to load into a GestureNet with a shape error nobody can read.
    cls = {"CompactNet": CompactNet, "GestureNet": GestureNet}[obj.get("architecture", "GestureNet")]
    model = cls(n_channels=obj.get("n_channels", N_CHANNELS), n_classes=len(obj["labels"]))
    model.load_state_dict(obj["state_dict"])
    model.eval()
    return model, obj
