"""
Measure one factor at a time, under the corrected protocol.

    python -m probe.ablate --seeds 5

Every configuration is trained and scored identically; only the named factor
moves. Conflating several changes into one comparison is the specific mistake
this project's architecture table made -- "+12.8 points from fixing the pooling"
also changed the block type, the width and the parameter count.

**How the negatives are split, and why.** Each negative session is cut in half by
time. The first half goes into training, the second half is scored. This matters
most for waving: the earlier finding that "13 architectures all fail on waving,
therefore the distinction is absent from the data" was circular, because the
waving clip was held out of training in every one of those runs. A model cannot
reject something it has never seen. Splitting lets it learn from one stretch and
be tested on another.

The halves of a 1.7-minute clip are still highly correlated -- same person, same
sitting, same motion -- so a good number here is necessary and not sufficient.
It is the honest best available until more high-energy negatives exist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from whip import dataset, evaluate, events, sampling

SESSIONS = Path("data/sessions")

GESTURE_HELD_OUT = "prompted_20260912_013715"
CALIBRATION = "gate_imm4_20260906_210533"          # typing, the longest negative
REPORT_ON = {
    "typing": "gate_imm4_20260906_210533",
    "waving": "negative_20260908_202143",
    "idle": "negative_20260908_201610",
    "walking": "negative_20260908_200022",
}

# (label, channels, loud_factor, motion_class)
#
# The motion axis is the question: is a separate class for "moving, but not a
# gesture" better than leaving those windows in `none` and reweighting them?
# The reweighting exists only because loud windows were 4.7% of `none` and class
# weights could not reach them. A real class gets a class weight directly, and
# stops `none` having to mean both silence and a violently moving hand.
CONFIGS = [
    ("none-only, no weight",        ("shape", "scale"), 1.0, False),
    ("none-only, weight x10",       ("shape", "scale"), 10.0, False),
    ("motion class",                ("shape", "scale"), 1.0, True),
    ("motion class + weight x10",   ("shape", "scale"), 10.0, True),
    ("motion + saturation",         ("shape", "scale", "saturation"), 1.0, True),
    ("motion + gravity/linear",     ("gravity", "linear", "scale"), 1.0, True),
]


def truth_for(session_id: str) -> list[tuple[float, str]]:
    path = SESSIONS / f"{session_id}.notes.json"
    if not path.exists():
        return []
    notes = json.loads(path.read_text())
    return [(m["cue_at"] + 0.6, m["label"]) for m in notes.get("marks", [])
            if m.get("label") in ("flag", "approve")]


def main() -> int:
    parser = argparse.ArgumentParser(description="One-factor-at-a-time ablation")
    parser.add_argument("--windows", type=Path, default=Path("data/windows.npz"))
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--budget-per-hour", type=float, default=1.0)
    args = parser.parse_args()

    import torch
    import torch.nn as nn

    from whip import model as gm

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    d = np.load(args.windows, allow_pickle=True)
    dataset.check_format_version(d)
    raw, y, SESS, START = d["X"], d["y"], d["session"], d["start_s"]
    all_names = [str(s) for s in d["labels"]]

    def labelling(with_motion: bool):
        """Labels and class names with the `motion` class kept or folded back in."""
        if with_motion:
            return y, all_names
        # Fold `motion` back into `none` and renumber so the classes stay
        # contiguous -- this reproduces the pre-motion labelling exactly, which
        # is what makes the comparison an A/B on one factor rather than on the
        # dataset.
        mi = all_names.index(dataset.MOTION_LABEL)
        kept = [i for i in range(len(all_names)) if i != mi]
        remap = {old: new for new, old in enumerate(kept)}
        remap[mi] = 0
        return np.array([remap[int(v)] for v in y]), [all_names[i] for i in kept]
    peaks = sampling.window_peaks(raw)
    budget = args.budget_per_hour / 60.0

    # --- split every negative session in half by time --------------------------
    train_half = np.zeros(len(y), dtype=bool)
    score_half = {}
    for name, sid in REPORT_ON.items():
        sel = SESS == sid
        if not sel.any():
            continue
        lo, hi = START[sel].min(), START[sel].max()
        cut = lo + (hi - lo) * 0.5
        train_half |= sel & (START + events.WINDOW_S <= cut)
        score_half[name] = sel & (START >= cut + events.WINDOW_S)

    other = ~np.isin(SESS, [GESTURE_HELD_OUT] + list(REPORT_ON.values()))
    train_mask = other | train_half

    # The budget has to be expressible by the amount of negative data being
    # scored, or every configuration is being ranked on where zero events
    # happened to fall. `evaluate.calibrate` refuses this; so should the ablation.
    scoring_minutes = sum(
        (START[m].max() - START[m].min()) / 60 for m in score_half.values() if m.any())
    floor = evaluate.min_measurable_rate_per_minute(scoring_minutes)
    if budget < floor:
        print(f"WARNING: the {args.budget_per_hour:.2f}/hour budget "
              f"({budget:.4f}/min) is below what {scoring_minutes:.1f} min of scoring")
        print(f"negatives can express. The smallest non-zero rate measurable here is")
        print(f"{floor:.4f}/min = {floor * 60:.1f}/hour, so 'recall at budget' below that")
        print("means 'recall wherever zero events happened to occur', not a measured")
        print("false-positive rate. Every row inherits that, and the ranking is")
        print("dominated by the measurement floor rather than by the models.\n")

    print(f"{args.seeds} seeds, {args.epochs} epochs. Held out entirely: {GESTURE_HELD_OUT}.")
    print("Every negative session split in half by time: first half trains, second half scores.")
    print(f"Threshold calibrated on the {CALIBRATION} scoring half, "
          f"then recall read on {GESTURE_HELD_OUT}.\n")
    info = sampling.describe(peaks[train_mask], y[train_mask])
    print(f"training set: {int(train_mask.sum())} windows, "
          f"{info['n_loud_negatives']} loud negatives of {info['n_negatives']} "
          f"({info['loud_negative_share'] * 100:.1f}%)\n")

    channel_cache: dict[tuple, np.ndarray] = {}

    def run(channels, loud_factor, with_motion, seed):
        torch.manual_seed(seed)
        np.random.seed(seed)
        if channels not in channel_cache:
            channel_cache[channels] = gm.to_model_input(raw, channels)
        X = channel_cache[channels]
        y_used, class_names = labelling(with_motion)
        Xtr, ytr = X[train_mask], y_used[train_mask]
        net = gm.GestureNet(n_channels=X.shape[1], n_classes=len(class_names)).to(device)
        opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-3)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
        n_cls = len(class_names)
        counts = np.bincount(ytr, minlength=n_cls)
        cw = torch.tensor(len(ytr) / (n_cls * np.maximum(counts, 1)),
                          dtype=torch.float32, device=device)
        loss_fn = nn.CrossEntropyLoss(weight=cw, reduction="none")
        gesture_ids = [class_names.index(n) for n in dataset.GESTURE_LABELS]
        loud_g = sampling.gesture_peak_percentile(peaks[train_mask], ytr, 10.0,
                                                  gesture_indices=gesture_ids)
        sw = sampling.loud_negative_weights(peaks[train_mask], ytr, loud_g, loud_factor)
        xt = torch.tensor(Xtr, device=device)
        yt = torch.tensor(ytr, device=device)
        wt = torch.tensor(sw, dtype=torch.float32, device=device)
        for _ in range(args.epochs):
            net.train()
            perm = torch.randperm(len(yt), device=device)
            for i in range(0, len(perm), 128):
                idx = perm[i:i + 128]
                opt.zero_grad()
                per = loss_fn(net(gm.augment(xt[idx])), yt[idx])
                ((per * wt[idx]).sum() / wt[idx].sum()).backward()
                opt.step()
            sched.step()
        net.eval()

        def probs(mask):
            order = np.where(mask)[0][np.argsort(START[mask])]
            with torch.no_grad():
                p = torch.softmax(net(torch.tensor(X[order], device=device)), 1).cpu().numpy()
            st = START[order].tolist()
            return p, st, (st[-1] - st[0]) / 60 if len(st) > 1 else 0.0

        # Score false positives on the pooled scoring halves, not on one activity.
        # A budget is a statement about mixed realistic wear, and pooling also
        # makes the curve comparable across configurations -- reading recall at a
        # matched false-positive rate is the only way to compare two models
        # without comparing their confidence calibration instead.
        gp, gs, _ = probs(SESS == GESTURE_HELD_OUT)
        truth = truth_for(GESTURE_HELD_OUT)
        # `motion` never fires, so recall and false positives mean the same thing
        # in both arms and the comparison stays honest.

        # One segment per session, never concatenated: events.detect has no notion
        # of time, so joining sessions end to end lets windows from different
        # recordings form a run that never happened.
        segments, pooled_minutes = [], 0.0
        for mask in score_half.values():
            if not mask.any():
                continue
            p_, st_, mins_ = probs(mask)
            segments.append((p_, st_))
            pooled_minutes += mins_

        points = evaluate.curve(gp, gs, truth, segments, pooled_minutes, class_names,
                                min_run=events.MIN_RUN, max_run=events.MAX_RUN)
        best = evaluate.recall_at_budget(points, budget)
        auc = evaluate.area_under_curve(points, budget)

        thr = best.threshold if best else 0.999
        hits = evaluate.gesture_hits(
            events.detect(evaluate.labels_at(gp, class_names, thr), gs), truth)
        fps = {}
        for name, mask in score_half.items():
            p, st, mins = probs(mask)
            n = len(events.detect(evaluate.labels_at(p, class_names, thr), st))
            fps[name] = evaluate.rate_per_minute(n, mins)
        return thr, hits, fps, auc, pooled_minutes

    print(f"{'configuration':<32} {'AUC':>6} {'recall@budget':>14} {'95% CI':>15} "
          f"{'thr':>5} {'wave/min':>9} {'idle/min':>9}")
    print("-" * 104)
    rows = []
    for label, channels, factor, with_motion in CONFIGS:
        all_hits, thrs, fp_acc, pooled, aucs = [], [], {}, [], []
        minutes = 0.0
        for seed in range(args.seeds):
            thr, hits, fps, auc, minutes = run(channels, factor, with_motion, seed)
            thrs.append(thr)
            all_hits.append(np.mean(hits))
            pooled.extend(hits)
            aucs.append(auc)
            for k, v in fps.items():
                fp_acc.setdefault(k, []).append(v)
        # Sampling interval over gestures, pooled across seeds; seed spread
        # reported separately. They are different quantities and both belong here.
        ci = evaluate.bootstrap_recall_ci(pooled)
        rows.append((label, np.mean(aucs), np.mean(all_hits), ci))
        print(f"{label:<32} {np.mean(aucs) * 100:5.1f}% "
              f"{np.mean(all_hits) * 100:7.1f}+/-{np.std(all_hits) * 100:<4.1f} "
              f"{ci[0] * 100:6.1f}-{ci[1] * 100:5.1f}% "
              f"{np.mean(thrs):5.2f} "
              f"{np.mean(fp_acc.get('waving', [np.nan])):9.2f} "
              f"{np.mean(fp_acc.get('idle', [np.nan])):9.2f}", flush=True)

    print(f"\n  AUC is mean recall across the curve up to the budget, on {minutes:.1f} min of")
    print("  pooled scoring halves. It is the comparable number: reading recall at a")
    print("  matched false-positive rate is the only way to compare two models without")
    print("  comparing their confidence calibration instead.")
    print("\n  recall +/- is seed spread; the bracket is the sampling interval over")
    print("  gestures. Both are needed, and both are wide: at 64 gestures the sampling")
    print("  interval alone is about +/-5 points here.")

    best = max(rows, key=lambda r: r[1])
    contenders = [r for r in rows if r[3][1] >= best[3][0]]
    print(f"\n  Best AUC: {best[0]} ({best[1] * 100:.1f}%).")
    if len(contenders) > 1:
        print(f"  {len(contenders)} of {len(rows)} configurations have overlapping recall")
        print("  intervals with it, so this is a tie, not a winner:")
        for r in contenders:
            print(f"    {r[0]}")
    print("\n  Waving halves come from one 1.7-minute clip, so a good number there is")
    print("  necessary and not sufficient.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
