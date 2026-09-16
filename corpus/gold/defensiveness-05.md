---
id: defensiveness-05
dimension: defensiveness
status: gold
domain: ml-training
sentinel: false
---

# Task

Write the loader for our internal `.npz` capture archives: keys `xyz`
(N x 3, int16 counts), `t` (N, float64 seconds), `labels` (N, uint8).

# Context

The archives are written by our own capture pipeline and read only by our
own training scripts. Loading happens once at the start of a run.

## A (trusting)

```python
def load_capture(path):
    arc = np.load(path)
    return arc["xyz"], arc["t"], arc["labels"]
```

A wrong path raises `FileNotFoundError` naming the file; a missing key
raises `KeyError` naming the key, with the loading call and its `path`
argument sitting right there in the traceback. Our own writer produced the
file, so a malformed archive is a pipeline bug to fix, not a case to handle.

## B (defensive)

```python
KEYS = {"xyz": ((None, 3), np.int16), "t": ((None,), np.float64),
        "labels": ((None,), np.uint8)}

def load_capture(path):
    arc = np.load(path)
    for key, (shape, dtype) in KEYS.items():
        if key not in arc:
            raise ValueError(f"{path}: missing key {key!r}, "
                             f"expected {sorted(KEYS)}")
        a = arc[key]
        if a.dtype != dtype or a.ndim != len(shape) or any(
                s is not None and s != d for s, d in zip(shape, a.shape)):
            raise ValueError(f"{path}: {key} is {a.dtype}{a.shape}, "
                             f"expected {np.dtype(dtype).name} {shape}")
    return arc["xyz"], arc["t"], arc["labels"]
```

Any mismatch raises one message naming the file, the key, and what was
expected, before the arrays reach the training code.

# Notes

On a well-formed archive both return the same three arrays. The axis is only
how a malformed one surfaces: numpy's own exceptions and the traceback,
versus a single curated message with file, key, and expected shape. Both
fail loudly before training starts; neither returns partial or repaired
data.
