---
id: idiom-04
dimension: idiom
status: gold
domain: ml-training
sentinel: false
---

# Task

Set up the config handling for the new `evaluate.py` script: it needs
`--checkpoint` (required), `--split` (default `val`), and `--batch-size`
(default 64).

# Context

The repo's six existing scripts all build a parser in `parse_args()` and pass
the bare argparse `Namespace` through every function (`train(args)`,
`export(args)`, ...). There are no dataclasses or typed configs anywhere in
the repo.

## A (conform)

The pattern the other six scripts use:

```python
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--split", default="val")
    p.add_argument("--batch-size", type=int, default=64)
    return p.parse_args()

def main():
    args = parse_args()
    evaluate(args)
```

`evaluate()` reads `args.checkpoint` etc., exactly as `train()` and
`export()` do theirs.

## B (modernize)

A typed config, with argparse kept at the edge:

```python
@dataclass(frozen=True)
class EvalConfig:
    checkpoint: str
    split: str = "val"
    batch_size: int = 64

def parse_args() -> EvalConfig:
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--split", default="val")
    p.add_argument("--batch-size", type=int, default=64)
    ns = p.parse_args()
    return EvalConfig(ns.checkpoint, ns.split, ns.batch_size)

def main():
    cfg = parse_args()
    evaluate(cfg)
```

This is the repo's first dataclass config and diverges from the other six
scripts; `evaluate()` gets attribute access with types, and the `Namespace`
never leaves `parse_args()`.

# Notes

Same three flags, same defaults, same required-ness, and `evaluate()`
receives an object with identically named attributes either way — the logic
is the same to the last flag. A keeps the repo uniform; B introduces the
modern structure and names the divergence. Both are working, defensible
choices.
