#!/usr/bin/env bash
# Rebuild public-source RT02CR firmware and verify every archived image against
# SHA256SUMS. RT12COL stock was acquired locally and is never downloaded here.
#
# The two downloadable images come from the vendor CDN and from upstream; the
# rate variants are built by probe/build.py; the experimental optical-off
# candidate is derived from the pinned 25 Hz image by probe/build_optical_off.py;
# the compact unified candidate is derived by probe/build_unified_mode.py. The
# RT12COL candidate is rebuilt only when its exact local stock restore exists.
# See PROVENANCE.md for what each is and why.
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
if [ ! -e "rt02cr-25hz-health-default-gesture-v1-experimental.bin" ]; then
  (cd .. && "$PY" -m probe.build_unified_mode --out firmware/rt02cr-25hz-health-default-gesture-v1-experimental.bin)
fi
if [ -e "rt12col-stock-1.00.00.bin" ]; then
  for revision in v1 v2 v3-revoked v4-lp2 v5-lp1 v6-sleep-fix; do
    case "$revision" in
      v3-revoked) artifact="rt12col-25hz-health-default-gesture-v3-experimental.bin" ;;
      *) artifact="rt12col-25hz-health-default-gesture-${revision}-experimental.bin" ;;
    esac
    if [ ! -e "$artifact" ]; then
      (cd .. && "$PY" -m probe.build_rt12col_unified --revision "$revision" --out "firmware/$artifact")
    fi
  done
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
