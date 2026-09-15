"""
M2 calibration corpus tools: validate the corpus, plan a labeling session.

    python -m probe.calibrate validate
    python -m probe.calibrate stats
    python -m probe.calibrate plan --session 1 --pairs 40 --seed 7 \
        [--out data/sessions/plan_s1.json]

`validate` exits 0 on a clean corpus and 2 with defects listed, so it can gate
a session the way probe.stream gates M0. `plan` is deterministic in
(--seed, --session); the emitted JSON is the artifact the labeling UI replays,
and re-running the command reproduces it byte for byte.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from whip import corpus


def cmd_validate() -> int:
    taxonomy = corpus.load_taxonomy()
    items = corpus.load_items()
    problems = corpus.validate(taxonomy, items)
    gold = sum(1 for it in items if it.status == "gold")
    print(f"{len(taxonomy)} dimensions, {len(items)} items ({gold} gold, "
          f"{len(items) - gold} spec)")
    if problems:
        for p in problems:
            print(f"  DEFECT {p}")
        print(f"FAIL: {len(problems)} defect(s)")
        return 2
    print("PASS")
    return 0


def cmd_stats() -> int:
    taxonomy = corpus.load_taxonomy()
    items = corpus.load_items()
    print(f"{'dimension':<14} {'gold':>4} {'spec':>4}  domains")
    for key in taxonomy:
        dim_items = [it for it in items if it.dimension == key]
        gold = [it for it in dim_items if it.status == "gold"]
        spec = [it for it in dim_items if it.status == "spec"]
        domains = sorted({it.domain for it in dim_items})
        print(f"{key:<14} {len(gold):>4} {len(spec):>4}  {', '.join(domains)}")
        for it in gold:
            ratio = len(it.a.text) / max(1, len(it.b.text))
            longer = it.a.pole if ratio > 1 else it.b.pole
            print(f"  {it.id}: a/b length ratio {ratio:.2f} "
                  f"(longer: {longer})"
                  f"{'  [sentinel]' if it.sentinel else ''}")
    return 0


def cmd_plan(session: int, pairs: int, seed: int, out: str | None) -> int:
    taxonomy = corpus.load_taxonomy()
    items = corpus.load_items()
    problems = corpus.validate(taxonomy, items)
    if problems:
        print(f"corpus has {len(problems)} defect(s); run validate first")
        return 2
    plan = corpus.plan_session(taxonomy, items, session, pairs, seed)
    text = json.dumps(plan, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n")
        print(f"wrote {out}: {len(plan['presentations'])} presentations")
    else:
        print(text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    sub.add_parser("stats")
    plan = sub.add_parser("plan")
    plan.add_argument("--session", type=int, required=True)
    plan.add_argument("--pairs", type=int, default=40)
    plan.add_argument("--seed", type=int, required=True)
    plan.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.cmd == "validate":
        return cmd_validate()
    if args.cmd == "stats":
        return cmd_stats()
    return cmd_plan(args.session, args.pairs, args.seed, args.out)


if __name__ == "__main__":
    sys.exit(main())
