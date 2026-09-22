"""
The fixed train / val / test split.

    python -m probe.split make                 # data/split.json (seed, fractions, chunk) -> data/split/{train,val,test}.npz
    python -m probe.split report               # per-class gesture counts per part
    python -m probe.split score --part val     # one checkpoint, scored on one part: per class, confusions, ambient FP
    python -m probe.split score --part test --checkpoint data/work/x.pt

Train on the train part:  python -m probe.train --windows data/split/train.npz --out data/work/x.pt
(no --held-out needed: the parts are already disjoint). The deployed
checkpoint trains on train + val (`--windows data/split/trainval.npz`).
The test part is scored once, at the end, and never tuned on.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from whip import audit, dataset, evaluate, events, split as sp
from whip.registry import load_registry

SESSIONS = Path("data/sessions")
PLAN = Path("data/split.json")
OUT = Path("data/split")
R = load_registry()


def _load_plan(windows) -> sp.Plan:
    if PLAN.exists():
        plan = sp.Plan.load(PLAN)
    else:
        plan = sp.Plan(seed=sp.DEFAULT_PLAN["seed"], fractions=list(sp.DEFAULT_PLAN["fractions"]), chunk_s=sp.DEFAULT_PLAN["chunk_s"])
        plan.save(PLAN)
        print(f"wrote {PLAN} (default plan)")
    return sp.resolve(plan, SESSIONS, _spans(windows), R)


def _spans(windows) -> dict[str, tuple[float, float]]:
    out = {}
    for sid in set(windows["session"].tolist()):
        s = windows["start_s"][windows["session"] == sid]
        out[sid] = (float(s.min()), float(s.max()) + sp.WINDOW_S)
    return out


def marks_in_part(plan: sp.Plan, part: str, spans) -> dict[str, list[tuple[float, str]]]:
    """Cued impulsive gestures (valid only) whose windows live in `part`, per session."""
    out: dict[str, list[tuple[float, str]]] = {}
    for sid in spans:
        notes = SESSIONS / f"{sid}.notes.json"
        if not notes.exists():
            continue
        bad = set(audit.excluded_cues(SESSIONS / f"{sid}.jsonl"))
        for m in json.loads(notes.read_text()).get("marks", []):
            if "until" in m or m["cue_at"] in bad:
                continue
            spec = R.resolve(m.get("label", ""))
            if spec is None or sp.part_of_mark(plan, sid, m["cue_at"]) != part:
                continue
            d = m.get("direction", "none")
            name = f"{spec.name}_{d}" if spec.split_by_direction and d in ("up", "down", "left", "right") else spec.name
            out.setdefault(sid, []).append((m["cue_at"] + 0.6, name))
    return out


def make(args) -> int:
    d = np.load(args.windows, allow_pickle=True)
    dataset.check_format_version(d)
    plan = _load_plan(d); spans = _spans(d)
    parts = np.array([sp.part_of_window(plan, s, float(t)) or "" for s, t in zip(d["session"], d["start_s"])])
    OUT.mkdir(parents=True, exist_ok=True)
    per_row = [k for k in d.files if d[k].shape[:1] == d["X"].shape[:1]]
    for part in sp.PARTS + ("trainval",):
        keep = np.isin(parts, ["train", "val"]) if part == "trainval" else parts == part
        np.savez(OUT / f"{part}.npz", **{k: (d[k][keep] if k in per_row else d[k]) for k in d.files})
        print(f"wrote {OUT / f'{part}.npz'}  windows {int(keep.sum())}")
    print(f"dropped {int((parts == '').sum())} windows straddling a cut")
    return report(args)


def report(args) -> int:
    d = np.load(args.windows, allow_pickle=True); plan = _load_plan(d); spans = _spans(d)
    labels = [str(s) for s in d["labels"]]
    print("\ngestures (valid, cued) per class per part -- what each part can train or score:")
    table: dict[str, Counter] = defaultdict(Counter)
    for part in sp.PARTS:
        for sid, ms in marks_in_part(plan, part, spans).items():
            for _, name in ms:
                table[name][part] += 1
    print(f"  {'class':20s} {'train':>6s} {'val':>6s} {'test':>6s}")
    for name in [l for l in labels if l in table] + sorted(set(table) - set(labels)):
        c = table[name]; print(f"  {name:20s} {c['train']:6d} {c['val']:6d} {c['test']:6d}")
    parts = np.array([sp.part_of_window(plan, s, float(t)) or "" for s, t in zip(d["session"], d["start_s"])])
    print("\nwindows per part (all classes incl. none and wave):", dict(Counter(parts.tolist())))
    lab = np.array(labels)[d["y"]]
    for part in sp.PARTS:
        c = Counter(lab[parts == part].tolist())
        print(f"  {part:5s} none {c.get('none', 0):6d}  wave {c.get('wave', 0):4d}")
    print(f"seed {plan.seed}, fractions {plan.fractions}, chunk {plan.chunk_s:.0f} s; sessions {len(spans)}")
    return 0


def score(args) -> int:
    import torch
    from whip import model as gm

    d = np.load(args.windows, allow_pickle=True); plan = _load_plan(d); spans = _spans(d)
    labels = [str(s) for s in d["labels"]]; cn = R.collapsed_names(labels)
    model, meta = gm.load(args.checkpoint); model.eval()
    policies = R.policies(labels); policies_c = R.policies(cn)
    if args.min_run is not None:
        from whip.events import RunPolicy
        policies = {k: (RunPolicy(args.min_run, v.max_run, v.refractory_s) if v.max_run is not None else v) for k, v in policies.items()}
        policies_c = {k: (RunPolicy(args.min_run, v.max_run, v.refractory_s) if v.max_run is not None else v) for k, v in policies_c.items()}
    part_marks = marks_in_part(plan, args.part, spans)
    parts = np.array([sp.part_of_window(plan, s, float(t)) or "" for s, t in zip(d["session"], d["start_s"])])
    per_class = defaultdict(lambda: [0, 0, 0, 0]); conf = Counter(); fp_minutes = 0.0; fp_events = Counter()
    for sid in sorted(spans):
        in_part = (d["session"] == sid) & (parts == args.part)
        if not in_part.any():
            continue
        # Run the model over the WHOLE session in time order, as deployment
        # does, and count only what belongs to this part: a gesture's later
        # windows can sit in a dropped boundary zone next to a gesture of
        # another part, and scoring on the part's windows alone cut those
        # runs short (p(true) = 1.00, run 2, no event). Nothing here trains
        # on a val/test gesture's windows -- they were dropped, not moved.
        sel = d["session"] == sid
        order = np.where(sel)[0][np.argsort(d["start_s"][sel])]; starts = d["start_s"][order]
        part_here = parts[order] == args.part
        with torch.no_grad():
            probs = torch.softmax(model(torch.tensor(gm.to_model_input(d["X"][order], meta["channels"], gravity=d["gravity"][order]))), 1).numpy()
        ev = events.detect(evaluate.labels_at(probs, labels, args.threshold), starts.tolist(), policies=policies)
        evc = events.detect(evaluate.labels_at(R.collapse_probabilities(probs, labels), cn, args.threshold), starts.tolist(), policies=policies_c)
        truth = part_marks.get(sid, [])
        if not truth and not sid.startswith("prompted_"):
            # a negative recording: count minutes and events on this part's
            # none-windows only (span-labelled windows are not negatives)
            neg = np.where(part_here & (d["y"][order] == 0))[0]
            fp_minutes += len(neg) * events.STRIDE_S / 60
            neg_starts = set(np.round(starts[neg], 3).tolist())
            for e in evc:
                if round(float(e.start_s), 3) in neg_starts: fp_events[e.label] += 1
            continue
        hx = evaluate.gesture_hits(ev, truth); ht = evaluate.gesture_hits(evc, [(t, R.collapse(n)[0]) for t, n in truth])
        ha = evaluate.gesture_hits(evc, [(t, R.collapse(n)[0]) for t, n in truth], require_class=False)
        for (t, name), a, b, c in zip(truth, hx, ht, ha):
            p = per_class[name]; p[0] += 1; p[1] += a; p[2] += b; p[3] += c
            if not a:
                fired = [e.label for e in ev if abs(e.centre_s - t) <= 0.75]; conf[(name, fired[0] if fired else "-")] += 1
    n = sum(v[0] for v in per_class.values())
    print(f"{args.checkpoint} on part '{args.part}', thr {args.threshold}: exact {sum(v[1] for v in per_class.values())}/{n}  "
          f"type {sum(v[2] for v in per_class.values())}/{n}  any {sum(v[3] for v in per_class.values())}/{n}")
    for name in [l for l in labels if l in per_class]:
        v = per_class[name]; print(f"  {name:20s} n={v[0]:3d}  exact {v[1]:3d} ({100*v[1]/v[0]:5.1f}%)  type {v[2]:3d}  any {v[3]:3d}")
    if fp_minutes:
        tot = sum(fp_events.values())
        print(f"  ambient ({fp_minutes:.1f} min in this part): {tot} events = {60*tot/fp_minutes:.1f}/h  {dict(fp_events)}")
    print("  confusions:", {f"{a} -> {b}": c for (a, b), c in conf.most_common(12)})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("make", "report", "score"))
    parser.add_argument("--windows", type=Path, default=Path("data/windows.npz"))
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--part", default="val", choices=sp.PARTS)
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--min-run", type=int, default=None, help="override the impulsive gestures' minimum run (default: registry, 3)")
    args = parser.parse_args()
    return {"make": make, "report": report, "score": score}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
