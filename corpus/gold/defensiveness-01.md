---
id: defensiveness-01
dimension: defensiveness
status: gold
domain: python-cli
sentinel: false
---

# Task

Write `load_config(path)` for the CLI — it reads a JSON file with keys
`device`, `rate`, and optional `out_dir`.

# Context

An internal tool used only by its author. The config file is written by hand.

## A (trusting)

```python
def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)
    cfg.setdefault("out_dir", "data")
    return cfg
```

A missing file or malformed JSON raises with Python's own traceback, which
already names the file and the parse position.

## B (defensive)

```python
REQUIRED = ("device", "rate")

def load_config(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"config not found: {p}")
    try:
        cfg = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"config is not valid JSON: {p} ({e})")
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise SystemExit(f"config missing keys: {', '.join(missing)}")
    if not isinstance(cfg["rate"], (int, float)) or cfg["rate"] <= 0:
        raise SystemExit(f"rate must be a positive number, got {cfg['rate']!r}")
    cfg.setdefault("out_dir", "data")
    return cfg
```

Every failure mode exits with a one-line message naming exactly what to fix.

# Notes

On a valid config the two return identical dicts. The axis is how failures
surface: raw traceback versus curated messages. Both are defensible for an
internal single-user tool; neither hides an error.
