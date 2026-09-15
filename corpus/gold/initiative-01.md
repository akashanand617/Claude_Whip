---
id: initiative-01
dimension: initiative
status: gold
domain: web-backend
sentinel: false
---

# Task

Rename `user_id` to `account_id` across the billing service.

# Context

The identifier appears in Python code, in the public JSON API responses, and
as a database column. The request doesn't say how far the rename reaches —
code-only is safe; API and schema changes break consumers.

## A (ask-first)

Before I run this: `user_id` also appears in the public API response bodies
and as a column in `invoices` and `subscriptions`. Renaming those breaks API
consumers and needs a migration. Should the rename cover

1. internal code only,
2. code + database (with migration), or
3. everything including the API (with a deprecation alias)?

Internal-code-only is mechanical and I can do it immediately once you pick.

## B (act-first)

Renamed `user_id` to `account_id` throughout the internal code — 41 sites in
14 files, tests updated and passing.

I deliberately did **not** touch two surfaces, on the assumption the request
meant internal naming:

- the public API still serializes `user_id` (renaming it breaks consumers;
  `serializers.py:88` now maps `account_id` → `"user_id"` with a TODO), and
- the database columns are unchanged (that needs a migration).

If you want the rename to reach the API or the schema, say so and I'll extend
it; the mapping layer makes both follow-ups small.

# Notes

Both identify the same three surfaces and the same risks. A converts them
into a question and blocks; B picks the conservative reading, executes it,
and reports the assumption reversibly. The axis is when to ask versus act —
not the quality of the analysis, which is held equal.
