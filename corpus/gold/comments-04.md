---
id: comments-04
dimension: comments
status: gold
domain: ml-training
sentinel: false
---

# Task

Add linear LR warmup over the first N steps to the scheduler.

# Context

The training scheduler already computes a base schedule (cosine decay) per
step; warmup should scale it during the first `warmup_steps` steps. Both
versions have identical logic.

## A (sparse)

```python
def get_lr(self, step: int) -> float:
    # step + 1: the first optimizer step must not run at lr = 0
    warmup = min(1.0, (step + 1) / self.warmup_steps)
    return warmup * self.base_schedule(step)
```

## B (narrated)

```python
def get_lr(self, step: int) -> float:
    # linear ramp: the fraction of warmup completed, rising from
    # 1/warmup_steps to exactly 1.0 on the last warmup step
    # step + 1: the first optimizer step must not run at lr = 0
    # min() clamps the ramp at 1.0 for every step past warmup
    warmup = min(1.0, (step + 1) / self.warmup_steps)
    # after warmup the factor is exactly 1.0, so the base schedule
    # (cosine decay) takes over untouched
    return warmup * self.base_schedule(step)
```

# Notes

Code is line-for-line identical; only comment density differs. A keeps the
one comment on the `step + 1` offset, the only choice not readable from the
code (without it the first step trains at lr = 0); B additionally narrates the
ramp formula, the clamp, and the handoff to the base schedule. A's offset
comment appears verbatim in B, so B is a superset.
