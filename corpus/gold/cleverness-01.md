---
id: cleverness-01
dimension: cleverness
status: gold
domain: python-tooling
sentinel: false
---

# Task

Group these parsed log records by `request_id`, preserving order within each
group.

# Context

`records` is a list of dicts, already parsed. Part of a log-analysis script.

## A (explicit)

```python
groups: dict[str, list[dict]] = {}
for record in records:
    request_id = record["request_id"]
    if request_id not in groups:
        groups[request_id] = []
    groups[request_id].append(record)
```

## B (dense)

```python
from collections import defaultdict

groups = defaultdict(list)
for r in records:
    groups[r["request_id"]].append(r)
```

Or, if the records are already sorted by request id,
`itertools.groupby(records, key=itemgetter("request_id"))` avoids building
the dict at all.

# Notes

Identical result for identical input. A spells out the membership check with
long names; B reaches for `defaultdict` and mentions the `groupby` idiom.
Both are common professional Python; the axis is taste for density, not
correctness or even asymptotics.
