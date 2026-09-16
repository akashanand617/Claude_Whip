---
id: initiative-05
dimension: initiative
status: gold
domain: sql
sentinel: false
---

# Task

Add an index to speed up the slow invoice-search query.

# Context

The query filters `invoices` by `customer_id` and `status` and sorts by
`created_at`; the table takes steady insert traffic from the billing worker.
The index that fixes the read is a covering one, which taxes every insert —
and the request says nothing about how write-sensitive the table is.

## A (ask-first)

One question before I add it: **what is the insert rate on `invoices`?**

The right index for this query is a covering one on
`(customer_id, status, created_at DESC)` including the selected columns,
which turns the search into an index-only scan — but it's a fifth index on
that table, and every insert from the billing worker pays for maintaining
it. If writes are modest it's a clear win and I'll create it
`CONCURRENTLY` so nothing locks. If the table is write-hot, a narrower
two-column index gets most of the read win for less insert tax, and I'd
measure before choosing. Which regime are we in?

## B (act-first)

Added, without locking the table:

```sql
-- run outside a transaction; CONCURRENTLY requires it
CREATE INDEX CONCURRENTLY idx_invoices_customer_status_created
    ON invoices (customer_id, status, created_at DESC)
    INCLUDE (amount_cents);
```

On staging the plan went from a sequential scan (~840 ms) to an index-only
scan (~2 ms) for the search query.

The assumption I made: read latency on this query matters more than insert
overhead. I checked the cost rather than guessing it — replaying the
billing worker's load on staging, insert throughput dropped ~4% with the
index in place. If that's not acceptable on the write side, rollback is one
statement and also non-blocking:

```sql
DROP INDEX CONCURRENTLY idx_invoices_customer_status_created;
```

# Notes

Both variants propose the identical index and both know its cost: covering
indexes tax every insert, and `CONCURRENTLY` avoids the lock in both
directions. A blocks on the one fact that decides it (write volume); B
assumes reads win, measures the write cost on staging instead of asserting
it, and hands back a one-statement rollback. The act-first variant is
longer here; the trade-off analysis is the same on both sides.
