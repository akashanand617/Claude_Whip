---
id: register-02
dimension: register
layer: agency
status: gold
domain: python-backend
sentinel: false
---

# Task

The request counter reads high. I think the retry wrapper is double-counting.

# Context

`retry.py` wraps outbound calls and increments `requests_total`. The service
has been retrying more than usual since last week's timeout change.

## A (composed)

You were right about the wrapper.

The increment sits inside the retry loop at `retry.py:52`, so a call that
retries twice is counted three times.

I moved the increment outside the loop, which means one call is now one
increment regardless of attempts.

Because that would otherwise lose the retry signal entirely, I added a separate
`retries_total` counter incremented per extra attempt, so the ratio between the
two is still readable.

Anything already charting `requests_total` will step down when this deploys.
On last week's traffic the replay puts the step at about 4%, and it is not a
drop in traffic.

I added one test asserting a single increment across three attempts, and all
28 pass.

## B (curt)

You were right about the wrapper.

Increment is inside the retry loop, `retry.py:52`. Two retries, three counts.

Moved it outside. One call, one increment, whatever the attempt count.

That loses the retry signal, so: new `retries_total`, one per extra attempt.
Ratio still readable.

Anything charting `requests_total` steps down on deploy. Replay on last week's
traffic: ~4%. Not a traffic drop.

1 test, single increment across three attempts. 28 passed.

# Notes

Same content in both, in the same order and to the same level of detail: same
line reference, same fix, same replacement counter and the reason for it, same
warning that existing dashboards will step down, same replayed 4% figure, same
test count. Neither variant omits the dashboard consequence, which is the part
a reader would actually be hurt by missing. A's sentences are complete but not
padded; B's fragments drop subjects and connectives, not facts. Poles are in
the opposite slots from `register-01` so that slot position and style are not
confounded across the pair, and the domains differ so neither style is tied to
one kind of work.
