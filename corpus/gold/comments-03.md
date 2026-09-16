---
id: comments-03
dimension: comments
status: gold
domain: scripting
sentinel: false
---

# Task

Write the nightly cleanup script: delete captures older than 30 days, but
always keep the newest 5 regardless of age.

# Context

Runs from cron against `/data/captures`. Capture filenames contain no spaces.
Both versions run the identical pipeline.

## A (sparse)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /data/captures

# the newest 5 survive even past 30 days -- the keep rule wins over the age rule
ls -1t *.cap | tail -n +6 | while read -r f; do
    if [ -n "$(find "$f" -mtime +30 -print)" ]; then
        rm -- "$f"
    fi
done
```

## B (narrated)

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /data/captures

# list every capture, newest first (ls -t sorts by mtime, descending)
# the newest 5 survive even past 30 days -- the keep rule wins over the age rule
# tail -n +6 slices off the first five lines, i.e. the newest 5
ls -1t *.cap | tail -n +6 | while read -r f; do
    # find prints the file only when it is older than 30 days
    if [ -n "$(find "$f" -mtime +30 -print)" ]; then
        # delete it; -- guards against a name starting with a dash
        rm -- "$f"
    fi
done
```

# Notes

Code is line-for-line identical; only comment density differs. A carries the
single comment on the keep-newest-5 override, which deliberately contradicts
the age rule and so cannot be inferred from the code alone; B additionally
narrates each pipeline stage (list/sort, slice, age test, delete). A's
override comment appears verbatim in B, so B is a superset.
