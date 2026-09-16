---
id: hedging-03
dimension: hedging
status: gold
domain: cpp-daemon
sentinel: false
---

# Task

What caused the daemon crash during ring disconnects?

# Context

Both responses rest on the same evidence. Field crash logs cluster within
~50 ms of disconnect events. Under ASAN, the reconnect test aborts with
heap-use-after-free: the `Session` is freed in `onDisconnect()`
(session.cpp:88) and read 40 ms later from `ReconnectTimer::fire()` — both
stacks are in the report. A fake-clock unit test reproduces it
deterministically. Two other places also hold the raw session pointer across
disconnect: the heartbeat loop and the stats dump.

## A (committed)

The reconnect timer is reading a freed session. The ASAN report contains
both halves: the free is `onDisconnect()` at session.cpp:88, and the bad
read is `ReconnectTimer::fire()` 40 ms later — the timer is armed on
disconnect and never cancelled when the session is torn down, so it fires
into freed memory. That matches the field logs exactly: crashes cluster
within ~50 ms of disconnects, which is the timer's window. The fake-clock
test reproduces it on every run — disconnect, advance 40 ms, identical
report.

Fix: cancel the timer in `onDisconnect()` before the session is released
(two lines at session.cpp:86). With that in place, the reproducer and 500
randomized-timing iterations run clean under ASAN.

## B (cautious)

Most likely the reconnect timer, which is one of three paths holding the
session pointer across disconnect. The ASAN report shows the free in
`onDisconnect()` (session.cpp:88) and the read in `ReconnectTimer::fire()`
40 ms later, the fake-clock test reproduces it, and the field crashes
cluster in that same post-disconnect window — consistent, though the field
crashes themselves were never run under ASAN. Fix: cancel the timer in
`onDisconnect()` before the release (session.cpp:86); the reproducer runs
clean after. The heartbeat loop and the stats dump hold the same raw pointer
and weren't instrumented — worth auditing both for the same lifetime
bug before declaring the crash class closed.

# Notes

Same trace, same reproducer, same two-line fix at the same site. The axis is
epistemic framing: A treats trace + reproducer + field timing as settling
the cause; B frames it as the demonstrated one of three pointer-holding
paths and asks for the other two to be audited. B's caveats are genuine —
the field crashes were unsymbolized and the other paths unexamined — not
doubt about what ASAN showed.
