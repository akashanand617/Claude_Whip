#!/usr/bin/env bash
# Re-run the whole data pipeline after recording a session:
#   audit every prompted session (writes <session>.audit.json, exits 2 on invalid)
#   -> export the valid-only dataset -> retrain the deployed checkpoint
#   -> rollout -> (optionally) the held-out experiments and the notebook.
#
#   scripts/rerun.sh              audit, export, train, rollout          (~5 min)
#   scripts/rerun.sh --notebook   ...plus learning curve + clean comparison and the notebook (~40 min)
#
# The audit's exit code is reported, not obeyed: an invalid gesture is excluded
# by the exporter, so the pipeline still runs; re-record what the "to re-record"
# lines list. Env: WHIP_CHANNELS, WHIP_AMBIENT, WHIP_REF, WHIP_WORK.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
WORK=${WHIP_WORK:-data/work}; mkdir -p "$WORK"
CH=${WHIP_CHANNELS:-shape,scale,saturation,gref}
AMBIENT=${WHIP_AMBIENT:-negative_20260915_021616}

echo "### 1. audit"; python -m probe.audit --all --write; echo "audit exit $? (2 = something invalid; it is excluded, re-record it)"
echo "### 2. export (valid only)"; python -m probe.dataset --out data/windows.npz || exit 1
echo "### 3. train deployed checkpoint ($CH, ambient held out)"; python -m probe.train --quiet --channels "$CH" --held-out "$AMBIENT" || exit 1
echo "### 4. rollout"; python -m probe.rollout

if [[ "${1:-}" == "--notebook" ]]; then
  echo "### 5. held-out experiments (reference ${WHIP_REF:-prompted_20260915_184744})"
  cp data/windows.npz "$WORK/clean.npz"
  python notebooks/experiments/curve.py "$WORK" || exit 1
  python notebooks/experiments/clean_run.py "$WORK" || exit 1
  cp "$WORK/curve_results.json" "$WORK/clean_results.json" notebooks/results/
  echo "### 6. notebook"
  python notebooks/build_data_quality.py && python -m jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=900 notebooks/data_quality.ipynb
fi
echo "### done"
