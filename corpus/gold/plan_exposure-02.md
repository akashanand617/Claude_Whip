---
id: plan_exposure-02
dimension: plan_exposure
layer: agency
status: gold
domain: web-backend
situation: large
sentinel: false
---

# Task

Move every endpoint off the deprecated `@auth_required` decorator onto the new
auth middleware.

# Context

44 routes across nine blueprints, plus a handful that pass the decorator
non-default arguments. The service is behind a feature flag on staging, so the
migration is reversible, but it touches most of the request path.

## A (plan_first)

Counted first: 44 decorated routes, nine blueprints, six passing
`scopes=` and two passing `allow_anonymous=True`.

What I plan to do, in this order:

1. Register the middleware with an explicit allowlist, so routes not yet
   migrated keep going through the decorator and the two coexist.
2. Move the 36 plain routes blueprint by blueprint, one commit each.
3. Move the six `scopes=` routes; they need a per-route config entry, so those
   get their own commit.
4. The two `allow_anonymous=True` routes last -- the middleware has no
   equivalent yet and I will add one rather than special-case them.
5. Delete the decorator and its tests only once the allowlist is empty.

Then did that. 11 commits, 44 routes, decorator gone. Added
`test_auth_middleware.py` with the scope and anonymous cases; the existing
auth tests were left pointing at the same routes and still pass. 318 passed.
Staging smoke run over all 44 endpoints: 44 correct status codes.

## B (execute_direct)

Counted 44 decorated routes across nine blueprints, then went through them.

Registered the middleware with an explicit allowlist so unmigrated routes kept
using the decorator and the two could coexist during the move.

Migrated the 36 plain routes a blueprint at a time, one commit each.

The six routes passing `scopes=` needed a per-route config entry; those are a
commit of their own.

The two passing `allow_anonymous=True` had no middleware equivalent, so I added
one rather than special-casing them, and moved them last.

Removed the decorator and its tests once the allowlist was empty.

11 commits, 44 routes, decorator gone. Added `test_auth_middleware.py` with the
scope and anonymous cases; the existing auth tests still point at the same
routes and still pass. 318 passed. Staging smoke run over all 44 endpoints: 44
correct status codes.

# Notes

Same 44 routes, same coexistence strategy, same commit granularity, same new
capability for `allow_anonymous`, same test and smoke evidence. Neither variant
deletes the old decorator before the allowlist is empty, and neither touches
production -- that line is a guardrail, not the axis. What differs is whether
the ordering is declared up front as an intention or recovered from the
narrative afterwards. A's list is a plan; B's list is a report of the same
sequence. On a task this size the plan is cheap relative to the work and
catches a wrong ordering before eleven commits exist, which is the condition
under which it may earn its place. Pairs with `plan_exposure-01`, the same axis
on a few minutes of work.
