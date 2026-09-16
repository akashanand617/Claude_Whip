---
id: idiom-02
dimension: idiom
status: gold
domain: python-tooling
sentinel: false
---

# Task

Add a `load_manifest(capture_dir)` function to `captures.py` that reads and
returns the `manifest.json` in a capture directory, raising if it's missing.

# Context

A legacy module from the first capture tooling. Every function in it builds
paths with `os.path.join`, formats strings with `%`, and carries no type
annotations; there is no `pathlib` or f-string anywhere in the file. `os.path`
and `json` are already imported at the top.

## A (conform)

Matches every neighbor in the file — `os.path`, `%` formatting, no
annotations:

```python
def load_manifest(capture_dir):
    path = os.path.join(capture_dir, "manifest.json")
    if not os.path.isfile(path):
        raise FileNotFoundError("no manifest.json in %s" % capture_dir)
    with open(path) as fh:
        manifest = json.load(fh)
    return manifest
```

Uses the imports already at the top of the module, so nothing else changes;
it reads like the `load_index()` two functions above it.

## B (modernize)

Written to current practice:

```python
def load_manifest(capture_dir: str | Path) -> dict:
    path = Path(capture_dir) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"no manifest.json in {capture_dir}")
    return json.loads(path.read_text())
```

This is the module's first `pathlib`, f-string, and annotation; the
neighboring functions keep `os.path` until they're migrated.

# Notes

Identical logic and identical behavior: same path, same existence check, same
exception with the same message content, same parsed dict returned. A extends
the file's dated idiom consistently; B writes the modern form and says so.
Neither is buggy — conform is consistent code, not worse code.
