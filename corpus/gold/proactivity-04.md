---
id: proactivity-04
dimension: proactivity
status: gold
domain: scripting
sentinel: false
---

# Task

Write a script that rotates the daemon logs, keeping 7 days.

# Context

The daemon appends to `/var/log/whipd/whipd.log` and reopens its log file
on SIGHUP. The request names only the script.

## A (exact)

`rotate-whipd-logs.sh`:

```sh
#!/bin/sh
set -eu
LOG_DIR=/var/log/whipd
mv "$LOG_DIR/whipd.log" "$LOG_DIR/whipd.log.$(date +%Y%m%d)"
kill -HUP "$(cat /var/run/whipd.pid)"   # daemon reopens its log file
find "$LOG_DIR" -name 'whipd.log.*' -mtime +7 -delete
```

Rotate first, then HUP so the daemon starts a fresh file, then prune
anything older than 7 days.

## B (collateral)

`rotate-whipd-logs.sh`:

```sh
#!/bin/sh
set -eu
LOG_DIR=/var/log/whipd
mv "$LOG_DIR/whipd.log" "$LOG_DIR/whipd.log.$(date +%Y%m%d)"
kill -HUP "$(cat /var/run/whipd.pid)"   # daemon reopens its log file
find "$LOG_DIR" -name 'whipd.log.*' -mtime +7 -delete
```

Rotate first, then HUP so the daemon starts a fresh file, then prune
anything older than 7 days. Also set up, unrequested:

- the crontab line to install it, nightly before the daemon's busy hours:
  `15 3 * * * /usr/local/bin/rotate-whipd-logs.sh`
- a README "Log rotation" section: where the archives land, the 7-day
  retention, and that restarting the daemon mid-rotation is safe because
  the HUP handler only reopens the file.

# Notes

The script is identical in both variants, byte for byte. B adds the cron
installation line and a README section that were not asked for. The axis
is whether that surrounding collateral is valued; the requested artifact
and its behavior are held equal.
