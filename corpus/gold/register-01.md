---
id: register-01
dimension: register
layer: agency
status: gold
domain: python-cli
sentinel: false
---

# Task

Add a `--since` flag to the report command.

# Context

The CLI already has `--until`, which takes either an ISO date or a relative
string like `7d`. The new flag is its mirror.

## A (curt)

`cli.py`, `report.py`.

`--until` parsing was inline in the command body. Pulled it out to
`_parse_when()`, both flags use it now.

`--since`: ISO date or relative (`7d`, `36h`). No default -- bare command
unchanged.

Bad value -> exit 2, message lists both accepted forms. Same as `--until` did.

`--since 8d --until 1d` on the sample log: 412 rows to 96.

3 tests added. 41 passed.

## B (composed)

I read `cli.py` and `report.py`.

The parsing for `--until` was written inline in the command body, so I pulled
it out into `_parse_when()` and both flags now go through it.

`--since` accepts either an ISO date or a relative string such as `7d` or
`36h`. It has no default, so the bare command behaves exactly as it did before.

An unparseable value exits 2 with a message listing both accepted forms, which
is the behaviour `--until` already had.

Running `--since 8d --until 1d` against the sample log narrows 412 rows to 96.

I added three tests, and all 41 pass.

# Notes

This axis declares no conditioner, so both items sit in the same unconditioned
situation. The two variants carry exactly the same content, point for point and
in the same order: same two files read, same extraction of `_parse_when()`,
same accepted formats, same absence of a default, same exit code and error
message, same sample-log numbers, same test counts. Nothing is said in one that
is not said in the other, so a reader cannot prefer one for being more
informative. B is not padding -- the sentences carry no filler clauses -- and A
is not dropping detail, only articles and subjects. The length difference is
what clipping costs, and it is the axis rather than a leak. Pairs with
`register-02`, which puts the same two styles in the opposite slots.
