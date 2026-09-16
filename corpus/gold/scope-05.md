---
id: scope-05
dimension: scope
status: gold
domain: scripting
sentinel: false
---

# Task

`backup_captures.sh` is copying the symlinks in `data/captures`
(`current.bin`, `latest-good.bin`) as if they were real captures. Make it
skip symlinks.

# Context

A short cron'd POSIX shell script. The source and destination are fixed repo
directories, and capture filenames are timestamped (`cap-20260912-1417.bin`)
— no whitespace, no glob characters. The script leaves `$SRC`, `$f`, and
`$DEST` unquoted.

## A (minimal)

Without `-L`, `find` sees a symlink as type `l`, so `-type f` excludes them:

```sh
-find $SRC -name '*.bin' -mtime -30 | while read -r f; do
+find $SRC -type f -name '*.bin' -mtime -30 | while read -r f; do
```

The two symlinks are skipped; everything else is untouched.

## B (opportunistic)

Without `-L`, `find` sees a symlink as type `l`, so `-type f` excludes them.
While editing I also quoted the three unquoted path expansions — latent
word-splitting bugs if a path ever grows a space:

```sh
-find $SRC -name '*.bin' -mtime -30 | while read -r f; do
-  cp -p $f $DEST/
-done
+find "$SRC" -type f -name '*.bin' -mtime -30 | while read -r f; do
+  cp -p "$f" "$DEST/"
+done
```

The two symlinks are skipped, and the copy loop no longer depends on paths
staying whitespace-free.

# Notes

The requested fix is the same `-type f` token in the same position in both
variants. B's quoting is a behavioral no-op on the paths this script actually
uses — fixed directories and timestamped filenames with no whitespace or glob
characters — so the backup itself is byte-for-byte identical under A and B;
the axis is only whether the unrequested hardening is welcome.
