"""
The gesture classifier, and the augmentation that trains it.

This lives in the repo rather than only in the notebook for two reasons. A
checkpoint that pickles a class defined in a notebook can only ever be loaded by
that notebook -- `probe.rollout` could not read it. And the C++ daemon has to
reproduce these exact layer shapes, so there needs to be one definition to port
from rather than a cell somebody edited afterwards.

The notebook still shows the process. It imports this.

Shape of the thing: input is (4, 50) -- two seconds at 25 Hz as three
unit-amplitude waveform channels plus one channel carrying log peak amplitude.
See `to_model_input` for why the split is not cosmetic.

    Conv1d(4->16, k=5)  BN ReLU MaxPool2      (16, 25)
    Conv1d(16->32, k=5) BN ReLU MaxPool2      (32, 12)
    Conv1d(32->64, k=7) BN ReLU               (64, 12)
    global avg (+) global max -> 128 -> Dropout -> Linear(3)

Receptive field is 40 samples, 1600 ms, which comfortably spans the longest
measured gesture (1395 ms). Concatenating average and max pooling matters more
than it looks: average carries how sustained the motion was, max carries how
hard the peak was, and the two features that actually separate the classes are
oscillation count and amplitude.

17,939 parameters. Small on purpose -- there are a few hundred gestures, and the
failure mode already measured is memorising the session rather than underfitting.
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


class GestureNet(nn.Module):
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
        "n_channels": model.n_channels,
        "trained_on": sorted(trained_on),
        "held_out": sorted(held_out),
        "window_samples": WINDOW_SAMPLES,
    }, path)


def load(path) -> tuple[GestureNet, dict]:
    obj = torch.load(path, map_location="cpu", weights_only=False)
    model = GestureNet(n_channels=obj.get("n_channels", N_CHANNELS))
    model.load_state_dict(obj["state_dict"])
    model.eval()
    return model, obj
