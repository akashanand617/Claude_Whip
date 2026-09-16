---
id: dependencies-05
dimension: dependencies
status: gold
domain: ml-training
sentinel: false
---

# Task

Show progress during the multi-hour training loop: step, loss, and time
remaining.

# Context

The training script runs interactively during development and under nohup
on the box overnight, where stdout goes to a log file. `loader` yields
`total_steps` batches.

## A (handroll)

A carriage-return print every 50 steps; no dependency:

```python
t0 = time.time()
for step, batch in enumerate(loader, 1):
    loss = train_step(batch)
    if step % 50 == 0:
        eta = (time.time() - t0) / step * (total_steps - step)
        print(f"\rstep {step}/{total_steps}  loss {loss:.4f}  "
              f"eta {eta/60:.0f}m", end="", flush=True)
```

## B (library)

Wrap the loader in `tqdm`; the rate estimate is smoothed over a moving
window rather than averaged from step one, so the ETA stays honest after
warmup, and when stdout is not a TTY (the overnight log) it degrades to
occasional plain lines instead of filling the file with carriage returns:

```python
from tqdm import tqdm

pbar = tqdm(loader, total=total_steps, desc="train",
            unit="step", dynamic_ncols=True)
for batch in pbar:
    loss = train_step(batch)
    pbar.set_postfix(loss=f"{loss:.4f}")
```

Adds `tqdm` to the training environment (`pip install tqdm`).

# Notes

Both report step, loss, and time remaining on a single updating terminal
line. A is eight owned lines with a straightforward whole-run-average ETA;
B adds the standard progress dependency and gets smoothed rates, non-TTY
degradation, and terminal-width handling for free. The axis is the
dependency, not the quality of either implementation.
