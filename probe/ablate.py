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

CONFIGS = [
    ("baseline  shape+scale",            ("shape", "scale"), 1.0),
    ("+ loud-negative weight x10",       ("shape", "scale"), 10.0),
    ("+ loud-negative weight x30",       ("shape", "scale"), 30.0),
    ("gravity/linear split",             ("gravity", "linear", "scale"), 1.0),
    ("gravity/linear + weight x10",      ("gravity", "linear", "scale"), 10.0),
    ("+ saturation channel",             ("shape", "scale", "saturation"), 1.0),
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
    class_names = [str(s) for s in d["labels"]]
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

    print(f"{args.seeds} seeds, {args.epochs} epochs. Held out entirely: {GESTURE_HELD_OUT}.")
    print("Every negative session split in half by time: first half trains, second half scores.")
    print(f"Threshold calibrated on the {CALIBRATION} scoring half, "
          f"then recall read on {GESTURE_HELD_OUT}.\n")
    info = sampling.describe(peaks[train_mask], y[train_mask])
    print(f"training set: {int(train_mask.sum())} windows, "
          f"{info['n_loud_negatives']} loud negatives of {info['n_negatives']} "
          f"({info['loud_negative_share'] * 100:.1f}%)\n")

    def run(channels, loud_factor, seed):
        torch.manual_seed(seed)
        np.random.seed(seed)
        X = gm.to_model_input(raw, channels)
        Xtr, ytr = X[train_mask], y[train_mask]
        net = gm.GestureNet(n_channels=X.shape[1]).to(device)
        opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-3)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
        counts = np.bincount(ytr, minlength=3)
        cw = torch.tensor(len(ytr) / (3 * np.maximum(counts, 1)),
                          dtype=torch.float32, device=device)
        loss_fn = nn.CrossEntropyLoss(weight=cw, reduction="none")
        loud_g = sampling.gesture_peak_percentile(peaks[train_mask], ytr, 10.0)
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

        cal = probs(score_half["typing"])
        thr = evaluate.calibrate(*cal[:2], cal[2], class_names, budget,
                                 min_run=events.MIN_RUN, max_run=events.MAX_RUN, strict=False)
        gp, gs, _ = probs(SESS == GESTURE_HELD_OUT)
        hits = evaluate.gesture_hits(
            events.detect(evaluate.labels_at(gp, class_names, thr), gs), truth_for(GESTURE_HELD_OUT))
        fps = {}
        for name, mask in score_half.items():
            if name == "typing":
                continue
            p, st, mins = probs(mask)
            n = len(events.detect(evaluate.labels_at(p, class_names, thr), st))
            fps[name] = evaluate.rate_per_minute(n, mins)
        return thr, hits, fps

    print(f"{'configuration':<32} {'thr':>5} {'recall':>8} {'95% CI':>15} "
          f"{'wave/min':>9} {'idle/min':>9} {'walk/min':>9}")
    print("-" * 100)
    for label, channels, factor in CONFIGS:
        all_hits, thrs, fp_acc, pooled = [], [], {}, []
        for seed in range(args.seeds):
            thr, hits, fps = run(channels, factor, seed)
            thrs.append(thr)
            all_hits.append(np.mean(hits))
            pooled.extend(hits)
            for k, v in fps.items():
                fp_acc.setdefault(k, []).append(v)
        # Sampling interval over gestures, pooled across seeds; seed spread
        # reported separately. They are different quantities and both belong here.
        ci = evaluate.bootstrap_recall_ci(pooled)
        print(f"{label:<32} {np.mean(thrs):5.2f} "
              f"{np.mean(all_hits) * 100:6.1f}+/-{np.std(all_hits) * 100:<3.1f} "
              f"{ci[0] * 100:6.1f}-{ci[1] * 100:5.1f}% "
              f"{np.mean(fp_acc.get('waving', [np.nan])):9.2f} "
              f"{np.mean(fp_acc.get('idle', [np.nan])):9.2f} "
              f"{np.mean(fp_acc.get('walking', [np.nan])):9.2f}", flush=True)

    print("\n  recall +/- is seed spread; the bracket is the sampling interval over gestures.")
    print("  Both are needed: at 64 gestures the sampling interval alone is about +/-11 points.")
    print("  Waving halves are from one 1.7-minute clip, so a good number there is")
    print("  necessary and not sufficient.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
