"""
Train a gesture classifier and save it with its provenance.

    python -m probe.train --held-out prompted_20260912_013715 \
                          --held-out gate_imm4_20260906_210533

Sessions named with `--held-out` are excluded from training. Everything else is
used. The checkpoint records which sessions it saw, so `probe.rollout` can refuse
to count recall on a session the model memorised -- a distinction that inflated
every headline number in this project before it was enforced.

Hold out at least one **negative** session as well as the gesture session. Without
one there is nowhere to calibrate a threshold except the data being reported on,
and `probe.rollout` will refuse to run rather than produce a number that looks
measured and is not.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a gesture classifier")
    parser.add_argument("--windows", type=Path, default=Path("data/windows.npz"))
    parser.add_argument("--out", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--held-out", action="append", default=[],
                        help="session id to exclude from training; repeatable")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-3)
    parser.add_argument("--batch", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--architecture", default="GestureNet", choices=("GestureNet", "CompactNet"))
    # Default 0: measured (2 seeds, held out), training the direction head at
    # 0.3 cost ~10 points of gesture recall at the current 264-gesture scale --
    # the trunk cannot afford the second objective yet. The head stays in the
    # architecture; enable with more data and re-measure.
    parser.add_argument("--direction-weight", type=float, default=0.0,
                        help="auxiliary direction-head loss weight; 0 disables (measured default)")
    parser.add_argument("--frame-aug", default="spin", choices=("none", "flips", "spin"),
                        help="'spin' (default): each batch is rotated by a random full spin about the "
                             "finger axis, windows and gravity together -- the ring may sit anywhere "
                             "around the finger but must point the known way (wear rule), so room-frame "
                             "left/right stays learnable; 'flips': also random half-turns, blind to which "
                             "way the ring is on (and to room-left vs room-right); 'none': the small "
                             "spin only, on the shape channels")
    parser.add_argument("--channels", default="shape,scale,saturation",
                        help="comma-separated channel groups; see model.to_model_input")
    parser.add_argument("--loud-factor", type=float, default=1.0,
                        help="how much more a loud negative is worth than a quiet one. "
                             "1.0 disables the reweighting")
    parser.add_argument("--loud-g", type=float, default=None,
                        help="amplitude boundary of the overlap region; "
                             "default is the 10th percentile of gesture peaks")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    import torch
    import torch.nn as nn

    from whip import dataset
    from whip import model as gm
    from whip import sampling

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    d = np.load(args.windows, allow_pickle=True)
    try:
        dataset.check_format_version(d)
    except dataset.StaleDataset as exc:
        print(exc)
        return 1
    channels = tuple(c.strip() for c in args.channels.split(",") if c.strip())
    raw = d["X"]
    X = gm.to_model_input(raw, channels, gravity=d["gravity"] if "gravity" in d else None)
    y, sessions = d["y"], d["session"]
    labels = [str(l) for l in d["labels"]]
    direction = d["direction"] if "direction" in d else np.zeros(len(y), dtype=np.int64)
    direction_names = ([str(n) for n in d["direction_names"]]
                       if "direction_names" in d else ["none", "up", "down", "left", "right"])
    peaks = sampling.window_peaks(raw)

    held = set(args.held_out)
    unknown = held - set(sessions.tolist())
    if unknown:
        print(f"unknown session id(s): {', '.join(sorted(unknown))}")
        return 1

    train_mask = ~np.isin(sessions, list(held))
    if not train_mask.any():
        print("nothing left to train on")
        return 1

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    net = getattr(gm, args.architecture)(n_channels=X.shape[1], n_classes=len(labels)).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)

    Xtr, ytr = X[train_mask], y[train_mask]
    dtr = direction[train_mask]
    counts = np.bincount(ytr, minlength=len(labels))
    # Class weights, because `none` outnumbers the gestures roughly 8:1 and an
    # unweighted loss is nearly satisfied by predicting it always.
    weights = torch.tensor(len(ytr) / (len(labels) * np.maximum(counts, 1)),
                           dtype=torch.float32, device=device)
    loss_fn = nn.CrossEntropyLoss(weight=weights, reduction="none")
    direction_loss_fn = nn.CrossEntropyLoss()

    # Per-sample weights on top of the class weights, correcting a different
    # imbalance. Class weights fix "there are 8x more none windows than gestures".
    # These fix "the ~5% of negatives that are as loud as a gesture are the ones
    # that decide the false-positive rate, and cross-entropy is nearly
    # indifferent to all of them".
    from whip.dataset import gesture_names
    gesture_ids = [labels.index(n) for n in gesture_names(labels)]
    loud_g = args.loud_g if args.loud_g is not None else sampling.gesture_peak_percentile(
        peaks[train_mask], ytr, 10.0, gesture_indices=gesture_ids)
    sample_w = sampling.loud_negative_weights(peaks[train_mask], ytr, loud_g, args.loud_factor)
    if args.loud_factor != 1.0 and not args.quiet:
        info = sampling.describe(peaks[train_mask], ytr, loud_g)
        print(f"  loud negatives: {info['n_loud_negatives']} of {info['n_negatives']} "
              f"({info['loud_negative_share'] * 100:.1f}%) at >= {loud_g:.2f} g, "
              f"weighted x{args.loud_factor:g}")

    xt = torch.tensor(Xtr, device=device)
    # Frame augmentation works on the RAW window and its gravity vector, before
    # the channels are derived, so every channel group sees a consistent frame.
    raw_tr = raw[train_mask]
    grav_tr = d["gravity"][train_mask] if "gravity" in d else None
    frame_rng = np.random.default_rng(args.seed)
    yt = torch.tensor(ytr, device=device)
    wt = torch.tensor(sample_w, dtype=torch.float32, device=device)
    dt = torch.tensor(dtr, device=device)
    # Direction supervision exists only where a prompt recorded one; everything
    # else (negatives, spans, "any"-direction prompts) is masked out rather than
    # trained toward a fake "none" answer it would then predict everywhere.
    directed = dt > 0

    for epoch in range(args.epochs):
        net.train()
        perm = torch.randperm(len(yt), device=device)
        total = 0.0
        for i in range(0, len(perm), args.batch):
            idx = perm[i:i + args.batch]
            opt.zero_grad()
            if args.frame_aug in ("flips", "spin"):
                ii = idx.cpu().numpy()
                frames = (gm.random_frames(len(ii), frame_rng, flips=True) if args.frame_aug == "flips"
                          else gm.random_frames(len(ii), frame_rng, flips=False, spin_deg=180.0))
                xr, gr = gm.rotate_frame(raw_tr[ii], grav_tr if grav_tr is None else grav_tr[ii], frames)
                xb = torch.tensor(gm.to_model_input(xr, channels, gravity=gr), device=device)
                xb = gm.augment(xb, rotation_deg=0.0)   # spin already applied to the frame
            else:
                xb = gm.augment(xt[idx])
            gesture_logits, direction_logits = net.forward_heads(xb)
            per_sample = loss_fn(gesture_logits, yt[idx])
            loss = (per_sample * wt[idx]).sum() / wt[idx].sum()
            mask = directed[idx]
            if mask.any():
                # 0.3: enough for the trunk to be pushed toward encoding which
                # way the wrist rotated, small enough that the gesture head --
                # the one that actually fires events -- stays the objective.
                loss = loss + args.direction_weight * direction_loss_fn(
                    direction_logits[mask], dt[idx][mask])
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(idx)
        sched.step()
        if not args.quiet and (epoch + 1) % 20 == 0:
            print(f"  epoch {epoch + 1:3d}/{args.epochs}   loss {total / len(perm):.4f}")

    net.eval().cpu()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    gm.save(net, args.out,
            trained_on=[s for s in sorted(set(sessions.tolist())) if s not in held],
            held_out=sorted(held), labels=labels, channels=channels,
            direction_names=direction_names,
            direction_trained=args.direction_weight > 0)

    n_params = sum(p.numel() for p in net.parameters())
    print(f"\nwrote {args.out}  {args.architecture} ({n_params:,} params)")
    print(f"  classes    {', '.join(labels)}")
    print(f"  channels   {','.join(channels)}   direction weight {args.direction_weight}")
    print(f"  trained on {train_mask.sum()} windows from "
          f"{len(set(sessions[train_mask].tolist()))} sessions")
    print(f"  held out   {', '.join(sorted(held)) if held else '(nothing)'}")

    # A held-out negative is what makes an honest threshold possible. Warn here
    # rather than letting rollout discover it, since by then the training is done.
    from probe.rollout import truth_for
    if not any(not truth_for(s) for s in held):
        print("\n  WARNING: no negative session held out. There will be nowhere to")
        print("  calibrate a threshold except the data being reported on, and")
        print("  probe.rollout will refuse to score this checkpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
