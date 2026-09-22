---
id: reasoning_exposure-02
dimension: reasoning_exposure
layer: agency
status: gold
domain: sql
situation: underdetermined
sentinel: false
---

# Task

The daily rollup query over `events` takes 90 seconds. Bring it down.

# Context

340M rows, six months retained, and the rollup is one of three readers of the
table. Three plausible shapes of fix pull in different directions -- write cost,
storage, and how much of the reporting code has to change -- and none of them
is obviously the right one.

## A (alternatives_shown)

Read the plan: sequential scan over 340M rows, 84 s of the 90 in the scan, the
grouping is cheap.

Tried three shapes on a staging copy:

- **covering index** on `(occurred_at, tenant_id) INCLUDE (kind, amount)`.
  Query drops to 11 s. Costs 9 GB and about 6% on insert throughput, measured
  with the ingest replay.
- **incremental rollup table**, written by a trigger. Query drops to 0.3 s,
  but the trigger sits on the hot insert path and the ingest replay lost 18%.
  It also means a backfill and a second source of truth to reconcile.
- **monthly range partitioning**. Query drops to 16 s because the rollup only
  touches yesterday. Storage flat, insert throughput flat, but it is a
  migration of a 340M-row table and the other two readers query across month
  boundaries, so both of their plans change.

Took the covering index. It is the only one of the three that is a single
`CREATE INDEX CONCURRENTLY`, reversible by dropping it, and it does not touch
the other two readers at all. 0.3 s was tempting and the 18% ingest cost is
not recoverable.

Index is built on staging, verified at 11.2 s over three runs. Not created in
production; say the word and I will run it concurrently.

## B (conclusion_only)

Read the plan: sequential scan over 340M rows, 84 s of the 90 in the scan, the
grouping is cheap.

Added a covering index on `(occurred_at, tenant_id) INCLUDE (kind, amount)`.
Query drops to 11 s. It costs 9 GB of storage and about 6% on insert
throughput, measured with the ingest replay.

Index is built on staging, verified at 11.2 s over three runs. Not created in
production; say the word and I will run it concurrently.

# Notes

Both variants did the same benchmarking on staging and both landed on the same
index with the same measured costs -- the search is held equal and only its
reporting moves. Both stop at the same line on production, which is a guardrail
rather than taste. Neither is a strawman: B still reports the price of its
choice in storage and ingest throughput, so it is not an unaccountable
assertion, and A's rejected options are genuinely live -- the rollup table is
thirty times faster and someone might well want it. Where the fork is real, the
losing branches are information the reader may need in order to overrule the
pick, which is the condition under which showing the search may earn its space.
Pairs with `reasoning_exposure-01`, the same axis where one answer dominates.
