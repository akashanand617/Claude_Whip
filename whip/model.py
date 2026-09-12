"""
The gesture classifier, and the augmentation that trains it.

This lives in the repo rather than only in the notebook for two reasons. A
checkpoint that pickles a class defined in a notebook can only ever be loaded by
that notebook -- `probe.rollout` could not read it. And the C++ daemon has to
reproduce these exact layer shapes, so there needs to be one definition to port
from rather than a cell somebody edited afterwards.

The notebook still shows the process. It imports this.

Shape of the thing: input is (3, 50) -- three axes, two seconds at 25 Hz,
gravity removed but amplitude kept.

    Conv1d(3->16, k=5)  BN ReLU MaxPool2      (16, 25)
    Conv1d(16->32, k=5) BN ReLU MaxPool2      (32, 12)
    Conv1d(32->64, k=7) BN ReLU               (64, 12)
    global avg (+) global max -> 128 -> Dropout -> Linear(3)

Receptive field is 40 samples, 1600 ms, which comfortably spans the longest
measured gesture (1395 ms). Concatenating average and max pooling matters more
than it looks: average carries how sustained the motion was, max carries how
hard the peak was, and the two features that actually separate the classes are
oscillation count and amplitude.

17,859 parameters. Small on purpose -- there are a few hundred gestures, and the
failure mode already measured is memorising the session rather than underfitting.
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn

N_CLASSES = 3
N_AXES = 3
WINDOW_SAMPLES = 50


class GestureNet(nn.Module):
    def __init__(self, n_classes: int = N_CLASSES, dropout: float = 0.3):
        super().__init__()
        self.block1 = nn.Sequential(
            nn.Conv1d(N_AXES, 16, 5, padding=2), nn.BatchNorm1d(16), nn.ReLU(), nn.MaxPool1d(2))
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
        scale = 1.0 - amplitude + 2 * amplitude * torch.rand(len(batch), 1, 1, device=batch.device)
        out = out * scale
    if rotation_deg:
        theta = (torch.rand(len(batch), device=batch.device) * 2 - 1) * (rotation_deg * math.pi / 180)
        cos, sin = torch.cos(theta)[:, None], torch.sin(theta)[:, None]
        y, z = out[:, 1].clone(), out[:, 2].clone()
        out[:, 1], out[:, 2] = cos * y - sin * z, sin * y + cos * z
    if noise_g:
        out = out + noise_g * torch.randn_like(out)
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
        "trained_on": sorted(trained_on),
        "held_out": sorted(held_out),
        "window_samples": WINDOW_SAMPLES,
    }, path)


def load(path) -> tuple[GestureNet, dict]:
    obj = torch.load(path, map_location="cpu", weights_only=False)
    model = GestureNet()
    model.load_state_dict(obj["state_dict"])
    model.eval()
    return model, obj
