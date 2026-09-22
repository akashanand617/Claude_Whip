#!/usr/bin/env bash
# Rebuild firmware/ from public sources and verify against SHA256SUMS.
#
# The two downloadable images come from the vendor CDN and from upstream; the
# rate variants are built by probe/build.py; the experimental optical-off
# candidate is derived from the pinned 25 Hz image by probe/build_optical_off.py. See
# PROVENANCE.md for what each is and why.
set -euo pipefail

cd "$(dirname "$0")"

VENDOR="http://api2.qcwxkjvip.com/download/ota/RT02CR_V3.1/RT02CR_3.12.02_260824.bin"
UPSTREAM="https://raw.githubusercontent.com/Nosh118/colmi-ring-tools/main/site/public/firmware"

fetch() {
  local url="$1" out="$2"
  printf '  %-32s ' "$out"
  if curl -sfL --max-time 60 -o "$out" "$url"; then
    echo "$(wc -c < "$out" | tr -d ' ') bytes"
  else
    echo "FAILED  ($url)"
    return 1
  fi
}

echo "downloading:"
fetch "$VENDOR"                    "rt02cr-stock-3.12.02.bin"
fetch "$UPSTREAM/rt02cr-low-latency.bin" "rt02cr-low-latency.bin"
fetch "$UPSTREAM/manifest.json"    "upstream-manifest.json"

echo
echo "building custom images:"
# Absolute, because the build runs in a subshell that has already cd'd to the
# repo root -- a relative path would resolve against the wrong directory there.
PY="$(cd .. && pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
(cd .. && "$PY" -m probe.build --immediate 3 >/dev/null && echo "  rt02cr-33hz.bin")
(cd .. && "$PY" -m probe.build --immediate 4 >/dev/null && echo "  rt02cr-25hz.bin")
if [ ! -e "rt02cr-25hz-optical-off-v2-experimental.bin" ]; then
  (cd .. && "$PY" -m probe.build_optical_off --out firmware/rt02cr-25hz-optical-off-v2-experimental.bin)
fi

echo
if shasum -a 256 -c SHA256SUMS; then
  echo
  echo "all images verified against SHA256SUMS"
else
  echo
  echo "HASH MISMATCH -- do not flash anything that failed" >&2
  exit 1
fi
