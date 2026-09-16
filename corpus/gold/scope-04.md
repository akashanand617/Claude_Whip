---
id: scope-04
dimension: scope
status: gold
domain: ml-training
sentinel: false
---

# Task

We save optimizer state in checkpoints now — bump the checkpoint format
version and keep old checkpoints loadable.

# Context

`checkpoint.py` in the training repo. `CKPT_VERSION` is 3, and
`load_checkpoint` has accumulated one sequential shim per past bump: v1
checkpoints get a step counter, v2 get the DataParallel prefix stripped. The
trainer already treats `optimizer=None` as start-fresh.

## A (minimal)

```python
-CKPT_VERSION = 3
+CKPT_VERSION = 4
```

and one more shim at the end of the existing chain:

```python
     if ckpt["version"] <= 2:
         ckpt["model"] = _strip_module_prefix(ckpt["model"])
+    if ckpt["version"] <= 3:
+        ckpt["optimizer"] = None  # pre-4: no optimizer state saved
     ckpt["version"] = CKPT_VERSION
```

Old checkpoints load with `optimizer=None` and the trainer starts the
optimizer fresh, as it already does today.

## B (opportunistic)

```python
-CKPT_VERSION = 3
+CKPT_VERSION = 4
```

and, since I was in the file, the accumulated if-chain is now a
version-to-upgrade table, so the next bump is one entry:

```python
_UPGRADES = {  # version -> in-place upgrade to version + 1
    1: lambda c: c.update(step=0),
    2: lambda c: c.update(model=_strip_module_prefix(c["model"])),
    3: lambda c: c.update(optimizer=None),  # pre-4: no optimizer state saved
}

def load_checkpoint(path):
    ckpt = torch.load(path)
    for v in range(ckpt["version"], CKPT_VERSION):
        _UPGRADES[v](ckpt)
    ckpt["version"] = CKPT_VERSION
    return ckpt
```

Old checkpoints load with `optimizer=None` exactly as before; the two existing
shims compute the same thing they always did.

# Notes

The version bump is byte-identical and the new v3 shim has identical
semantics in both (`optimizer=None`). B additionally restructures the
existing, unmentioned shim chain without changing what any shim computes —
every version 1-4 loads to the same dict under both variants. The axis is
whether that unrequested refactor of adjacent code is welcome.
