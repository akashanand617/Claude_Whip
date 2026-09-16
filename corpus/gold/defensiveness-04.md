---
id: defensiveness-04
dimension: defensiveness
status: gold
domain: scripting
sentinel: false
---

# Task

Write the deploy script. It reads `TARGET_HOST`, `RELEASE_TAG`, and
`DEPLOY_KEY` from the environment, copies the release tarball over, and
activates it.

# Context

Run by hand and from CI. The three variables are documented in
`docs/DEPLOY.md`; CI exports them from its secrets store.

## A (trusting)

```bash
#!/usr/bin/env bash
set -euo pipefail

scp -i "$DEPLOY_KEY" "releases/$RELEASE_TAG.tar.gz" \
    "deploy@$TARGET_HOST:/srv/incoming/"
ssh -i "$DEPLOY_KEY" "deploy@$TARGET_HOST" \
    "sudo /srv/bin/activate-release $RELEASE_TAG"
```

`set -u` makes an unset variable abort the script immediately with the
shell's own `TARGET_HOST: unbound variable`, before anything is copied.

## B (defensive)

```bash
#!/usr/bin/env bash
set -euo pipefail

for var in TARGET_HOST RELEASE_TAG DEPLOY_KEY; do
    if [ -z "${!var:-}" ]; then
        echo "error: $var is not set or empty (see docs/DEPLOY.md)" >&2
        exit 1
    fi
done

scp -i "$DEPLOY_KEY" "releases/$RELEASE_TAG.tar.gz" \
    "deploy@$TARGET_HOST:/srv/incoming/"
ssh -i "$DEPLOY_KEY" "deploy@$TARGET_HOST" \
    "sudo /srv/bin/activate-release $RELEASE_TAG"
```

Each variable is checked up front; the message names which one is missing
and where it is documented, before any remote command runs.

# Notes

The deploy body is byte-identical, and both abort before copying anything
when a variable is unset. The axis is only the failure message: the shell's
terse `unbound variable` versus a curated line naming the variable and its
documentation. B additionally treats empty-but-set as missing, which is
still invalid input, not a happy-path difference. Neither proceeds on a bad
environment.
