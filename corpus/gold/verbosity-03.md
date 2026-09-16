---
id: verbosity-03
dimension: verbosity
status: gold
domain: sql
sentinel: false
---

# Task

Why is this LEFT JOIN dropping customers who have no invoices? I expected
them with NULL totals.

```sql
SELECT c.id, i.total
FROM customers c
LEFT JOIN invoices i ON i.customer_id = c.id
WHERE i.status = 'paid';
```

# Context

A reporting query in the billing service. The report should list every
customer, padding the invoice columns with NULLs where there are none.

## A (terse)

The WHERE runs after the join, and `i.status` is NULL on the padded rows, so
`NULL = 'paid'` filters them out — the LEFT JOIN degenerates into an inner
join. Move the predicate into the ON clause:

```sql
LEFT JOIN invoices i ON i.customer_id = c.id AND i.status = 'paid'
```

## B (explanatory)

A LEFT JOIN is evaluated in two stages: first the join builds rows, padding
with NULLs for customers that match no invoice; then the WHERE filters the
result. With two customers — 7 has a paid invoice, 9 has none — the join
produces:

| c.id | i.total | i.status |
|---|---|---|
| 7 | 120.00 | paid |
| 9 | NULL | NULL |

Then `WHERE i.status = 'paid'` evaluates `NULL = 'paid'`, which is not TRUE,
so customer 9's row is discarded — the filter has silently turned the outer
join into an inner one.

A predicate in ON behaves differently: it decides which invoices *match*,
and a customer matching nothing still gets its NULL-padded row. So the fix
is to move it:

```sql
LEFT JOIN invoices i ON i.customer_id = c.id AND i.status = 'paid'
```

Customer 9 now survives as `(9, NULL)`; the rule of thumb is ON filters the
right table, WHERE filters the joined result.

# Notes

Identical diagnosis and byte-identical fixed line; the axis is whether the
join-then-filter evaluation order and the worked two-row example are wanted
alongside it. B's extra content is correct SQL semantics, not padding.
