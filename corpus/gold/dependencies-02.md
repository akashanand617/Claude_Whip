---
id: dependencies-02
dimension: dependencies
status: gold
domain: python-cli
sentinel: false
---

# Task

Print the per-session summary (session, minutes, gestures, loss %) as an
aligned table in the terminal.

# Context

The summary command of the capture CLI. `rows` is a list of tuples,
`headers` a list of column names. The CLI currently has no third-party
dependencies.

## A (handroll)

Column widths from the data, `str.ljust` to pad -- no new dependency:

```python
def print_table(rows, headers):
    cells = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))
```

## B (library)

`tabulate` does the measuring and padding, and right-aligns numeric columns
automatically:

```python
from tabulate import tabulate

def print_table(rows, headers):
    print(tabulate(rows, headers=headers))
```

Adds `tabulate` to the environment (`pip install tabulate`).

# Notes

Both render the same rows as an aligned table with a header rule (tabulate's
default "simple" format matches the hand-rolled dashes). A keeps the CLI
dependency-free at the cost of ten lines of width bookkeeping; B adds a tiny
ubiquitous package and gets numeric alignment and other output formats for
free. The axis is the dependency itself, not effort or correctness.
