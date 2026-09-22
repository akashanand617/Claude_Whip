"""
M3 labeling: present a session plan, record labels, join ring events, score.

The presenter replays a plan from `whip.corpus.plan_session` one slot at a
time -- prompt plus one response -- and records one label per slot. The
keyboard is the primary label source; the ring is secondary. That order is
measured, not provisional: on held-out data the gesture model recalls ~58% of
flicks (95% CI 45-69), so four in ten ring labels would simply not arrive, and
a presenter that waited for the ring would stall on nearly half its slots.

Ring events are therefore joined *after* the fact, offline, from the gesture
platform's `data/live/events_*.jsonl`. The join contract, from that platform:

- join on **`wall`** (epoch seconds). `t_s` is the engine's stream clock and is
  not comparable across processes.
- use **`action`**, not the gesture name. `data/app_config.json` maps
  flick->flag and double_flick->approve; snap/wave/clap are unmapped and carry
  `action: null`. Every ambient false positive observed so far was unmapped,
  so filtering on action is what keeps them out of the labels.
- **direction is recorded but never routed on.** It is available and accurate
  (93-96% on a held-out session), and `data/app_config.json` supports
  direction-qualified mapping keys, but M3 deliberately does not use them: the
  label vocabulary has three states, which two gestures plus silence already
  cover, so a direction qualifier would add a second way for a ring label to be
  wrong on a path the keyboard already handles perfectly. It is stored on every
  joined record so the direction *habit* per action is observable -- whether a
  coder flags down and approves up without being asked -- which is what would
  justify routing on it later. M3 cannot score direction accuracy, because the
  labeler is never asked for a direction and there is no ground truth.
- latency is ~1.3 s from gesture end to event, so a slot's acceptance window
  extends RING_ACCEPT_WINDOW_S past the moment the key label was recorded.

A slot with no mapped event inside its window is recorded as `missing`, never
silently skipped: missed slots are the recall number, and they are reported
per session as the ring-vs-key agreement check.

Everything downstream of the label file is pure and deterministic:
`score_session` produces the per-session acceptance report and
`aggregate_preferences` produces `data/calibration/preferences.json`, the
M2/M3 exit artifact that feeds both M4 training and the M6 context arm.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from whip import corpus

# Seconds past the key label during which a ring event still belongs to the
# slot. Measured gesture-end-to-event latency is ~1.3 s; 2.0 s leaves margin
# for a labeler who presses the key before the flick has fully returned.
RING_ACCEPT_WINDOW_S = 2.0

# Only mapped actions are labels. Unmapped gestures (action null) are the
# platform's way of saying "a gesture happened that means nothing here".
MAPPED_ACTIONS = ("flag", "approve")

KEY_LABELS = {"f": "flag", "a": "approve", "": "none", "n": "none"}
SOURCES = ("key", "ring")

# Per-session acceptance thresholds (docs/CALIBRATION.md).
SENTINEL_AGREEMENT_MIN = 0.80
NONE_RATE_MAX = 0.85

# A dimension whose pairs read indifferent more often than this is dropped
# from the context file and trained flat -- a preference never expressed must
# not be baked in.
INDIFFERENT_RATE_MAX = 0.60

# Detecting a conditional preference means showing the preferred pole DIFFERS
# between two levels of a situation factor. That is a claim about an
# interaction, and interactions need more evidence than main effects: each
# level needs its own decided pairs, and each needs to be lopsided on its own.
# At these settings the design detects flips, not gradients -- a preference
# that merely weakens with stakes reads as unconditional, which is the honest
# outcome for this sample size.
MIN_PAIRS_PER_LEVEL = 4
LEVEL_MAJORITY_MIN = 0.75


# --------------------------------------------------------------------------
# records

def make_record(plan: dict, presentation: dict, label: str, source: str,
                wall_shown: float, wall_labeled: float) -> dict:
    if label not in corpus.LABELS:
        raise ValueError(f"unknown label {label!r}")
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    return {
        "session": plan["session"],
        "seed": plan["seed"],
        "slot": presentation["slot"],
        "item": presentation["item"],
        "variant": presentation["variant"],
        "pole": presentation["pole"],
        "dimension": presentation["dimension"],
        "layer": presentation.get("layer", "artifact"),
        "situation": presentation.get("situation", []),
        "sentinel_phase": presentation.get("sentinel_phase"),
        "label": label,
        "source": source,
        "wall_shown": wall_shown,
        "wall_labeled": wall_labeled,
        "ring": None,
    }


def read_jsonl(path: Path) -> list[dict]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def write_jsonl(path: Path, records: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def load_events(paths) -> list[dict]:
    """Events from one or more events_*.jsonl files, sorted by wall time."""
    events = []
    for p in paths:
        events.extend(read_jsonl(p))
    events = [e for e in events if "wall" in e]
    events.sort(key=lambda e: e["wall"])
    return events


# --------------------------------------------------------------------------
# ring join

def join_ring_events(records: list[dict], events: list[dict],
                     window_s: float = RING_ACCEPT_WINDOW_S) -> list[dict]:
    """
    Attach the ring's verdict to each record, by wall time and mapped action.

    Windows are [wall_shown, wall_labeled + window_s]. Adjacent windows can
    overlap, so each event goes to the one containing slot whose key-label
    time is nearest -- the key is pressed at about the moment of the flick,
    and the event follows ~1.3 s later -- and is never counted twice.
    Outcomes per slot:

      ok         exactly one mapped event (or several agreeing) -> ring label
      missing    no mapped event in the window
      ambiguous  mapped events disagree (a flag and an approve)
    """
    mapped = [e for e in events if e.get("action") in MAPPED_ACTIONS]
    ordered = sorted(records, key=lambda r: (r["wall_shown"], r["slot"]))
    assigned: dict[int, list[dict]] = defaultdict(list)
    for e in mapped:
        containing = [(abs(e["wall"] - r["wall_labeled"]), idx)
                      for idx, r in enumerate(ordered)
                      if r["wall_shown"] <= e["wall"] <= r["wall_labeled"] + window_s]
        if containing:
            assigned[min(containing)[1]].append(e)
    out = []
    for idx, r in enumerate(ordered):
        hits = sorted(assigned.get(idx, []), key=lambda e: e["wall"])
        r = dict(r)
        if not hits:
            r["ring"] = {"status": "missing", "label": None}
        else:
            actions = {e["action"] for e in hits}
            first = hits[0]
            if len(actions) == 1:
                r["ring"] = {
                    "status": "ok" if len(hits) == 1 else "multiple",
                    "label": first["action"],
                    "wall": first["wall"],
                    "confidence": first.get("confidence"),
                    "name": first.get("name"),
                    "direction": first.get("direction", "none"),
                }
            else:
                r["ring"] = {"status": "ambiguous", "label": None,
                             "wall": first["wall"],
                             "confidence": first.get("confidence"),
                             "name": first.get("name"),
                             "direction": first.get("direction", "none")}
        out.append(r)
    out.sort(key=lambda r: r["slot"])
    return out


def ring_agreement(records: list[dict]) -> dict:
    """
    Ring-vs-key agreement, broken down so recall and false positives stay
    separate numbers. On slots the key labeled as a gesture: matched /
    mismatched / missed. On slots the key labeled none: silent / spurious.
    """
    gesture = Counter()
    none = Counter()
    for r in records:
        ring = r.get("ring") or {"status": "unjoined", "label": None}
        if r["label"] in MAPPED_ACTIONS:
            if ring["label"] is None:
                gesture["missed" if ring["status"] != "ambiguous"
                        else "ambiguous"] += 1
            elif ring["label"] == r["label"]:
                gesture["matched"] += 1
            else:
                gesture["mismatched"] += 1
        else:
            none["spurious" if ring["label"] is not None else "silent"] += 1
    # Direction is observed, never scored: there is no ground truth for it
    # here. What this shows is whether the coder has a consistent direction
    # habit per action, which is the only thing that would justify routing on
    # direction in a later revision.
    directions: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        ring = r.get("ring") or {}
        if ring.get("label"):
            directions[ring["label"]][ring.get("direction", "none")] += 1

    n_gesture = sum(gesture.values())
    fired = gesture["matched"] + gesture["mismatched"]
    return {
        "direction_habit": {k: dict(v) for k, v in sorted(directions.items())},
        "gesture_slots": n_gesture,
        "matched": gesture["matched"],
        "mismatched": gesture["mismatched"],
        "missed": gesture["missed"],
        "ambiguous": gesture["ambiguous"],
        "recall": (fired / n_gesture) if n_gesture else None,
        "agreement_when_fired": (gesture["matched"] / fired) if fired else None,
        "none_slots": sum(none.values()),
        "silent": none["silent"],
        "spurious": none["spurious"],
    }


# --------------------------------------------------------------------------
# per-session scoring

def pair_preferences(records: list[dict]) -> list[dict]:
    """One entry per item whose two regular showings were both labeled."""
    by_item: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in records:
        if r.get("sentinel_phase") is None:
            by_item[r["item"]][r["variant"]] = r
    out = []
    for item, seen in sorted(by_item.items()):
        if "a" not in seen or "b" not in seen:
            continue
        a, b = seen["a"], seen["b"]
        read = corpus.label_pair(a["label"], b["label"])
        out.append({
            "item": item,
            "dimension": a["dimension"],
            "layer": a.get("layer", "artifact"),
            "situation": a.get("situation", []),
            "a_pole": a["pole"],
            "b_pole": b["pole"],
            "a_label": a["label"],
            "b_label": b["label"],
            "preference": read["preference"],
            "review": read["review"],
            "session": a["session"],
        })
    return out


def score_session(records: list[dict], taxonomy=None) -> dict:
    taxonomy = taxonomy or corpus.load_taxonomy()
    labels = Counter(r["label"] for r in records)
    n = len(records)

    # Sentinels: the same variant shown early and late; disagreement is drift.
    sentinel: dict[str, dict[str, str]] = defaultdict(dict)
    for r in records:
        if r.get("sentinel_phase"):
            sentinel[r["item"]][r["sentinel_phase"]] = r["label"]
    pairs_seen = [v for v in sentinel.values() if "early" in v and "late" in v]
    agree = sum(1 for v in pairs_seen if v["early"] == v["late"])
    sentinel_agreement = (agree / len(pairs_seen)) if pairs_seen else None

    regular = [r for r in records if r.get("sentinel_phase") is None]
    dims = {r["dimension"] for r in regular}
    # A session covers one layer; completeness is judged against that layer's
    # axes, not against every axis in the project.
    layers = {r.get("layer", "artifact") for r in records}
    expected = {k for k, d in taxonomy.items() if d.layer in layers}
    first_variant: dict[str, str] = {}
    for r in sorted(regular, key=lambda r: r["slot"]):
        first_variant.setdefault(r["item"], r["variant"])
    a_first = sum(1 for v in first_variant.values() if v == "a")

    pairs = pair_preferences(records)
    none_rate = (labels["none"] / n) if n else None
    checks = {
        "sentinel_agreement": (sentinel_agreement is None
                               or sentinel_agreement >= SENTINEL_AGREEMENT_MIN),
        "all_dimensions": dims == expected,
        "reaction_coverage": none_rate is not None and none_rate <= NONE_RATE_MAX,
        "first_shown_balance": abs(a_first - (len(first_variant) - a_first)) <= 1,
    }
    return {
        "n_presentations": n,
        "labels": dict(labels),
        "none_rate": none_rate,
        "sentinel_agreement": sentinel_agreement,
        "sentinels_scored": len(pairs_seen),
        "dimensions_present": sorted(dims),
        "layers": sorted(layers),
        "first_shown_a": a_first,
        "first_shown_b": len(first_variant) - a_first,
        "pairs": len(pairs),
        "review": [p["item"] for p in pairs if p["review"]],
        "checks": checks,
        "accepted": all(checks.values()),
        "ring": ring_agreement(records) if any(r.get("ring") for r in records)
                else None,
    }


# --------------------------------------------------------------------------
# cross-session aggregation -> preferences.json

def _level_winner(pairs: list[dict], level: str) -> tuple[str | None, int, float]:
    """The pole preferred among pairs at one situation level, if lopsided."""
    at_level = [p for p in pairs if level in (p.get("situation") or [])]
    votes = Counter()
    for p in at_level:
        if p["preference"] > 0:
            votes[p["a_pole"]] += 1
        elif p["preference"] < 0:
            votes[p["b_pole"]] += 1
    decided = sum(votes.values())
    if decided < MIN_PAIRS_PER_LEVEL:
        return None, decided, 0.0
    pole, n = votes.most_common(1)[0]
    majority = n / decided
    if majority < LEVEL_MAJORITY_MIN:
        return None, decided, majority
    return pole, decided, majority


def detect_conditionals(pairs: list[dict], dim, factors) -> list[dict]:
    """
    Where does this axis's preferred pole change with the situation?

    One entry per conditioner whose two levels disagree. A conditioner whose
    levels agree, or which lacks the evidence to say, produces nothing -- the
    axis is then reported as an ordinary unconditional preference.
    """
    out = []
    for factor_key in dim.conditioners:
        factor = factors.get(factor_key)
        if factor is None:
            continue
        winners = {}
        for level in factor.levels:
            pole, n, majority = _level_winner(pairs, level)
            winners[level] = {"pole": pole, "decided": n, "majority": majority}
        poles = {v["pole"] for v in winners.values() if v["pole"]}
        if len(poles) == 2 and all(v["pole"] for v in winners.values()):
            out.append({
                "factor": factor_key,
                "levels": {lvl: {"pole": v["pole"], "decided": v["decided"],
                                 "majority": round(v["majority"], 3),
                                 "phrase": factor.phrase(lvl)}
                           for lvl, v in winners.items()},
            })
    return out


def _decap(text: str) -> str:
    return text[0].lower() + text[1:]


def compose_context_statement(dim, winner: str | None,
                              conditionals: list[dict]) -> str:
    """
    The sentence the M6 context arm uses.

    Three shapes, and which one appears is itself a finding. An unconditional
    axis gets the winning pole's statement verbatim. An axis with a default
    and an exception gets "<default>. Exception: when <situation>, <other>."
    An axis that flips cleanly has no default at all -- it gets one clause per
    situation. The last two are policies rather than constants, and applying
    them requires recognising the situation at a decision point buried in a
    full context, which is exactly what M6 measures.
    """
    poles = {p.key: p for p in dim.poles}
    if winner is not None:
        base = poles[winner].context_statement
        clauses = [f"when {info['phrase']}, {_decap(poles[info['pole']].context_statement)}"
                   for c in conditionals for info in c["levels"].values()
                   if info["pole"] != winner]
        return base if not clauses else base + " Exception: " + " Also, ".join(clauses)
    clauses = []
    for c in conditionals:
        for info in c["levels"].values():
            clauses.append(f"When {info['phrase']}, "
                           f"{_decap(poles[info['pole']].context_statement)}")
    return " ".join(clauses)


def aggregate_preferences(sessions: list[list[dict]], taxonomy=None,
                          factors=None) -> dict:
    """
    Per dimension: the winning pole, `indifferent`, `contested`, or
    `unmeasured`. A pole wins only if it holds the majority overall AND in
    every session where the dimension had at least two decided pairs -- a
    single sitting measures that day's mood, not a preference.
    """
    taxonomy = taxonomy or corpus.load_taxonomy()
    factors = corpus.load_situation_factors() if factors is None else factors
    votes: dict[str, list[dict]] = defaultdict(list)
    review = []
    for records in sessions:
        for p in pair_preferences(records):
            if p["review"]:
                review.append({"session": p["session"], "item": p["item"]})
                continue
            votes[p["dimension"]].append(p)

    result: dict[str, dict] = {}
    for key, dim in taxonomy.items():
        ps = votes.get(key, [])
        n = len(ps)
        entry = {"n_pairs": n, "sessions": {}}
        if n == 0:
            entry.update(result="unmeasured", margin=None, indifferent_rate=None)
            result[key] = entry
            continue
        pole_votes = Counter()
        per_session: dict[int, Counter] = defaultdict(Counter)
        zeros = 0
        for p in ps:
            if p["preference"] > 0:
                pole = p["a_pole"]
            elif p["preference"] < 0:
                pole = p["b_pole"]
            else:
                zeros += 1
                per_session[p["session"]]["indifferent"] += 1
                continue
            pole_votes[pole] += 1
            per_session[p["session"]][pole] += 1
        entry["sessions"] = {str(s): dict(c) for s, c in sorted(per_session.items())}
        entry["indifferent_rate"] = zeros / n
        decided = sum(pole_votes.values())
        if entry["indifferent_rate"] > INDIFFERENT_RATE_MAX or decided == 0:
            entry.update(result="indifferent", margin=0.0)
            result[key] = entry
            continue
        (winner, w), *rest = pole_votes.most_common()
        loser_votes = rest[0][1] if rest else 0

        # Conditionals are detected before the main effect is judged. A
        # preference that flips cleanly with the situation cancels itself out
        # in aggregate -- four votes each way -- and would otherwise be
        # dismissed as "contested" precisely when it is most informative.
        conditionals = detect_conditionals(ps, dim, factors)
        if conditionals:
            default = None if w == loser_votes else winner
            entry.update(result="conditional", conditional=True,
                         default=default, conditionals=conditionals,
                         margin=(w - loser_votes) / decided,
                         context_statement=compose_context_statement(
                             dim, default, conditionals))
            result[key] = entry
            continue

        if w == loser_votes:
            entry.update(result="contested", margin=0.0)
            result[key] = entry
            continue
        consistent = True
        for c in per_session.values():
            decided_here = {k: v for k, v in c.items() if k != "indifferent"}
            if sum(decided_here.values()) >= 2:
                top = max(decided_here.values())
                if decided_here.get(winner, 0) < top:
                    consistent = False
        margin = (w - loser_votes) / decided
        if not consistent:
            entry.update(result="contested", margin=margin)
        else:
            entry.update(result=winner, margin=margin, conditional=False,
                         conditionals=[], default=winner,
                         context_statement=compose_context_statement(
                             dim, winner, []))
        result[key] = entry

    ordered = sorted(
        (k for k, e in result.items()
         if e["result"] in dim_pole_keys(taxonomy, k) or e["result"] == "conditional"),
        key=lambda k: -abs(result[k]["margin"]))
    return {
        "dimensions": result,
        "review": review,
        "context_file": [result[k]["context_statement"] for k in ordered],
        "n_sessions": len(sessions),
    }


def dim_pole_keys(taxonomy, key: str) -> tuple[str, str]:
    return taxonomy[key].pole_keys()
