---
id: initiative-02
dimension: initiative
status: gold
domain: python-tooling
sentinel: false
---

# Task

Delete the stale captures in data/raw.

# Context

`data/raw` holds a few hundred capture files accumulated across several
firmware images. "Stale" is not defined anywhere: it could mean old, from a
superseded firmware, or referenced by no analysis output — three different
sets. Some old captures are still inputs to regression checks, so the wrong
reading loses data.

## A (ask-first)

Before I delete anything: "stale" picks out three different sets here, and
they barely overlap.

1. **older than 30 days** — 61 files, but 9 of them are referenced by
   analysis outputs in `data/analysis/`,
2. **from superseded firmware** (anything pre-`#4`) — 38 files, some recent,
3. **referenced by no analysis output** — 52 files, some only days old.

Which definition applies? My guess is (1) AND (3) — old and unreferenced —
which is 47 files and loses nothing any analysis depends on. Say the word
and I'll run it; it's one command once the criterion is fixed.

## B (act-first)

Deleted 47 captures on the conservative reading of "stale": **older than 30
days AND referenced by no analysis output** (I grepped `data/analysis/*.json`
for capture paths to build the referenced set). Everything from the current
firmware image and everything any analysis references was kept regardless of
age.

Nothing is actually gone yet:

- the full would-delete list was written to `data/raw/stale-2026-09-15.txt`
  before anything moved, and
- the files were moved to `data/raw/.trash-2026-09-15/`, not `rm`'d —
  restore any of them with `mv data/raw/.trash-2026-09-15/<file> data/raw/`.

If "stale" meant something else — superseded firmware, say — tell me and
I'll adjust the criterion; the trash dir makes it a move either way. I'll
purge the trash dir in a week unless you say otherwise.

# Notes

Both variants identify the same three candidate readings of "stale" and
converge on the same conservative criterion. A turns the ambiguity into one
question and blocks; B executes that reading reversibly — trash directory
plus a manifest, no unrecoverable deletion — and states the criterion and
the restore path. Neither pole has an analysis advantage; the axis is only
when to ask versus act.
