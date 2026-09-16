---
id: cleverness-05
dimension: cleverness
status: gold
domain: sql
sentinel: false
---

# Task

Get each customer's most recent invoice.

# Context

Postgres. `invoices(id, customer_id, created_at, total_cents)`; `created_at`
is set from a monotonic clock at insert, so it is distinct within a customer
and "most recent" is unique. One row per customer with at least one invoice.

## A (explicit)

```sql
SELECT i.*
FROM invoices i
JOIN (
    SELECT customer_id, MAX(created_at) AS latest_at
    FROM invoices
    GROUP BY customer_id
) latest
  ON i.customer_id = latest.customer_id
 AND i.created_at = latest.latest_at;
```

## B (dense)

```sql
SELECT *
FROM (
    SELECT i.*,
           ROW_NUMBER() OVER (
               PARTITION BY customer_id
               ORDER BY created_at DESC
           ) AS rn
    FROM invoices i
) ranked
WHERE rn = 1;
```

# Notes

Same result set on the stated schema: `created_at` is distinct per customer,
so the max-timestamp join and the row-number filter select the same rows --
without that guarantee they would diverge on ties, which is why the context
pins it. A builds the answer from GROUP BY pieces anyone can read; B reaches
for the window-function idiom, which is the standard modern form but assumes
the reader parses `PARTITION BY ... ORDER BY ... rn = 1` as one unit. The
two variants are almost exactly the same length, so length carries no signal
about the pole here.
