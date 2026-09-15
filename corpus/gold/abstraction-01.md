---
id: abstraction-01
dimension: abstraction
status: gold
domain: python-tooling
sentinel: false
---

# Task

We format byte sizes in two places (`report.py` and `drain.py`) and they
disagree (one says `1.5MB`, the other `1.50 MiB`). Make them consistent.

# Context

A diagnostic tool suite. Two call sites today; conceivably more later.

## A (concrete)

One function, both call sites use it:

```python
def format_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"
```

`report.py` and `drain.py` now both call `format_bytes`.

## B (generalized)

A small formatting module, so future quantities (rates, durations) live in one
place and units are configurable:

```python
class QuantityFormatter:
    def __init__(self, units: list[str], base: float, precision: int = 1):
        self.units, self.base, self.precision = units, base, precision

    def __call__(self, n: float) -> str:
        for unit in self.units[:-1]:
            if n < self.base:
                return f"{n:.{self.precision}f} {unit}"
            n /= self.base
        return f"{n:.{self.precision}f} {self.units[-1]}"

format_bytes = QuantityFormatter(["B", "KiB", "MiB", "GiB", "TiB"], 1024)
format_rate = QuantityFormatter(["Hz", "kHz"], 1000, precision=2)
```

`report.py` and `drain.py` both call `format_bytes`; `format_rate` is ready
for the rate summaries.

# Notes

Both resolve the inconsistency identically at the two real call sites and
produce identical byte strings. B adds structure and a speculative second
formatter that nothing requested. The axis is whether that up-front generality
is welcome or premature.
