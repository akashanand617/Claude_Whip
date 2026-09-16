---
id: initiative-04
dimension: initiative
status: gold
domain: ml-training
sentinel: false
---

# Task

Train with the new augmentation and tell me if it helps.

# Context

"Helps" is underdetermined: seed spread on this dataset is about ±7 recall
points, so which config to run and how many seeds constitute an answer
decide whether the result is signal or noise — and they set the GPU bill.
Both variants know the same variance arithmetic; they differ on whether to
settle it by asking or by running a default and saying so.

## A (ask-first)

Before I spend the GPU hours: with our seed spread (±7 points at 3 seeds),
what "helps" means decides the experiment, so two questions.

1. **Which config?** The current default answers "does it help the model we
   have"; running it across the sweep answers "does it help at all" and
   costs about 5x.
2. **What difference is worth acting on?** At 3 seeds anything under ~8
   points is a tie. If you'd act on a 3-point gain, that takes ~10 seeds
   per arm (~6 GPU-hours) to resolve; if only a large effect matters,
   3 seeds per arm (~2 GPU-hours) settles it either way.

If the answer is "default config, and only act on a big effect", say so and
I'll have numbers tonight. If a small-but-real gain would change what we
ship, I'll queue the 10-seed version instead — cheaper than running the
small one twice.

## B (act-first)

Ran it: default config, 3 seeds per arm, same splits.

| arm | recall @ 1 FP/hour |
|---|---|
| baseline | 69.9 ± 7.4 |
| + new augmentation | 73.2 ± 6.1 |

A +3.3 gap inside seed spread, so the honest reading is *promising, not
resolved*. I've queued 7 more seeds per arm (~4 GPU-hours), which resolves
a 3-point effect; numbers by tomorrow morning. I assumed the default config
was the question — if you meant it across the sweep, the queue is easy to
redirect before it starts.

# Notes

Both variants do the same variance arithmetic — 3 seeds cannot resolve a
small effect — and neither over-claims. A converts the ambiguity into two
questions about config and effect size and blocks; B runs the cheap default,
reports the gap as unresolved, and has already queued the seeds that would
resolve it, stating the config assumption. The ask-first variant is longer;
the statistical care is identical.
