---
id: plan_exposure-01
dimension: plan_exposure
layer: agency
status: gold
domain: scripting
situation: small
sentinel: false
---

# Task

Give me a script that pulls the last 200 build logs off the CI box and tells me
which ones hit the flaky socket test.

# Context

One shell script, no repo to fit into, a few minutes of work. The CI box is
reachable over ssh and the logs are plain text under a dated directory.

## A (execute_direct)

Listed the log dir over ssh: one file per build, `build-<n>.log`, newest 200
span the last nine days.

Wrote `scripts/flaky_scan.sh`:

- `ssh ci ls -1t /var/log/ci | head -200` for the names, then one `rsync` for
  the batch rather than 200 round trips;
- caches into `.cache/ci-logs/` and skips anything already there, so a re-run
  is about four seconds;
- greps for `test_socket_reconnect .* FAILED`, prints build number, date, and
  the assertion line;
- `--since` and `--pattern` flags, both defaulted.

Ran it: 200 logs, 41 s cold, 3.6 s warm. 17 hits, clustered on two days,
all the same assertion at `test_net.py:212`.

Output is in `flaky.txt`.

## B (plan_first)

Here is what I intend to do, before I start writing it.

Pull the newest 200 names with `ssh ci ls -1t | head -200`, then fetch the
batch in a single `rsync` rather than 200 round trips, into a local cache dir
so a second run does not re-download. Grep for the failing test name, print
build number, date, and the assertion line. Two flags, `--since` and
`--pattern`, both defaulted so the bare command does the thing you asked for.

Then wrote `scripts/flaky_scan.sh` that way.

Ran it: 200 logs, 41 s cold, 3.6 s warm. 17 hits, clustered on two days, all
the same assertion at `test_net.py:212`.

Output is in `flaky.txt`.

# Notes

Identical script, identical flags, identical caching decision, identical run
and identical findings -- the amount of work is held equal and only the
announcement moves. The axis is whether the approach is stated before it exists
or read off the result afterwards. A is not withholding anything: every choice
B previews is legible in A's summary, just after the fact. B is not stalling
either; it does not wait for approval, it says what it is about to do and then
does it. On a task this size the preview costs a paragraph against a few
minutes of work, which is the condition under which it may read as ceremony.
Pairs with `plan_exposure-02`, the same axis on a task that spans a package.
