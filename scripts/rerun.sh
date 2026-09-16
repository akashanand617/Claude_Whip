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
# lines list. Env: WHIP_CHANNELS, WHIP_REF (held-out reference for the
# notebook experiments), WHIP_WORK. Which sessions train / validate / test is
# data/split.json (`probe.split`).
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
WORK=${WHIP_WORK:-data/work}; mkdir -p "$WORK"
CH=${WHIP_CHANNELS:-shape,scale,saturation,room}
# The split plan (data/split.json) decides which sessions train, validate
# and test; WHIP_AMBIENT is no longer used.

echo "### 1. audit"; python -m probe.audit --all --write; echo "audit exit $? (2 = something invalid; it is excluded, re-record it)"
echo "### 2. export (valid only)"; python -m probe.dataset --out data/windows.npz || exit 1
echo "### 2b. fixed split (data/split.json -> data/split/{train,val,test,trainval}.npz)"; python -m probe.split make | grep -v "split by" || exit 1
echo "### 3. train deployed checkpoint ($CH) on train + val; the test part is never trained on"
python -m probe.train --quiet --channels "$CH" --windows data/split/trainval.npz || exit 1
echo "### 4. validation score (threshold and seed are chosen here, never on test)"
python -m probe.split score --part val --threshold 0.4 | grep -v "split by"
python -m probe.split score --part val --threshold 0.9 | grep -v "split by"
echo "    test part: python -m probe.split score --part test --checkpoint <a checkpoint trained on data/split/train.npz>"
echo "    (the deployed checkpoint trains on val, so it is not scored on test; score a train-only checkpoint)"

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
