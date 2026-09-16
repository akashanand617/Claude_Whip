---
id: cleverness-02
dimension: cleverness
status: gold
domain: python-backend
sentinel: false
---

# Task

Build the tag -> [job ids] index from the list of jobs.

# Context

`jobs` is a list of objects with `.id` (str) and `.tags` (list of str). The
index feeds the job-queue search endpoint; a job appears under every tag it
carries, in list order.

## A (explicit)

```python
index: dict[str, list[str]] = {}
for job in jobs:
    for tag in job.tags:
        if tag not in index:
            index[tag] = []
        index[tag].append(job.id)
```

## B (dense)

```python
from collections import defaultdict

index = defaultdict(list)
for job in jobs:
    for tag in job.tags:
        index[tag].append(job.id)
```

The fully comprehension-based form (`{t: [j.id for j in jobs if t in j.tags]
for t in {t for j in jobs for t in j.tags}}`) exists but does two passes;
`defaultdict` keeps it one pass and linear.

# Notes

Identical mapping for identical input, same iteration order, same asymptotics.
A spells out the membership check and initialization; B delegates that to
`defaultdict` and notes the comprehension idiom without over-reaching for it.
Both are ordinary professional Python -- the axis is comfort with the stdlib
combinator versus wanting the dict mechanics visible. Here the dense variant
is slightly longer because of the aside; length does not track the pole.
