"""
Assemble recorded sessions into a training set, and report what is in it.

    python -m probe.dataset                          # summarise what exists
    python -m probe.dataset --out data/windows.npz   # export for PyTorch
    python -m probe.dataset --test-session <id>      # hold one out

Exports `X` of shape (N, 3, 50) in g with gravity removed, `y` of shape (N,)
indexing (none, flag, approve), and `session` so the split can be reconstructed
or changed without re-windowing.

The summary is worth reading before training. Class balance, per-session counts
and the ambiguous-window count are all things that quietly ruin a run, and all
are visible here in a second.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from whip import dataset
from whip.registry import DIRECTION_INDEX, DIRECTIONS, load_registry

SESSIONS_DIR = Path("data/sessions")
RAW_DIR = Path("data/raw")

# Sessions certified to contain no gestures. Kept in a file rather than passed as
# flags because the list used to survive only in a shell history: a re-export
# without it silently dropped six sessions and 42% of the corpus, and said
# "wrote data/windows.npz" exactly as if nothing were missing.
NEGATIVES_FILE = Path("data/negative_sessions.txt")


def declared_negatives(path: Path = NEGATIVES_FILE) -> set[str]:
    if not path.exists():
        return set()
    return {
        line.strip() for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def report(windows: list[dataset.Window], labels: list[str], title: str) -> None:
    s = dataset.summarise(windows)
    print(f"\n=== {title} ===")
    print(f"  windows       {s['total']}")
    for name in labels:
        n = s["counts"].get(name, 0)
        print(f"    {name:<14} {n:7d}  {s['balance'].get(name, 0) * 100:5.1f}%")
    positives = sum(s["counts"].get(name, 0) for name in dataset.gesture_names(labels))
    if s["counts"].get("none") and positives:
        print(f"  neg:pos       {s['counts']['none'] / positives:.1f}:1")
    if s["directions"]:
        parts = "  ".join(f"{d}:{s['directions'].get(d, 0)}" for d in DIRECTIONS if d != "none")
        print(f"  directions    {parts}")
    print(f"  sessions      {len(s['sessions'])}")
    for sid, n in sorted(s["sessions"].items()):
        print(f"    {sid:<44} {n:6d}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble sessions into labelled windows")
    parser.add_argument("--dirs", nargs="+", default=[str(SESSIONS_DIR), str(RAW_DIR)],
                        help="directories of captures to include")
    parser.add_argument("--test-session", action="append", default=[],
                        help="session id to hold out for test; repeatable")
    parser.add_argument("--val-session", action="append", default=[])
    parser.add_argument("--out", type=Path, help="write an .npz for PyTorch")
    parser.add_argument("--gesture-duration", type=float, default=None,
                        help="override the per-gesture labelled span, seconds")
    parser.add_argument("--negative", action="append", default=[],
                        help="extra session id you certify contains no gestures; repeatable")
    parser.add_argument("--negatives-file", type=Path, default=NEGATIVES_FILE,
                        help="file of certified-negative session ids")
    args = parser.parse_args()

    negatives = declared_negatives(args.negatives_file) | set(args.negative)
    print(f"{len(negatives)} session(s) certified negative "
          f"(from {args.negatives_file} plus {len(args.negative)} on the command line)")

    registry = load_registry()
    windows: list[dataset.Window] = []
    skipped: list[str] = []
    for d in args.dirs:
        p = Path(d)
        if p.exists():
            w, sk = dataset.load_all(p, args.gesture_duration, negatives, registry=registry)
            windows.extend(w)
            skipped.extend(sk)

    if skipped:
        print(f"skipped {len(skipped)} capture(s):")
        for s_ in skipped:
            print(f"  {s_}")

    if not windows:
        print("no sessions found. Record one:")
        print("  python -m probe.collect --prompts 150 --ring-position 'middle, logo up'")
        return 1

    # Classes materialise from data: the registry declares what MAY exist, the
    # corpus decides what does. Declared-but-absent classes are reported rather
    # than silently missing, because "the model cannot detect snaps" and "nobody
    # has recorded a snap" deserve to look different.
    present = {w.label for w in windows} - {"none"}
    labels = registry.labels_for(present)
    absent = [g for g in registry.training_names() if g not in present]
    if absent:
        print(f"declared but no data yet (record with probe.collect): {', '.join(absent)}")

    report(windows, labels, "all windows")

    if args.test_session or args.val_session:
        parts = dataset.split_by_session(windows, set(args.test_session), set(args.val_session))
        for name in ("train", "val", "test"):
            if parts[name]:
                report(parts[name], labels, name)

    positives = sum(1 for w in windows if w.label != "none")
    if positives == 0:
        print("\n  NOTE: no positive windows. Prompted sessions carry marks;")
        print("  negative-only captures contribute the `none` class.")

    if args.out:
        try:
            import numpy as np
        except ImportError:
            print("\nnumpy is required to export. pip install numpy")
            return 1

        label_index = {name: i for i, name in enumerate(labels)}
        X = np.array([w.axes for w in windows], dtype=np.float32)
        y = np.array([label_index[w.label] for w in windows], dtype=np.int64)
        sess = np.array([w.session_id for w in windows])
        # Window start times, so a single session can be split temporally when
        # there is not yet a second session to hold out. Without these the only
        # available split leaves the test set with no positives at all.
        start = np.array([w.start_s for w in windows], dtype=np.float32)
        direction = np.array([DIRECTION_INDEX[w.direction] for w in windows], dtype=np.int64)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.out, X=X, y=y, session=sess, start_s=start,
                            labels=np.array(labels), direction=direction,
                            direction_names=np.array(DIRECTIONS),
                            format_version=np.array(dataset.FORMAT_VERSION))
        print(f"\nwrote {args.out}  X{X.shape} y{y.shape}  labels {labels}  "
              f"format v{dataset.FORMAT_VERSION}")
        print("  split by session, never by window -- windows overlap 88%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
