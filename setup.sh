#!/usr/bin/env bash
# Create the virtualenv and install dependencies for the M0 probe harness.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "creating .venv"
  python3 -m venv .venv
fi

./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo
echo "done. activate with:"
echo "  source .venv/bin/activate"
echo
echo "then, once the ring arrives:"
echo "  python -m probe.scan"
