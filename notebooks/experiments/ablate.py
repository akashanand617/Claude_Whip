"""
Controlled experiments on the fixed gesture split. One question per run,
same val/test, same scoring; results appended to <workdir>/ablate.jsonl.

    python notebooks/experiments/ablate.py <workdir> <name> [--frac-classes snap,clap=0.5]
        [--epochs N] [--channels a,b,c] [--seeds 0,1] [--frame-aug spin|flips|none]

Subsetting is by GESTURE within the train part (a gesture's windows go
together); val and test are never touched.
"""
from __future__ import annotations

import argparse, json, subprocess, sys, time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from whip import split as sp
from whip.registry import load_registry

R = load_registry(); SESS = Path("data/sessions")


def subset_train(d, plan, frac_by_class: dict[str, float], seed: int) -> np.ndarray:
    """Keep mask over all windows: the train part, with the named classes' gestures subsampled."""
    SESSION, START, y = d["session"], d["start_s"], d["y"]; LABELS = [str(s) for s in d["labels"]]
    part = np.array([sp.part_of_window(plan, s, float(t)) or "" for s, t in zip(SESSION, START)])
    spans = {s for s in set(SESSION.tolist())}
    units = [(s, c, k) for s, c, k in sp.gesture_units(SESS, spans, R) if sp.part_of_mark(plan, s, c) == "train"]
    rng = np.random.default_rng(seed)
    drop: set[tuple[str, float]] = set()
    by = defaultdict(list)
    for s, c, k in units:
        by[k].append((s, c))
    for k, frac in frac_by_class.items():
        v = by.get(k, [])
        n_keep = int(round(frac * len(v)))
        keep_idx = set(rng.choice(len(v), n_keep, replace=False).tolist()) if v else set()
        drop |= {v[i] for i in range(len(v)) if i not in keep_idx}
    keep = part == "train"
    if drop:
        lab = np.array(LABELS)[y]
        for i in np.where(keep & (y != 0) & (lab != "wave"))[0]:
            s = SESSION[i]; t = START[i] + 0.4
            cues = [c for (ss, c) in drop if ss == s]
            if cues and min(abs(np.array(cues) - t)) < 1.5:
                keep[i] = False
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir"); ap.add_argument("name")
    ap.add_argument("--frac-classes", default="", help="e.g. snap,double_snap,clap,double_clap=0.33")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--channels", default="shape,scale,saturation,room")
    ap.add_argument("--frame-aug", default="spin")
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--threshold", type=float, default=0.7)
    args = ap.parse_args()
    W = Path(args.workdir); W.mkdir(exist_ok=True)
    d = np.load("data/windows.npz", allow_pickle=True)
    SESSION, START = d["session"], d["start_s"]
    spans = {s: (float(START[SESSION == s].min()), float(START[SESSION == s].max()) + 2.0) for s in set(SESSION.tolist())}
    plan = sp.resolve(sp.Plan.load(Path("data/split.json")), SESS, spans, R)
    fracs = {}
    if args.frac_classes:
        classes, frac = args.frac_classes.split("="); fracs = {c: float(frac) for c in classes.split(",")}
    per_row = [k for k in d.files if d[k].shape[:1] == d["X"].shape[:1]]
    for seed in [int(s) for s in args.seeds.split(",")]:
        keep = subset_train(d, plan, fracs, seed)
        sub = W / f"ablate_{args.name}_s{seed}.npz"
        np.savez(sub, **{k: (d[k][keep] if k in per_row else d[k]) for k in d.files})
        ck = W / f"ablate_{args.name}_s{seed}.pt"
        t0 = time.time()
        subprocess.run([sys.executable, "-m", "probe.train", "--quiet", "--windows", str(sub), "--out", str(ck), "--seed", str(seed),
                        "--channels", args.channels, "--frame-aug", args.frame_aug, "--epochs", str(args.epochs)], check=True, capture_output=True)
        rec = {"name": args.name, "seed": seed, "fracs": fracs, "epochs": args.epochs, "channels": args.channels,
               "frame_aug": args.frame_aug, "train_windows": int(keep.sum()), "train_s": round(time.time() - t0), "parts": {}}
        for part in ("val", "test"):
            out = subprocess.run([sys.executable, "-m", "probe.split", "score", "--checkpoint", str(ck), "--part", part,
                                  "--threshold", str(args.threshold)], capture_output=True, text=True).stdout
            per = {}
            for line in out.splitlines():
                f = line.split()
                if line.startswith("  ") and len(f) >= 7 and f[1].startswith("n="):
                    per[f[0]] = [int(f[1][2:]), int(f[3]), int(f[5]), int(f[7])] if f[3].isdigit() else None
                if "exact" in line and "on part" in line:
                    head = line
                if line.strip().startswith("ambient"):
                    amb = line.strip()
            rec["parts"][part] = {"head": head.split(":", 1)[1].strip(), "per_class": per, "ambient": amb}
        with open(W / "ablate.jsonl", "a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"{args.name} seed {seed}: val {rec['parts']['val']['head']}  |  test {rec['parts']['test']['head']}  | {rec['parts']['test']['ambient']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
