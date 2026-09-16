---
id: verbosity-05
dimension: verbosity
status: gold
domain: python-tooling
sentinel: false
---

# Task

What is the guard at the bottom of `probe/report.py` actually for?

```python
if __name__ == "__main__":
    main()
```

# Context

Quick question while reading through the probe scripts; every one of them
ends with this same block.

## A (terse)

It makes `main()` run only when the file is executed directly
(`python -m probe.report`), not when the module is imported.

## B (explanatory)

Python sets `__name__` per module: when a file runs as the entry point
(`python probe/report.py` or `python -m probe.report`) it gets the value
`"__main__"`, but when it is imported it gets its dotted module name,
`"probe.report"`. The guard compares against the first case, so `main()`
runs on direct execution and stays quiet on import.

Without it, importing the module would execute `main()` as a side effect —
`from probe.report import format_table` in a test would generate a full
report just to borrow one helper. It also matters for multiprocessing on
Windows and macOS: the default `spawn` start method re-imports the main
module in every worker process, so an unguarded `main()` that creates
workers would recurse, spawning workers from workers until it errors out.

So the block is the line between "this file is a library" and "this file is
a program" — the same file gets to be both.

# Notes

Identical answer — the guard distinguishes direct execution from import.
The axis is whether the mechanism (`__name__` assignment) and the failure
modes without the guard (import side effects, spawn re-import) are wanted
alongside it. B's extra content is correct, not padding.
