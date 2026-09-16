---
id: idiom-05
dimension: idiom
status: gold
domain: sql
sentinel: false
---

# Task

Add the `refunds` table to the billing schema: one row per refund, linked to
an invoice and a customer, with an amount in cents, an optional reason, and a
creation timestamp.

# Context

The existing schema abbreviates every column name: `invoices` has
`amt_cents`, `cust_id`, `crtd_at`; foreign keys elsewhere are `invc_id`; a
free-text column is `rsn`. Nothing in the schema uses full words.

## A (conform)

Follows the schema's abbreviations:

```sql
CREATE TABLE refunds (
    id              BIGSERIAL PRIMARY KEY,
    invc_id         BIGINT NOT NULL REFERENCES invoices(id),
    cust_id         BIGINT NOT NULL REFERENCES customers(id),
    rfnd_amt_cents  INTEGER NOT NULL CHECK (rfnd_amt_cents > 0),
    rsn             TEXT,
    crtd_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## B (modernize)

Full names, current convention:

```sql
CREATE TABLE refunds (
    id                   BIGSERIAL PRIMARY KEY,
    invoice_id           BIGINT NOT NULL REFERENCES invoices(id),
    customer_id          BIGINT NOT NULL REFERENCES customers(id),
    refund_amount_cents  INTEGER NOT NULL CHECK (refund_amount_cents > 0),
    reason               TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Note the seam this creates: every query joining `refunds` to its siblings
will mix `customer_id` with `cust_id` and `created_at` with `crtd_at` until
the older tables are renamed.

# Notes

Identical structure: same six columns in the same order, same types,
constraints, defaults, and foreign keys — only the spelling of the names
differs. A keeps the schema internally consistent; B writes readable names
and flags the mixed-convention joins it causes. Neither table is wrong.
