"""
Held-out comparison on the audited export: the same two seeds trained on the
valid-only export versus checkpoints trained on everything, scored on the
reference session's valid gestures, plus ambient false positives.

    python notebooks/experiments/clean_run.py <workdir>

Needs <workdir>/clean.npz and <workdir>/gref_seed{0,1}.pt (the "trained on
everything" checkpoints; skipped if absent). Writes <workdir>/clean_results.json.
"""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
S = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WHIP_WORK", "data/work"))
from curve import score, S1, S2, REF, AMB
res = {}
for seed in (0, 1):
    ck = S / f"clean_gref_seed{seed}.pt"
    subprocess.run([sys.executable, "-m", "probe.train", "--quiet", "--windows", str(S / "clean.npz"), "--out", str(ck), "--seed", str(seed),
                    "--channels", "shape,scale,saturation,gref", "--held-out", AMB, "--held-out", REF], check=True, capture_output=True)
    res[f"seed{seed}"] = score(ck); print("clean gref seed", seed, json.dumps(res[f"seed{seed}"]), flush=True)
    out = subprocess.run([sys.executable, "-m", "probe.rollout", "--checkpoint", str(ck), "--windows", str(S / "clean.npz")], capture_output=True, text=True).stdout
    fp = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] in ("0.40", "0.60", "0.90") and parts[1].endswith("%"):
            fp[parts[0]] = {"recall": parts[1], "fp_per_min": float(parts[3])}
    res[f"seed{seed}"]["ambient"] = fp; print("  ambient", json.dumps(fp), flush=True)
# the previous (uncleaned) gref checkpoints scored on the same valid-only truth, for a like-for-like comparison
for seed in (0, 1):
    if (S / f"gref_seed{seed}.pt").exists():
        res[f"uncleaned_seed{seed}"] = score(S / f"gref_seed{seed}.pt"); print("uncleaned gref seed", seed, json.dumps(res[f"uncleaned_seed{seed}"]), flush=True)
(S / "clean_results.json").write_text(json.dumps(res, indent=1))
print("CLEAN_DONE")
