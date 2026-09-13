"""
The gesture classifier, and the augmentation that trains it.

This lives in the repo rather than only in the notebook for two reasons. A
checkpoint that pickles a class defined in a notebook can only ever be loaded by
that notebook -- `probe.rollout` could not read it. And the C++ daemon has to
reproduce these exact layer shapes, so there needs to be one definition to port
from rather than a cell somebody edited afterwards.

The notebook still shows the process. It imports this.

Input is (4, 50) -- two seconds at 25 Hz as three unit-amplitude waveform
channels plus one channel carrying log peak amplitude. See `to_model_input` for
why the split is not cosmetic.

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

N_CLASSES = 3
N_AXES = 3
WINDOW_SAMPLES = 50

# Shape on three channels plus peak amplitude on a fourth.
N_CHANNELS = 4

SCALE_FLOOR_G = 1e-3


def to_model_input(x):
    """
    Split each window into a unit-amplitude waveform and a separate scale channel.

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

    Takes (N, 3, W) and returns (N, 4, W).
    """
    import numpy as np

    x = np.asarray(x, dtype="float32")
    peak = np.sqrt((x ** 2).sum(axis=1)).max(axis=1)[:, None, None]
    peak = np.maximum(peak, SCALE_FLOOR_G)
    shape = x / peak
    # log, because gesture amplitude spans roughly 0.1 g to 7 g and a linear
    # channel would let the loud end dominate the gradient.
    scale = np.repeat(np.log10(peak), x.shape[2], axis=2)
    return np.concatenate([shape, scale], axis=1).astype("float32")


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
                 blocks: int = INCEPTION_BLOCKS):
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

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = x
        for block in self.blocks:
            z = block(z)
        z = torch.relu(z + self.shortcut(x))
        pooled = torch.cat([z.mean(dim=2), z.amax(dim=2), z.std(dim=2)], dim=1)
        return self.head(self.dropout(pooled))


# Settled by ablation, not by taste. The first version scaled amplitude +/-30%,
# rotated +/-30 degrees, jittered heavily and time-warped; it cost more than ten
# points and manufactured false positives on the adversarial session. Time warp
# was harmful at every level tried, because interpolating between samples smooths
# exactly the oscillation peaks that distinguish a single flick from a double.
AMPLITUDE_RANGE = 0.2      # +/-20%
ROTATION_DEGREES = 10.0
NOISE_G = 0.02


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


def save(model: GestureNet, path, trained_on: list[str], held_out: list[str]) -> None:
    """
    State dict plus provenance -- never the pickled module.

    `trained_on` is not decoration. Recall on a session the model trained on is
    memorisation, and every report that omits which sessions those were has
    quietly inflated its own headline number.
    """
    torch.save({
        "state_dict": model.state_dict(),
        "architecture": type(model).__name__,
        "n_channels": model.n_channels,
        "trained_on": sorted(trained_on),
        "held_out": sorted(held_out),
        "window_samples": WINDOW_SAMPLES,
    }, path)


def load(path) -> tuple[GestureNet, dict]:
    obj = torch.load(path, map_location="cpu", weights_only=False)
    # Checkpoints name their architecture. Without this a CompactNet checkpoint
    # silently fails to load into a GestureNet with a shape error nobody can read.
    cls = {"CompactNet": CompactNet, "GestureNet": GestureNet}[obj.get("architecture", "CompactNet")]
    model = cls(n_channels=obj.get("n_channels", N_CHANNELS))
    model.load_state_dict(obj["state_dict"])
    model.eval()
    return model, obj
