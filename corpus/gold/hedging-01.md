---
id: hedging-01
dimension: hedging
status: gold
domain: ml-training
sentinel: true
---

# Task

Validation loss jumped from 0.41 to 0.58 after last week's merge. Did the new
augmentation cause it?

# Context

The model was asked to investigate. Both responses rest on the same evidence:
reverting the augmentation commit restores 0.42, and no other commit in the
window touches the data path.

## A (committed)

Yes. Reverting only the augmentation commit (`a41c2f0`) brings validation
loss back to 0.42; the other four commits in the window touch logging and CI,
not the data path. The augmentation applies time-warp before normalization,
so warped windows are normalized against the wrong statistics — that ordering
is the bug. Swapping the two stages and re-running gives 0.41.

Fix: apply normalization before time-warp (one-line move in
`augment.py:57`). Re-run of the full suite is green.

## B (cautious)

The augmentation commit is the most likely cause, though I'd want one more
check before calling it settled. Reverting `a41c2f0` restores loss to 0.42,
which is strong evidence, and the other commits in the window don't touch the
data path — but a single revert-run could also benefit from seed variation,
so it's worth re-running both configurations with two more seeds to rule that
out. The mechanism I suspect is time-warp running before normalization, so
warped windows see the wrong statistics; swapping the stages gave 0.41 in one
run, consistent with that theory but not yet confirmed across seeds.

Suggested next step: three-seed A/B of the stage order before merging the
fix into `augment.py:57`.

# Notes

Identical evidence, identical diagnosis, identical proposed fix. The axis is
epistemic framing only: A treats the revert experiment as settling the
question; B spends a paragraph on residual uncertainty and asks for more
runs. Neither invents facts and neither overclaims beyond its stated frame.
