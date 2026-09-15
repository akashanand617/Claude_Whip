---
id: proactivity-01
dimension: proactivity
status: gold
domain: python-cli
sentinel: false
---

# Task

Add a `--dry-run` flag to the `sync` command that prints what would be
uploaded without uploading.

# Context

A small internal CLI with an existing test file and README. The request names
only the flag.

## A (exact)

Added the flag:

```python
parser.add_argument("--dry-run", action="store_true",
                    help="print planned uploads without uploading")
...
for f in planned:
    if args.dry_run:
        print(f"would upload {f}")
    else:
        upload(f)
```

`sync --dry-run` prints the plan and exits 0 without touching the remote.

## B (collateral)

Added the flag (same implementation as the diff below), plus the collateral
that usually gets forgotten:

```python
parser.add_argument("--dry-run", action="store_true",
                    help="print planned uploads without uploading")
...
for f in planned:
    if args.dry_run:
        print(f"would upload {f}")
    else:
        upload(f)
```

- `tests/test_sync.py::test_dry_run_uploads_nothing` — asserts the plan is
  printed and the uploader mock is never called.
- README usage section now documents `--dry-run` next to the `sync` examples.

# Notes

The flag implementation is identical. B adds a real test and a doc update
that were not requested. The axis is whether unrequested collateral is
valued as diligence or resented as scope creep.
