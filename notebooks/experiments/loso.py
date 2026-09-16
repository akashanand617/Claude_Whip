"""
Leave-one-session-out: for every prompted session with valid gestures, train
on everything else (frame flips, gref channels; an ambient session held out
too) and score that session's valid gestures. Pooled over sessions this is a
held-out score for every class, with confusions.

    python notebooks/experiments/loso.py <workdir> [seed]

Reads data/windows.npz (export made after `probe.audit --all --write`),
writes <workdir>/loso_results.json.
"""
import json, os, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

from whip import audit, evaluate, events
from whip import model as gm
from whip.registry import load_registry

R = load_registry()
W = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WHIP_WORK", "data/work"))
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 0
AMB = os.environ.get("WHIP_AMBIENT", "negative_20260915_224235")
SESS_DIR = Path("data/sessions")
CH = os.environ.get("WHIP_CHANNELS", "shape,scale,saturation,gref")

d = np.load("data/windows.npz", allow_pickle=True)
X, y, SESS, START, GRAV = d["X"], d["y"], d["session"], d["start_s"], d["gravity"]
labels = [str(s) for s in d["labels"]]
cn = R.collapsed_names(labels)


def truth_for(sid):
    n = json.loads((SESS_DIR / f"{sid}.notes.json").read_text())
    bad = set(audit.excluded_cues(SESS_DIR / f"{sid}.jsonl"))
    out = []
    for m in n["marks"]:
        if "until" in m or m["cue_at"] in bad:
            continue
        spec = R.resolve(m["label"])
        out.append((m["cue_at"] + 0.6, f"{spec.name}_{m['direction']}", m.get("amplitude", "")))
    return out


prompted = sorted(s for s in set(SESS.tolist()) if s.startswith("prompted_") and truth_for(s))
results = {"seed": SEED, "channels": CH, "sessions": {}, "per_class": {}, "confusions": {}, "by_amplitude": {}}
per_class = defaultdict(lambda: {"n": 0, "exact": 0, "type": 0, "any": 0})
conf = Counter()
by_amp = defaultdict(lambda: {"n": 0, "exact": 0})
for sid in prompted:
    ck = W / f"loso_{sid}_s{SEED}.pt"
    subprocess.run([sys.executable, "-m", "probe.train", "--quiet", "--out", str(ck), "--seed", str(SEED),
                    "--channels", CH, "--held-out", AMB, "--held-out", sid], check=True, capture_output=True)
    model, meta = gm.load(ck); model.eval()
    sel = SESS == sid; order = np.where(sel)[0][np.argsort(START[sel])]; starts = START[order]
    with torch.no_grad():
        probs = torch.softmax(model(torch.tensor(gm.to_model_input(X[order], meta["channels"], gravity=GRAV[order]))), 1).numpy()
    truth = truth_for(sid)
    ev = events.detect(evaluate.labels_at(probs, labels, 0.4), starts.tolist(), policies=R.policies(labels))
    evc = events.detect(evaluate.labels_at(R.collapse_probabilities(probs, labels), cn, 0.4), starts.tolist(), policies=R.policies(cn))
    hx = evaluate.gesture_hits(ev, [(t, nm) for t, nm, _ in truth])
    ht = evaluate.gesture_hits(evc, [(t, R.collapse(nm)[0]) for t, nm, _ in truth])
    ha = evaluate.gesture_hits(evc, [(t, R.collapse(nm)[0]) for t, nm, _ in truth], require_class=False)
    # false events: fired inside the session but matching no truth
    matched = set()
    for t, nm, _ in truth:
        for e in ev:
            if abs(e.centre_s - t) <= 0.75:
                matched.add(id(e))
    spurious = [e.label for e in ev if id(e) not in matched]
    s_res = {"n": len(truth), "exact": int(sum(hx)), "type": int(sum(ht)), "any": int(sum(ha)),
             "spurious_events": len(spurious), "minutes": float((starts[-1] - starts[0]) / 60)}
    results["sessions"][sid] = s_res
    print(sid, json.dumps(s_res), flush=True)
    for (t, nm, amp), ex, ty, an in zip(truth, hx, ht, ha):
        c = per_class[nm]; c["n"] += 1; c["exact"] += ex; c["type"] += ty; c["any"] += an
        a = by_amp[amp or "?"]; a["n"] += 1; a["exact"] += ex
        if not ex:
            fired = [e.label for e in ev if abs(e.centre_s - t) <= 0.75]
            conf[(nm, fired[0] if fired else "-")] += 1
results["per_class"] = dict(per_class)
results["confusions"] = {f"{a} -> {b}": n for (a, b), n in conf.most_common()}
results["by_amplitude"] = dict(by_amp)
(W / f"loso_results_s{SEED}.json").write_text(json.dumps(results, indent=1))
tot = sum(c["n"] for c in per_class.values())
print(f"\nPOOLED over {len(prompted)} held-out sessions, {tot} valid gestures, thr 0.4:")
print(f"  exact class {sum(c['exact'] for c in per_class.values())}/{tot}   type {sum(c['type'] for c in per_class.values())}/{tot}   any event {sum(c['any'] for c in per_class.values())}/{tot}")
for k in sorted(per_class):
    c = per_class[k]; print(f"  {k:20s} n={c['n']:3d}  exact {c['exact']:3d} ({100*c['exact']/c['n']:5.1f}%)  type {c['type']:3d}  any {c['any']:3d}")
print("  by amplitude:", {k: f"{v['exact']}/{v['n']}" for k, v in by_amp.items()})
print("  confusions (truth -> fired):", results["confusions"])
print("LOSO_DONE")
