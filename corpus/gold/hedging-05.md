---
id: hedging-05
dimension: hedging
status: gold
domain: devops
sentinel: false
---

# Task

Why is the integration test flaky on CI but never fails locally?

# Context

Both responses rest on the same evidence. The test starts the API server on
fixed port 8199. CI runs pipeline jobs in parallel on shared runners;
locally only one instance ever runs. Every captured failure log ends with
`EADDRINUSE: address already in use :::8199`, and in each failing run the CI
timeline shows a second job of the same pipeline active on the same runner.

## A (committed)

It's a port collision between parallel CI jobs. The failure is `EADDRINUSE`
on 8199, and every failing run overlaps a sibling job on the same runner —
two servers, one fixed port. Locally it can't reproduce because only one
instance ever runs. Fix: bind port 0, read the assigned port back from the
server, and pass it to the test client — three lines in the fixture. That
removes the shared resource rather than papering over the symptom.

## B (cautious)

Parallel jobs colliding on the fixed port is the leading explanation: the
failures are `EADDRINUSE` on 8199, and each one overlaps a sibling job on
the same runner, while locally a second instance never exists. One
alternative produces the identical error without a second job, though: a
teardown race, where the previous test's server hasn't released 8199 —
process exit lag or a socket in TIME_WAIT — when the next bind happens.
The overlap evidence favors the cross-job reading, but busy runners overlap
often, so it could coincide. The fix is the same either way: bind port 0,
read the assigned port back, pass it to the client — a fresh port each run
closes both causes. I'd watch CI for a week after merging; if flakes return
in another form, teardown hygiene in the fixture is the next place to look.

# Notes

Identical evidence, identical fix (ephemeral port read back from the
server), and both agree the error string and job overlap point at
collision. The axis is framing: A calls it settled from the log plus the
timeline; B names one alternative that yields the same errno, notes the fix
covers both, and asks for a week of observation. The teardown race is a real
alternative the evidence doesn't exclude, so B's caution is genuine; A adds
no claim beyond the stated log and timeline.
