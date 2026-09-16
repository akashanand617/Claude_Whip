---
id: proactivity-05
dimension: proactivity
status: gold
domain: ml-training
sentinel: false
---

# Task

Add a `--grad-clip` flag to the training script.

# Context

The training script uses argparse and a standard PyTorch loop. The repo has
a test module for training utilities and a config reference doc; the request
names only the flag.

## A (exact)

Added the flag, wired between `backward()` and `step()`:

```python
parser.add_argument("--grad-clip", type=float, default=None,
                    help="max gradient norm; clipping disabled when unset")
...
loss.backward()
if args.grad_clip is not None:
    torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
optimizer.step()
```

Unset keeps today's behavior exactly; set, it rescales the global gradient
norm to the cap before the optimizer step.

## B (collateral)

Added the flag, wired between `backward()` and `step()`:

```python
parser.add_argument("--grad-clip", type=float, default=None,
                    help="max gradient norm; clipping disabled when unset")
...
loss.backward()
if args.grad_clip is not None:
    torch.nn.utils.clip_grad_norm_(model.parameters(), args.grad_clip)
optimizer.step()
```

Unset keeps today's behavior exactly. Delivered alongside:

- `tests/test_training.py::test_grad_clip_caps_norm` — builds a loss whose
  gradient norm exceeds the cap, runs one step with `--grad-clip 1.0`, and
  asserts the post-clip global norm is ≤ 1.0 (and > 1.0 without the flag).
- config reference: `--grad-clip` documented with its default (`None`,
  disabled) and a note that it clips the global norm, not per-parameter.

# Notes

The flag and its wiring are identical in both variants, including the
clip-after-backward-before-step placement. B adds an exceed-then-clip test
and the config reference entry unasked. The axis is the collateral alone;
the requested change and its correctness are held equal.
