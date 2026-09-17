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


# OFF (2026-09-16). The filter was built for single-sample BLE artifacts, but
# measured on the raw stream the narrow events it removes are real: ambient
# wear has 47-92 one-to-two-sample shocks above 3 g per hour and 88% of them
# deviate on two or three axes -- desk taps, not corrupt packets -- and a
# finger snap is exactly such a shock at 4-8 g. With the filter on, 19 of 21
# correctly performed double snaps lost one or both strokes, and wide strokes
# lost up to half their peak (per-axis judgement on a 3-D event). Those taps
# are the hard negatives the shock classes must learn against, so the stream
# is used raw. `hampel` and `StreamingHampel` stay for the record and for
# `enabled=True` experiments; `apply` and the engine honour this flag.
ENABLED = False


def apply(x):
    """The stream as the pipeline uses it: filtered when ENABLED, else a copy."""
    return hampel(x) if ENABLED else np.asarray(x, dtype="float64").copy()


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
    # Only an ISOLATED outlier is a glitch. A snap at the ring is a 1-2 sample
    # shock at 5-7 g -- physically the same width as a BLE glitch -- and the
    # first version of this filter removed it (median snap peak 5.8 g -> 1.1 g,
    # 2026-09-16). Now a sample is replaced only when both its neighbours sit
    # within the centre's own threshold of the centre's baseline: a glitch has
    # quiet neighbours, a shock does not. Cost: ambient loud windows rise by
    # ~40% (68 -> 94 per hour above 3 g), and the model learns those as `none`.
    neighbour_quiet = np.ones_like(outlier)
    neighbour_quiet[..., 1:] &= np.abs(x[..., :-1] - local_median[..., 1:]) <= threshold[..., 1:]
    neighbour_quiet[..., :-1] &= np.abs(x[..., 1:] - local_median[..., :-1]) <= threshold[..., :-1]
    return np.where(outlier & neighbour_quiet, local_median, x)


class StreamingHampel:
    """
    The same filter, one sample at a time, for the live engine.

    `push(sample) -> list[despiked]`. Empty until a full window of lookahead
    exists; the first non-empty push also flushes the leading `half_window`
    samples (unfiltered -- they never had a full backward neighbourhood, and the
    batch filter's reflection trick has no streaming equivalent), then exactly
    one filtered sample per push, `half_window` behind the input: a fixed
    3-sample (120 ms) lag. `drain()` flushes the unfiltered tail at stream end,
    so the output stream has the same length as the input.

    **Parity with the batch filter is close, not exact, and deliberately so.**
    The batch floor is the median of *every* local MAD in the trace, which needs
    the whole recording; a stream only has the past. This keeps a running median
    of the MADs seen so far, which converges to the batch value within seconds
    and is identical in the only case that matters -- a genuine spike, whose
    deviation dwarfs the threshold however the floor is estimated. The realtime
    engine's parity test therefore feeds the engine already-despiked samples, so
    the windowing/model/tracker chain is proven bit-exact and the despiker is
    checked separately against batch with a tolerance.
    """

    def __init__(self, half_window: int = HALF_WINDOW, n_sigmas: float = N_SIGMAS,
                 n_axes: int = 3, enabled: bool = True):
        self.enabled = enabled                    # False: same buffering and lag, no replacement
        self.half_window = half_window
        self.n_sigmas = n_sigmas
        self.n_axes = n_axes
        self._buf: list[np.ndarray] = []          # recent samples, each (n_axes,)
        self._mads: list[float] = []              # per-axis MADs seen, for the floor
        self._started = False                     # has the leading edge been flushed

    def _filter_centre(self) -> np.ndarray:
        """Filter the centre sample of the current (2*hw+1) buffer."""
        hw = self.half_window
        window = np.stack(self._buf, axis=1)                    # (n_axes, 2*hw+1)
        centre = window[:, hw]
        neighbours = np.concatenate([window[:, :hw], window[:, hw + 1:]], axis=1)
        med = np.median(neighbours, axis=1)
        mad = np.median(np.abs(neighbours - med[:, None]), axis=1)
        self._mads.append(float(np.median(mad)))
        floor = np.median(self._mads)
        threshold = self.n_sigmas * MAD_TO_SIGMA * np.maximum(mad, floor)
        # Isolated-outlier rule, identical to the batch filter: replace only
        # when both adjacent samples sit within the centre's threshold of the
        # centre's baseline. The buffer holds both neighbours already.
        outlier = np.abs(centre - med) > threshold
        quiet = (np.abs(window[:, hw - 1] - med) <= threshold) & (np.abs(window[:, hw + 1] - med) <= threshold)
        if not self.enabled:
            return centre.copy()
        return np.where(outlier & quiet, med, centre)

    def push(self, sample) -> list[np.ndarray]:
        self._buf.append(np.asarray(sample, dtype="float64"))
        if len(self._buf) < 2 * self.half_window + 1:
            return []
        out: list[np.ndarray] = []
        if not self._started:
            # The leading half_window samples pass through unfiltered, exactly
            # as the tail does in drain(): a truncated neighbourhood is the edge
            # hypersensitivity the batch filter avoids with reflection.
            out.extend(self._buf[:self.half_window])
            self._started = True
        out.append(self._filter_centre())
        self._buf.pop(0)
        return out

    def drain(self) -> list[np.ndarray]:
        """
        Emit the final `half_window` samples, unfiltered.

        They never accumulated a full forward neighbourhood, so filtering them
        would use a truncated window -- exactly the edge hypersensitivity the
        batch filter avoids with reflection. Passing them through untouched is
        the honest choice at the very end of a stream.
        """
        hw = self.half_window
        # A stream shorter than one window never started; everything unfiltered.
        tail = list(self._buf) if not self._started else (self._buf[-hw:] if hw else [])
        self._buf = []
        self._started = False
        return tail


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
