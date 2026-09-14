"""
Remove single-sample artifacts from the accelerometer stream.

The ring emits occasional one-sample excursions that are not motion. Measured on
the recorded corpus: windows whose peak exceeds 3.6 g have a **median width above
half-peak of 1.0 samples** (40 ms) in the idle-coding and typing sessions, while a
real flick is ~9 samples wide. Twenty-seven such windows exist in 2.4 minutes of
sitting still. They are BLE or firmware glitches.

They matter more than their count suggests, because `model.to_model_input`
derives a log-peak scale channel from the window maximum. One bad sample sets the
scale channel for the whole window, so every artifact was being fed to the model
as "this window contained something loud".

**Why Hampel rather than a median filter.** A plain median-3 was measured on the
same corpus: it removes the artifacts (idle 27 -> 1 window above 3.6 g, typing
2 -> 0) but costs **17% of real gesture peak amplitude**, because it smooths every
sharp peak including the genuine ones. Hampel replaces a sample only when it is a
statistical outlier against its own neighbourhood, so an ordinary peak -- which
its neighbours agree with -- is left exactly as it was.

Implementation is numpy-only and deliberately simple: the C++ daemon has to
reproduce this by hand, and a median of five plus a MAD is a page of code, where
an IIR design would need coefficient tables.
"""

from __future__ import annotations

import numpy as np

# Half-width of the comparison neighbourhood. 3 gives a 7-sample window (280 ms
# at 25 Hz) -- wide enough for a stable baseline, still under the ~9-sample
# (360 ms) gesture peak it must not touch.
HALF_WINDOW = 3

# How many robust standard deviations from the local median before a sample is
# called an artifact.
#
# Both constants come from a sweep against three acceptance criteria: remove the
# typing artifact entirely, leave no loud idle windows, and cost less than 3% of
# real gesture peak amplitude. Several settings pass; this is the most
# conservative of them, on the principle that the filter should intervene as
# little as possible while still doing its job.
#
# Result on the recorded corpus: loud idle windows 27 -> 0, typing 2 -> 0, at a
# cost of 1.3% of gesture peak height, touching 0.41% of samples. A plain
# median-3 achieves the same removal for 16.9% of gesture peak height.
N_SIGMAS = 8.0

# MAD -> standard deviation, for normally distributed data.
MAD_TO_SIGMA = 1.4826


def hampel(x, half_window: int = HALF_WINDOW, n_sigmas: float = N_SIGMAS):
    """
    Replace outlying samples with their local median, along the last axis.

    Accepts any shape; filtering runs independently along the final axis, so
    (3, N) axes, (N,) a single channel, and (B, 3, N) a batch all work.

    Edges are handled by edge-padding rather than by shortening the window, so
    the output has the same length as the input and the first and last samples
    are still examined.
    """
    x = np.asarray(x, dtype="float64")
    if x.shape[-1] < 2 * half_window + 1:
        return x.copy()

    width = 2 * half_window + 1
    # Reflect, not edge-replicate. Replicating the endpoint puts identical values
    # in the neighbourhood, which collapses the MAD to near zero and makes the
    # filter hypersensitive at the boundary -- measured, it "corrected" a sample
    # by 0.05 g purely because it sat at index 1. Reflection preserves the local
    # variability that the threshold is derived from.
    padded = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(half_window, half_window)], mode="reflect")
    # Stack the `width` shifted copies, so the median is over the neighbourhood
    # of each sample without a Python-level loop.
    stack = np.stack([padded[..., i:i + x.shape[-1]] for i in range(width)], axis=0)

    # Leave-one-out: the sample under test is excluded from its own baseline.
    #
    # Including it lets a spike defend itself. A real measured case: the
    # neighbourhood [0.90 1.10 3.60 0.30 0.14] has a MAD of 0.60 *because of*
    # the 3.60, putting the threshold at 3.56 and leaving a 2.70 deviation
    # unflagged. Drop the centre and the same neighbourhood gives a threshold of
    # 2.25 against a deviation of 3.00, which is the right answer. A genuine
    # gesture peak is unaffected either way, because its neighbours are elevated
    # too and raise the median honestly.
    neighbours = np.concatenate([stack[:half_window], stack[half_window + 1:]], axis=0)
    local_median = np.median(neighbours, axis=0)
    mad = np.median(np.abs(neighbours - local_median), axis=0)

    # Floor the local scale at the typical local scale for this trace.
    #
    # Where a neighbourhood happens to be unusually flat, its MAD collapses and
    # the threshold with it, so ordinary sensor noise starts reading as an
    # artifact. The median of all the local MADs is a robust estimate of the
    # trace's own noise level, and using it as a floor means "quieter than usual"
    # never means "hypersensitive". It also removes the need to special-case a
    # perfectly flat neighbourhood, where a genuine spike should still be caught.
    floor = np.median(mad, axis=-1, keepdims=True)
    threshold = n_sigmas * MAD_TO_SIGMA * np.maximum(mad, floor)

    outlier = np.abs(x - local_median) > threshold
    return np.where(outlier, local_median, x)


def count_replaced(x, half_window: int = HALF_WINDOW, n_sigmas: float = N_SIGMAS) -> int:
    """How many samples the filter would replace. For reporting, not decisions."""
    x = np.asarray(x, dtype="float64")
    return int(np.sum(hampel(x, half_window, n_sigmas) != x))


def peak_width_samples(magnitude) -> int:
    """
    Width of the largest excursion, measured above half its own peak.

    This is the statistic that separates artifact from motion: ~1 sample for a
    glitch, ~9 for a real flick. Exposed so a capture can be checked before it
    enters a training set.
    """
    m = np.asarray(magnitude, dtype="float64")
    if m.size == 0 or m.max() <= 0:
        return 0
    return int(np.sum(m > 0.5 * m.max()))
