---
id: abstraction-04
dimension: abstraction
status: gold
domain: scripting
sentinel: false
---

# Task

The report needs both a plain-text and a CSV rendering of the same rows.

# Context

A reporting script that already builds its rows as a list of dicts sharing
the same keys. The caller picks the format from a `--format` flag.

## A (concrete)

Two functions:

```python
def render_text(rows: list[dict]) -> str:
    cols = list(rows[0])
    lines = ["  ".join(cols)]
    for r in rows:
        lines.append("  ".join(str(r[c]) for c in cols))
    return "\n".join(lines)

def render_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()
```

The flag handler calls `render_text(rows)` or `render_csv(rows)`.

## B (generalized)

A Renderer protocol, so a new format plugs in without touching the callers:

```python
class Renderer(Protocol):
    def render(self, rows: list[dict]) -> str: ...

class TextRenderer:
    def render(self, rows: list[dict]) -> str:
        cols = list(rows[0])
        lines = ["  ".join(cols)]
        for r in rows:
            lines.append("  ".join(str(r[c]) for c in cols))
        return "\n".join(lines)

class CsvRenderer:
    def render(self, rows: list[dict]) -> str:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()

def get_renderer(fmt: str) -> Renderer:
    return {"text": TextRenderer(), "csv": CsvRenderer()}[fmt]
```

The flag handler calls `get_renderer(fmt).render(rows)`.

# Notes

The rendering bodies are identical, so both variants emit byte-identical text
and CSV output for the same rows. B wraps them in a protocol, two classes,
and a factory that two formats do not yet need. The axis is whether the
pluggable structure is welcome now or should wait for a third format.
