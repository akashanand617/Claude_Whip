"""
M3 labeling session: present, record, join the ring, score, aggregate.

    python -m probe.label run --plan data/sessions/plan_s1.json
    python -m probe.label join --labels data/calibration/labels_s1.jsonl \
        --events data/live/events_*.jsonl
    python -m probe.label score --labels data/calibration/labels_s1.jsonl
    python -m probe.label aggregate --labels data/calibration/labels_s*.jsonl \
        --out data/calibration/preferences.json

`run` shows one slot at a time -- task, context, response -- and never the
dimension or pole: a labeler who can see the axis starts answering the policy
question instead of reacting (docs/CALIBRATION.md, "dimension blocking").
Keys: f = flag, a = approve, Enter = none, q = stop (resume later with the
same command; the file is appended per slot, so a crash loses nothing).

The keyboard is the primary label source. The ring is joined afterwards from
the gesture platform's event log by wall time on mapped actions only; see
whip/labeling.py for the contract and why the order is this way round.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

from whip import corpus, labeling

CLEAR = "\033[2J\033[H"


def _labels_path(plan: dict, out: str | None) -> Path:
    if out:
        return Path(out)
    return Path("data/calibration") / f"labels_s{plan['session']}.jsonl"


def cmd_run(plan_path: str, out: str | None, no_clear: bool) -> int:
    plan = json.loads(Path(plan_path).read_text())
    items = {it.id: it for it in corpus.load_items()}
    path = _labels_path(plan, out)
    done = {r["slot"] for r in labeling.read_jsonl(path)} if path.exists() else set()
    presentations = [p for p in plan["presentations"] if p["slot"] not in done]
    if not presentations:
        print(f"session {plan['session']} already complete: {path}")
        return 0
    if done:
        print(f"resuming session {plan['session']} at slot {presentations[0]['slot']} "
              f"({len(done)} already labeled)")
    path.parent.mkdir(parents=True, exist_ok=True)
    total = len(plan["presentations"])
    with open(path, "a") as f:
        for p in presentations:
            it = items[p["item"]]
            if not no_clear:
                print(CLEAR, end="")
            print(f"slot {p['slot'] + 1} / {total}\n")
            print("TASK\n" + it.task + "\n")
            if it.context:
                print("CONTEXT\n" + it.context + "\n")
            print("RESPONSE\n" + it.variant(p["variant"]).text + "\n")
            wall_shown = time.time()
            while True:
                try:
                    key = input("[f]lag  [a]pprove  [Enter] none  [q]uit > ").strip().lower()
                except EOFError:
                    key = "q"
                if key == "q":
                    print(f"\nstopped at slot {p['slot']}; rerun to resume")
                    return 0
                if key in labeling.KEY_LABELS:
                    break
                print("  f, a, Enter, or q")
            rec = labeling.make_record(plan, p, labeling.KEY_LABELS[key], "key",
                                       wall_shown, time.time())
            f.write(json.dumps(rec) + "\n")
            f.flush()
    print(f"\nsession {plan['session']} complete: {path}")
    return 0


def cmd_join(labels: str, events: list[str], window: float, out: str | None) -> int:
    records = labeling.read_jsonl(labels)
    paths = [p for pattern in events for p in sorted(glob.glob(pattern))]
    if not paths:
        print("no event files matched")
        return 2
    evs = labeling.load_events(paths)
    joined = labeling.join_ring_events(records, evs, window)
    dest = Path(out) if out else Path(labels)
    labeling.write_jsonl(dest, joined)
    print(f"joined {len(evs)} events from {len(paths)} file(s) -> {dest}")
    _print_ring(labeling.ring_agreement(joined))
    return 0


def _print_ring(r: dict) -> None:
    rec = "n/a" if r["recall"] is None else f"{r['recall']:.0%}"
    agr = "n/a" if r["agreement_when_fired"] is None else f"{r['agreement_when_fired']:.0%}"
    print(f"ring vs key -- gesture slots {r['gesture_slots']}: matched {r['matched']}, "
          f"mismatched {r['mismatched']}, missed {r['missed']}, ambiguous {r['ambiguous']} "
          f"(recall {rec}, agreement when fired {agr})")
    print(f"               none slots {r['none_slots']}: silent {r['silent']}, "
          f"spurious {r['spurious']}")
    for action, dirs in (r.get("direction_habit") or {}).items():
        spread = ", ".join(f"{d} {n}" for d, n in sorted(dirs.items(),
                                                         key=lambda kv: -kv[1]))
        print(f"               direction habit, {action}: {spread} "
              f"(observed, not scored)")


def cmd_score(labels: str) -> int:
    records = labeling.read_jsonl(labels)
    s = labeling.score_session(records)
    print(f"{s['n_presentations']} presentations ({'/'.join(s['layers'])} layer), "
          f"labels {s['labels']}, none rate {s['none_rate']:.0%}")
    sa = "n/a" if s["sentinel_agreement"] is None else f"{s['sentinel_agreement']:.0%}"
    print(f"sentinel agreement {sa} over {s['sentinels_scored']}; "
          f"dimensions {len(s['dimensions_present'])}/12; "
          f"first-shown a/b {s['first_shown_a']}/{s['first_shown_b']}; "
          f"pairs {s['pairs']}; review {s['review'] or 'none'}")
    for name, ok in s["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    if s["ring"]:
        _print_ring(s["ring"])
    print("ACCEPTED" if s["accepted"] else "REJECTED")
    return 0 if s["accepted"] else 2


def cmd_aggregate(labels: list[str], out: str) -> int:
    paths = [p for pattern in labels for p in sorted(glob.glob(pattern))]
    sessions = [labeling.read_jsonl(p) for p in paths]
    prefs = labeling.aggregate_preferences(sessions)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(prefs, indent=2) + "\n")
    print(f"{len(sessions)} session(s) -> {out}")
    for key, e in prefs["dimensions"].items():
        m = "" if e["margin"] is None else f" margin {e['margin']:+.2f}"
        flag = "  CONDITIONAL" if e.get("conditional") else ""
        print(f"  {key:<22} {e['result']:<14} n={e['n_pairs']}{m}{flag}")
        for c in e.get("conditionals", []):
            for lvl, info in c["levels"].items():
                print(f"      {c['factor']}={lvl:<16} -> {info['pole']} "
                      f"({info['decided']} pairs)")
    print(f"context file: {len(prefs['context_file'])} statement(s); "
          f"review: {len(prefs['review'])} pair(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--plan", required=True)
    run.add_argument("--out", default=None)
    run.add_argument("--no-clear", action="store_true")
    join = sub.add_parser("join")
    join.add_argument("--labels", required=True)
    join.add_argument("--events", nargs="+", required=True)
    join.add_argument("--window", type=float, default=labeling.RING_ACCEPT_WINDOW_S)
    join.add_argument("--out", default=None)
    score = sub.add_parser("score")
    score.add_argument("--labels", required=True)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--labels", nargs="+", required=True)
    agg.add_argument("--out", default="data/calibration/preferences.json")
    args = parser.parse_args()
    if args.cmd == "run":
        return cmd_run(args.plan, args.out, args.no_clear)
    if args.cmd == "join":
        return cmd_join(args.labels, args.events, args.window, args.out)
    if args.cmd == "score":
        return cmd_score(args.labels)
    return cmd_aggregate(args.labels, args.out)


if __name__ == "__main__":
    sys.exit(main())
