"""
Learning curve: train on a fraction of the valid gestures of the training
sessions, test on the held-out reference session, gref channels.

    python notebooks/experiments/curve.py <workdir>

Reads <workdir>/clean.npz (an export made after `probe.audit --write`), writes
<workdir>/curve_results.json; `scripts/rerun.sh` copies it into
notebooks/results/ for the data-quality notebook.
"""
import json, os, subprocess, sys, numpy as np, torch
from pathlib import Path
from whip import evaluate, events, audit
from whip import model as gm
from whip.registry import load_registry
R = load_registry()
S = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WHIP_WORK", "data/work"))
SESS_DIR = Path("data/sessions")
S1, S2 = "prompted_20260909_160303", "prompted_20260912_013715"
REF = os.environ.get("WHIP_REF", "prompted_20260915_184744"); AMB = os.environ.get("WHIP_AMBIENT", "negative_20260915_021616")
d = np.load(S / "clean.npz", allow_pickle=True)
X, y, SESS, START, GRAV, DIR = d["X"], d["y"], d["session"], d["start_s"], d["gravity"], d["direction"]
labels = [str(s) for s in d["labels"]]

def marks(sid):
    n = json.loads((SESS_DIR / f"{sid}.notes.json").read_text())
    bad = set(audit.excluded_cues(SESS_DIR / f"{sid}.jsonl"))
    out = []
    for m in n["marks"]:
        if "until" in m or m["cue_at"] in bad: continue
        spec = R.resolve(m["label"]); out.append((m["cue_at"], f"{spec.name}_{m['direction']}"))
    return out

def gesture_of(sid):
    """Map each labelled window of a session to the index of its mark (nearest cue)."""
    idx = np.where((SESS == sid) & (y != 0))[0]
    ms = marks(sid); cues = np.array([c for c, _ in ms])
    owner = np.full(len(X), -1)
    for i in idx:
        k = int(np.argmin(np.abs(cues - (START[i] + 0.4))))   # a labelled window starts ~0.4-1.2 s before the cue+0.6 centre
        owner[i] = k
    return owner, ms

owners = {}; markl = {}
for sid in (S1, S2):
    owners[sid], markl[sid] = gesture_of(sid)

def subset(frac, seed):
    rng = np.random.default_rng(100 + seed)
    keep = np.ones(len(X), bool)
    for sid in (S1, S2):
        ms = markl[sid]
        by_class = {}
        for k, (_, name) in enumerate(ms): by_class.setdefault(name, []).append(k)
        drop = set()
        for name, ks in by_class.items():
            n_keep = max(1, int(round(frac * len(ks))))
            chosen = set(rng.choice(ks, n_keep, replace=False).tolist())
            drop |= set(ks) - chosen
        sel = (SESS == sid) & (y != 0)
        keep[sel & np.isin(owners[sid], list(drop))] = False
        # also drop the `none` windows near dropped gestures? no -- they are genuine negatives
    return keep

def score(ck):
    model, meta = gm.load(ck); model.eval()
    sel = SESS == REF; order = np.where(sel)[0][np.argsort(START[sel])]; starts = START[order]
    with torch.no_grad():
        probs = torch.softmax(model(torch.tensor(gm.to_model_input(X[order], meta["channels"], gravity=GRAV[order]))), 1).numpy()
    truth = [(c + 0.6, n) for c, n in marks(REF)]
    out = {}
    for thr in (0.4, 0.6, 0.9):
        pred = evaluate.labels_at(probs, labels, thr)
        ev = events.detect(pred, starts.tolist(), policies=R.policies(labels))
        hits = evaluate.gesture_hits(ev, truth)
        cn = R.collapsed_names(labels); cp = R.collapse_probabilities(probs, labels)
        evc = events.detect(evaluate.labels_at(cp, cn, thr), starts.tolist(), policies=R.policies(cn))
        hits_t = evaluate.gesture_hits(evc, [(t, R.collapse(n)[0]) for t, n in truth])
        out[str(thr)] = {"exact": int(sum(hits)), "type": int(sum(hits_t)), "n": len(truth)}
    return out

if __name__ == "__main__":
  results = []
  for frac in (0.25, 0.5, 0.75, 1.0):
      for seed in (0, 1):
          keep = subset(frac, seed)
          sub = S / f"curve_{int(frac*100)}_{seed}.npz"
          np.savez(sub, **{k: (d[k][keep] if d[k].shape[:1] == X.shape[:1] else d[k]) for k in d.files})
          n_g = sum(int(round(frac * len(markl[s]))) for s in (S1, S2))
          ck = S / f"curve_{int(frac*100)}_{seed}.pt"
          subprocess.run([sys.executable, "-m", "probe.train", "--quiet", "--windows", str(sub), "--out", str(ck), "--seed", str(seed),
                          "--channels", "shape,scale,saturation,gref", "--held-out", AMB, "--held-out", REF], check=True, capture_output=True)
          r = {"frac": frac, "seed": seed, "train_gestures": n_g, "train_windows": int(((y != 0) & keep & np.isin(SESS, [S1, S2])).sum()), **score(ck)}
          results.append(r); print(json.dumps(r), flush=True)
  (S / "curve_results.json").write_text(json.dumps(results, indent=1))
  print("CURVE_DONE")
