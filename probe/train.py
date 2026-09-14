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
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    import torch
    import torch.nn as nn

    from whip import dataset
    from whip import model as gm

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    d = np.load(args.windows, allow_pickle=True)
    try:
        dataset.check_format_version(d)
    except dataset.StaleDataset as exc:
        print(exc)
        return 1
    X = gm.to_model_input(d["X"])
    y, sessions = d["y"], d["session"]

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

    net = getattr(gm, args.architecture)().to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)

    Xtr, ytr = X[train_mask], y[train_mask]
    counts = np.bincount(ytr, minlength=3)
    # Class weights, because `none` outnumbers the gestures roughly 8:1 and an
    # unweighted loss is nearly satisfied by predicting it always.
    weights = torch.tensor(len(ytr) / (3 * np.maximum(counts, 1)),
                           dtype=torch.float32, device=device)
    loss_fn = nn.CrossEntropyLoss(weight=weights)

    xt = torch.tensor(Xtr, device=device)
    yt = torch.tensor(ytr, device=device)

    for epoch in range(args.epochs):
        net.train()
        perm = torch.randperm(len(yt), device=device)
        total = 0.0
        for i in range(0, len(perm), args.batch):
            idx = perm[i:i + args.batch]
            opt.zero_grad()
            loss = loss_fn(net(gm.augment(xt[idx])), yt[idx])
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
            held_out=sorted(held))

    n_params = sum(p.numel() for p in net.parameters())
    print(f"\nwrote {args.out}  {args.architecture} ({n_params:,} params)")
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
