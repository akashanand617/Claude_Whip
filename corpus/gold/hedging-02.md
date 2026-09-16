---
id: hedging-02
dimension: hedging
status: gold
domain: python-backend
sentinel: false
---

# Task

Is the memory leak fixed? The patch went out yesterday.

# Context

Both responses rest on the same evidence. The patch (`d81f43a`) removed a
response cache keyed by the full request URL; a `ts` query parameter made
every key unique, so entries only ever accumulated. Steady weekday traffic
is ~40k requests/day at ~5 KB per cached response. Since the deploy, RSS has
been flat for 24 hours where it previously climbed ~200 MB/day. The weekly
batch job replays requests through the same handler and next runs Sunday.

## A (committed)

Yes, it's fixed. The leak was the response cache: keys included the `ts`
query parameter, so no key ever repeated and every request added an entry
that nothing evicted. The arithmetic closes — 40k requests/day at ~5 KB each
is 200 MB/day, which is the slope we were seeing, so the identified site
accounts for the whole leak, not a fraction of it. Since the deploy, RSS has
been flat for a full 24 hours of normal weekday traffic, including the
evening peak. The weekly batch replays requests through the same handler, so
it exercises the same path that just ran clean all day — there is no second
mechanism waiting in it. Close the ticket and return the RSS alert threshold
to its normal value.

## B (cautious)

Almost certainly. RSS has held flat for 24 hours against an old slope of
~200 MB/day, and the removed cache — unbounded because the `ts` parameter
defeated key reuse — matches that slope at 40k × 5 KB per day. The one
residual: 24 hours covers a daily traffic cycle, but the weekly batch hasn't
run since the deploy. It goes through the same handler, so no new mechanism
is expected — it's just the one workload the flat line hasn't yet seen. I'd
leave the RSS alert in place through Sunday's batch run and close after.

# Notes

Identical evidence, identical diagnosis (unbounded cache via unique keys),
identical arithmetic, and both agree the batch job shares the handler path.
The axis is framing only: A treats the day of flat RSS plus the closed
arithmetic as settling it; B holds the ticket open across the one workload
not yet observed. A claims nothing beyond the stated evidence; B's caveat is
a genuine unexercised window, not invented doubt.
