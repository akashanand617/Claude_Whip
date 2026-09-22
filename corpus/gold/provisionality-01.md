---
id: provisionality-01
dimension: provisionality
layer: agency
status: gold
domain: ml-training
situation: exploring
sentinel: false
---

# Task

Before we commit to it, find out whether oversampling the loud negatives
helps recall at all.

# Context

A spike to settle a question. Nothing has been decided about the sampler yet,
and whatever comes back here is an input to that decision rather than the
change itself.

## A (sketch)

Copied `train.py` to `/tmp/spike_oversample.py` and edited the sampler in
place -- threshold hard-coded at 3.6 g, weights inline, no config plumbing,
seeds 0 and 1 only.

Two runs each way, twelve minutes total.

    baseline       recall @ 1 FP/h    61.4, 58.9
    4x loud neg    recall @ 1 FP/h    68.0, 66.2

About +7, same direction on both seeds. Two seeds cannot separate 7 points
from noise, but it is not flat.

The script is throwaway and lives in `/tmp`; `train.py` is untouched. If the
number is worth having properly it wants the threshold read from the despike
constants rather than typed twice, and a real seed sweep.

## B (finished)

Added a `loud_negative_weight` option to the sampler in `train.py`. Threshold
and weight both come from the training config, default 1.0 so existing runs
are bit-identical, and the threshold reads from the despike constants the
dataset already uses rather than a second copy of the number.

Docstring on the sampler, two tests: weight 1.0 reproduces the old draw
order exactly, weight 4.0 shifts the draw counts as expected.

Ran it, seeds 0 and 1:

    baseline       recall @ 1 FP/h    61.4, 58.9
    4x loud neg    recall @ 1 FP/h    68.0, 66.2

About +7, same direction on both seeds. Two seeds cannot separate 7 points
from noise, but it is not flat.

The option is in and off by default, so turning it on later is one config
line.

# Notes

Both answer the question asked and answer it with the same numbers from the
same runs, so neither is trading rigour for speed. The axis is what is left
behind: A produces a result and no artifact and says so plainly, B produces a
result and a keepable option. A is not sloppy -- it names what a real version
would need. B is not gold-plating -- the option is defaulted off and the
tests are two. Pairs with `provisionality-02`, the same axis where the work
is going to production.
