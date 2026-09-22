"""
M4-M6 dry run: exercise the whole chain on synthetic labels, before any real
session exists.

    python -m probe.pipeline dryrun --layer agency --sessions 4
    python -m probe.pipeline contextfile --preferences data/calibration/preferences.json
    python -m probe.pipeline judgecheck --accuracy 0.93

`dryrun` plants a known preference in a synthetic persona -- including a
conditional one -- then runs: sessions -> labels -> preferences.json -> context
file -> reward -> three-arm adherence sweep. It passes when the chain recovers
what was planted and the sweep separates the arms.

**What it proves and what it does not.** It proves the components wire together
and the metrics can see an effect of the shape M6 hypothesises. It is not
evidence about anyone's preferences and not a result about weights versus
context: the arms are simulated by `whip.persona.simulate_response`, which was
written to contain the effect. The same distinction as `probe/simulate.py`,
which fabricates captures to exercise the M0 pipeline without a ring.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from whip import arms, corpus, labeling, persona, reward

FILLER = ("The archive retains quarterly summaries for each region. Figures are "
          "restated when a later submission supersedes an earlier one. Regional "
          "totals are published on the fifteenth of the following month. ")


def _persona(taxonomy) -> persona.Persona:
    """A planted preference, including one conditional axis per layer."""
    wants, conditional = {}, {}
    for i, (key, dim) in enumerate(sorted(taxonomy.items())):
        a, b = dim.pole_keys()
        wants[key] = None if i % 7 == 6 else (a if i % 2 == 0 else b)
    if "step_size" in taxonomy:
        wants["step_size"] = "stretches"
        conditional["step_size"] = {"reversibility": {"reversible": "stretches",
                                                      "irreversible": "increments"}}
    if "verification" in taxonomy:
        wants["verification"] = "asserted"
        conditional["verification"] = {"reversibility": {"reversible": "asserted",
                                                         "irreversible": "demonstrated"}}
    return persona.Persona(wants=wants, conditional=conditional,
                           noise=0.05, indifference=0.05, seed=3)


def cmd_dryrun(layer: str, n_sessions: int, pairs: int, out: str | None,
               repeats: int = 40) -> int:
    taxonomy = corpus.load_taxonomy()
    items = {it.id: it for it in corpus.load_items()}
    layer_tax = {k: d for k, d in taxonomy.items() if d.layer == layer}
    pool = [it for it in items.values() if it.layer == layer]
    pairs = min(pairs, len(pool))
    who = _persona(layer_tax)

    sessions = []
    for n in range(1, n_sessions + 1):
        plan = corpus.plan_session(taxonomy, list(items.values()), n, pairs,
                                   seed=100 + n, layer=layer)
        records = persona.label_plan(plan, who, t0=1_000_000.0 + n * 100_000)
        s = labeling.score_session(records, taxonomy)
        print(f"session {n}: {s['n_presentations']} presentations, "
              f"{'accepted' if s['accepted'] else 'REJECTED ' + str(s['checks'])}")
        sessions.append(records)

    prefs_raw = labeling.aggregate_preferences(sessions, taxonomy)
    print("\n-- preferences recovered")
    planted_ok, conditional_ok = 0, 0
    for key, e in prefs_raw["dimensions"].items():
        if key not in layer_tax:
            continue
        want = who.wants.get(key)
        cond = who.conditional.get(key)
        if cond:
            hit = e["result"] == "conditional"
            conditional_ok += hit
            print(f"  {key:<22} {e['result']:<14} planted conditional  "
                  f"{'OK' if hit else 'MISS'}")
        else:
            hit = (e["result"] == want) or (want is None and e["result"] == "indifferent")
            planted_ok += hit
            print(f"  {key:<22} {e['result']:<14} planted {str(want):<14} "
                  f"{'OK' if hit else 'MISS'}")

    dest = Path(out) if out else None
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(prefs_raw, indent=2) + "\n")
        print(f"\nwrote {dest}")

    prefs = {k: reward.Preference(
        dimension=k, result=e["result"],
        default=e.get("default") if e["result"] not in reward.FLAT_RESULTS else None,
        margin=e.get("margin") or 0.0, conditionals=e.get("conditionals") or [])
        for k, e in prefs_raw["dimensions"].items() if k in layer_tax}
    statements = {k: e.get("context_statement") for k, e in prefs_raw["dimensions"].items()}

    text = arms.context_file_text(prefs, layer_tax, statements)
    print(f"\n-- context file (arm B), {len(text.splitlines()) - 1} statements")
    for line in text.splitlines()[1:4]:
        print(f"  {line}")

    print("\n-- three-arm sweep (SIMULATED arms; a harness check, not a result)")
    rng = random.Random(7)
    by_arm: dict[str, dict[int, dict]] = {}
    for arm in arms.arms(text, adapter="dryrun"):
        by_arm[arm.name] = {}
        for fill in arms.FILL_LEVELS:
            judgements = []
            for it in pool * repeats:
                for level_set in ([], ["reversible"], ["irreversible"]):
                    sit = {"reversibility": level_set[0]} if level_set else {}
                    p = persona.simulate_response(
                        arm.name, it.dimension, level_set, who, layer_tax,
                        fill, rng, is_conditional=it.dimension in who.conditional)
                    judgements.append({"dimension": it.dimension, "pole_prob": p,
                                       "situation": sit})
            by_arm[arm.name][fill] = arms.adherence(judgements, prefs, layer_tax)
    summary = arms.sweep_summary(by_arm)
    for name, a in summary["arms"].items():
        pts = "  ".join(f"{k//1000}k:{v:.2f}" for k, v in a["adherence"].items())
        print(f"  {name:<8} {pts}   slope {a['slope_per_10k']:+.4f}/10k")
    gap = summary["context_weights_gap_at_zero"]
    print(f"  weights - context at zero fill: {gap:+.3f}")

    cond_dims = [d for d, v in summary["per_dimension"].items()
                 if v.get("context", {}).get("conditional")]
    conditional_steeper = None
    if cond_dims:
        cs = [summary["per_dimension"][d]["context"]["slope_per_10k"] for d in cond_dims]
        us = [v["context"]["slope_per_10k"] for d, v in summary["per_dimension"].items()
              if d not in cond_dims]
        if us:
            conditional_steeper = sum(cs) / len(cs) < sum(us) / len(us)
            n_min = min(by_arm["context"][0]["per_dimension"][d]["n"]
                        for d in summary["per_dimension"])
            print(f"  context slope, conditional axes {sum(cs)/len(cs):+.4f} vs "
                  f"unconditional {sum(us)/len(us):+.4f} /10k "
                  f"(n>={n_min}/dim/level) {'OK' if conditional_steeper else 'NOT SEEN'}")

    base_flat = abs(summary["arms"]["base"]["slope_per_10k"]) < 0.005
    separates = (summary["arms"]["context"]["slope_per_10k"]
                 < summary["arms"]["weights"]["slope_per_10k"])
    ok = base_flat and separates and (conditional_steeper is not False)
    print(f"\nchain {'OK' if ok else 'BROKEN'}: "
          f"{planted_ok} plain preferences and {conditional_ok} conditionals "
          f"recovered; context degrades faster than weights: {separates}; "
          f"base arm flat (no drift artifact): {base_flat}; "
          f"per-dimension conditional effect visible: {conditional_steeper}")
    return 0 if ok else 2


def cmd_contextfile(path: str) -> int:
    taxonomy = corpus.load_taxonomy()
    prefs = reward.load_preferences(path)
    statements = {k: e.get("context_statement") for k, e in
                  json.loads(Path(path).read_text())["dimensions"].items()}
    print(arms.context_file_text(prefs, taxonomy, statements))
    return 0


def cmd_judgecheck(accuracy: float) -> int:
    taxonomy = corpus.load_taxonomy()
    items = {it.id: it for it in corpus.load_items()}
    judge = persona.oracle_pole_judge(items, taxonomy, accuracy=accuracy, seed=1)
    acc = reward.pole_judge_accuracy(list(items.values()), judge, taxonomy)
    trusted = reward.trusted_dimensions(acc)
    for key, v in acc.items():
        print(f"  {key:<22} n={v['n']:>3} acc {v['accuracy']:.2f} "
              f"{'trusted' if v['trusted'] else 'NOT TRUSTED -> weight 0'}")
    print(f"{len(trusted)}/{len(acc)} axes clear the {reward.JUDGE_ACCURACY_MIN:.0%} bar")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dryrun")
    d.add_argument("--layer", default="agency", choices=("artifact", "agency"))
    d.add_argument("--sessions", type=int, default=4)
    d.add_argument("--pairs", type=int, default=40)
    d.add_argument("--out", default=None)
    d.add_argument("--repeats", type=int, default=40,
                   help="samples per prompt per fill level. Measured: the "
                        "pooled arm comparison is stable well below this, but "
                        "the per-dimension conditional comparison needs ~160 "
                        "samples per dimension per level (40 repeats on a "
                        "2-item axis) -- at ~48 it inverts on 1 seed in 12")
    c = sub.add_parser("contextfile")
    c.add_argument("--preferences", required=True)
    j = sub.add_parser("judgecheck")
    j.add_argument("--accuracy", type=float, default=1.0)
    args = parser.parse_args()
    if args.cmd == "dryrun":
        return cmd_dryrun(args.layer, args.sessions, args.pairs, args.out,
                          args.repeats)
    if args.cmd == "contextfile":
        return cmd_contextfile(args.preferences)
    return cmd_judgecheck(args.accuracy)


if __name__ == "__main__":
    sys.exit(main())
