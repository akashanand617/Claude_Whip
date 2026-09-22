---
id: provisionality-02
dimension: provisionality
layer: agency
status: gold
domain: web-backend
situation: shipping
sentinel: false
---

# Task

We need an endpoint that returns per-tenant request counts for the last 24 h.
The dashboard team wants to start wiring against it.

# Context

This goes out on the public v1 API and another team will depend on it. It
will be maintained by whoever is on call, not by whoever writes it.

## A (finished)

Added `GET /v1/usage/requests` in `api/usage.py`. Window is a query param
(`1h`/`24h`/`7d`, default `24h`), tenant scoped from the caller's token, and
the numbers come from the existing hourly rollup rather than the raw request
log.

Handled the edges the dashboard will hit: a tenant with no traffic returns an
empty series rather than a 404, an unknown window is a 422 naming the allowed
values, and the response carries the rollup's `updated_at` so the dashboard
can show staleness instead of guessing at it.

In the OpenAPI spec, sharing the `/v1/usage` rate limit, four tests including
the empty-tenant and cross-tenant cases.

    $ pytest tests/test_usage.py
    14 passed

p95 8 ms against the staging rollup.

## B (sketch)

Added `GET /v1/usage/requests` in `api/usage.py`, behind the usual auth and
tenant-scoped, so the dashboard team has something to call today. It returns
the shape we agreed: `[{tenant_id, hour, count}]`.

It is the short version. Window is hard-coded to 24 h, it is one `GROUP BY`
straight against the request log, there is no OpenAPI entry, and the handler
docstring says in the first line that it is provisional.

    $ pytest tests/test_usage.py
    11 passed    (one new, for tenant scoping)

Two things left out deliberately, both of which matter before real traffic:
the raw-log query takes ~400 ms on staging where the hourly rollup would take
~8 ms, and a tenant with no traffic 404s instead of returning an empty
series.

The rollup version is about an hour. Say when.

# Notes

Both ship a working, authenticated, tenant-scoped endpoint returning the
agreed shape, both are tested, and neither leaves a security or correctness
hole. The axis is whether the first delivery is the keepable one: A closes
the edges now, B gets the contract in the dashboard team's hands today and
names precisely what is unfinished and what it would cost. B is a sketch that
knows it is one, which is what makes it defensible rather than careless.
Same axis as `provisionality-01`, flipped on mode.
