"""
M4: the factored reward model, and the M5 datasets built from the same labels.

Reward is a product of two things measured separately, not a scalar head:

    r(prompt, response) = sum_d  w_d * s_d(prompt) * (2 * p_d(response) - 1)

      p_d      P(response exhibits pole A of dimension d), from a pole judge
      s_d(.)   +1 if the coder wants pole A here, -1 for pole B, 0 if the axis
               is indifferent, contested or unmeasured
      w_d      how strongly the preference was expressed

Three reasons it is factored rather than learned whole, each a lesson from M1:

**Credit assignment survives.** A monolithic head trained on ~160 pairs learns a
blend of 23 axes it cannot separate; a wrong reward here is attributable to a
wrong pole call or a wrong weight, and each is inspectable on its own.

**Indifference is structural.** `w_d = 0` is a guarantee, not something a scalar
head has to infer from a handful of `none, none` pairs. What the objective never
sees it cannot learn -- the same lesson as the 2% loud negatives in sampling.py.

**Supervision is free.** Pole judges train and validate on the corpus's own
variant labels: every item states which pole each variant exhibits, which is
~176 labelled responses nobody had to sit a session for. Held out BY ITEM, or
the judge learns the item's prompt instead of the pole.

`s_d` takes the prompt because a preference can be conditional: large autonomous
steps when the work is undoable, small ones when it is not. A fixed sign cannot
express that, which is why the situation judge exists alongside the pole judge.

Nothing here calls a model. Judges are injected, so the arithmetic is testable
today and the backend is swappable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from whip import corpus

# A judge below this on the corpus's own variants is not trusted to score that
# axis; the axis reverts to weight 0 rather than contributing noise.
JUDGE_ACCURACY_MIN = 0.90

# Results that carry no preference and therefore no reward signal.
FLAT_RESULTS = ("indifferent", "contested", "unmeasured")


class PoleJudge(Protocol):
    """P(response exhibits pole A of `dimension`), given the prompt."""
    def __call__(self, dimension: str, prompt: str, response: str) -> float: ...


class SituationJudge(Protocol):
    """Which level of each situation factor this prompt sits at."""
    def __call__(self, prompt: str) -> dict[str, str]: ...


# --------------------------------------------------------------------------
# rubrics -- the judge's entire instruction, generated from the taxonomy so the
# thing being scored and the thing written into the context file cannot drift

def pole_rubric(dim: corpus.Dimension) -> str:
    a, b = dim.poles
    return (f"{dim.question}\n"
            f"A ({a.key}): {a.summary}\n"
            f"B ({b.key}): {b.summary}\n"
            f"Answer with the probability, 0 to 1, that the response exhibits "
            f"A rather than B. Judge only this property. If the response does "
            f"not exercise it at all, answer 0.5.")


def situation_rubric(factor: corpus.SituationFactor) -> str:
    lines = [f"{factor.question}"]
    for key, body in factor.levels.items():
        lines.append(f"{key}: {body['phrase']} (e.g. {body['examples']})")
    lines.append("Answer with one level name. Judge the task, not the response.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# preferences.json -> direction and weight

@dataclass(frozen=True)
class Preference:
    dimension: str
    result: str
    default: str | None
    margin: float
    conditionals: list[dict] = field(default_factory=list)

    @property
    def flat(self) -> bool:
        return self.result in FLAT_RESULTS


def load_preferences(path: str | Path) -> dict[str, Preference]:
    raw = json.loads(Path(path).read_text())
    out = {}
    for key, e in raw["dimensions"].items():
        out[key] = Preference(
            dimension=key, result=e["result"],
            default=e.get("default") if e["result"] not in FLAT_RESULTS else None,
            margin=e.get("margin") or 0.0,
            conditionals=e.get("conditionals") or [])
    return out


def wanted_pole(pref: Preference, situation: dict[str, str]) -> tuple[str | None, float]:
    """
    The pole the coder wants here, and how strongly -- the (s_d, w_d) pair
    before the sign is resolved against pole order.

    A conditional preference is read off the situation. When the situation does
    not pin the conditioning factor, it falls back to the unconditional default,
    which for a cleanly flipped axis is None: the honest answer is that without
    knowing the situation there is no preference to apply.
    """
    if pref.flat:
        return None, 0.0
    for cond in pref.conditionals:
        level = situation.get(cond["factor"])
        if level and level in cond["levels"]:
            info = cond["levels"][level]
            return info["pole"], float(info.get("majority") or 1.0)
    if pref.result == "conditional":
        return pref.default, abs(pref.margin)
    return pref.result, abs(pref.margin)


def direction(pref: Preference, situation: dict[str, str],
              pole_keys: tuple[str, str]) -> tuple[float, float]:
    """(s_d, w_d). s_d is +1 when pole A is wanted, -1 for pole B, 0 for flat."""
    pole, weight = wanted_pole(pref, situation)
    if pole is None or weight == 0.0:
        return 0.0, 0.0
    return (1.0 if pole == pole_keys[0] else -1.0), weight


# --------------------------------------------------------------------------
# the reward

def reward(pole_probs: dict[str, float], situation: dict[str, str],
           preferences: dict[str, Preference], taxonomy: dict[str, corpus.Dimension],
           trusted: set[str] | None = None) -> dict:
    """
    Score one response. Returns the total and the per-dimension breakdown,
    because an unexplainable reward is the thing this design exists to avoid.
    """
    terms = []
    total = 0.0
    for dim_key, p in pole_probs.items():
        dim = taxonomy.get(dim_key)
        pref = preferences.get(dim_key)
        if dim is None or pref is None:
            continue
        if trusted is not None and dim_key not in trusted:
            continue
        s, w = direction(pref, situation, dim.pole_keys())
        contribution = w * s * (2.0 * p - 1.0)
        total += contribution
        if w:
            terms.append({"dimension": dim_key, "p_a": p, "s": s, "w": w,
                          "contribution": contribution})
    terms.sort(key=lambda t: -abs(t["contribution"]))
    return {"reward": total, "terms": terms}


def score_responses(prompts_responses, situations, pole_probs_per_item,
                    preferences, taxonomy, trusted=None) -> list[dict]:
    return [reward(probs, sit, preferences, taxonomy, trusted)
            for (_, _), sit, probs in zip(prompts_responses, situations,
                                          pole_probs_per_item)]


# --------------------------------------------------------------------------
# judge validation against the corpus's own variant labels

def pole_judge_accuracy(items, judge, taxonomy) -> dict[str, dict]:
    """
    Fraction of variants the judge assigns to the correct pole, per axis.

    Every item states which pole each variant exhibits, so the corpus validates
    its own judges for free -- ~176 labelled responses nobody sat a session
    for. Callers must hold out BY ITEM: both variants of an item share a
    prompt, so splitting between them tests memorisation of the prompt rather
    than recognition of the pole.
    """
    hits: dict[str, list[bool]] = {}
    for it in items:
        dim = taxonomy.get(it.dimension)
        if dim is None:
            continue
        first_pole = dim.pole_keys()[0]
        for variant in ("a", "b"):
            v = it.variant(variant)
            p = judge(it.dimension, it.task, v.text)
            hits.setdefault(it.dimension, []).append(
                (p >= 0.5) == (v.pole == first_pole))
    return {k: {"n": len(v), "accuracy": sum(v) / len(v),
                "trusted": sum(v) / len(v) >= JUDGE_ACCURACY_MIN}
            for k, v in sorted(hits.items())}


def trusted_dimensions(accuracies: dict[str, dict]) -> set[str]:
    return {k for k, v in accuracies.items() if v["trusted"]}


# --------------------------------------------------------------------------
# validation: does the reward order a held-out item the way the coder did

def orders_pair_correctly(item: corpus.Item, pole_probs_a: dict[str, float],
                          pole_probs_b: dict[str, float], situation,
                          preferences, taxonomy) -> bool | None:
    pref = preferences.get(item.dimension)
    if pref is None or pref.flat:
        return None
    ra = reward(pole_probs_a, situation, preferences, taxonomy)["reward"]
    rb = reward(pole_probs_b, situation, preferences, taxonomy)["reward"]
    wanted, _ = wanted_pole(pref, situation)
    if wanted is None or ra == rb:
        return None
    return (ra > rb) == (item.a.pole == wanted)


def pairwise_accuracy(judged_pairs) -> dict:
    """judged_pairs: iterable of (reward_chosen, reward_rejected)."""
    hits = [c > r for c, r in judged_pairs]
    return {"n": len(hits),
            "accuracy": (sum(hits) / len(hits)) if hits else float("nan"),
            "hits": hits}


# --------------------------------------------------------------------------
# M5 datasets, built from the same labels

def dpo_examples(pairs: list[dict], items: dict[str, corpus.Item]) -> list[dict]:
    """
    Chosen/rejected from the pair preference sign. Indifferent pairs are
    dropped -- DPO has no way to express "either is fine" and training on a
    coin flip teaches noise. |preference| = 2 (approve against flag) carries
    twice the weight of a one-sided read.
    """
    out = []
    for p in pairs:
        if p["preference"] == 0 or p.get("review"):
            continue
        it = items.get(p["item"])
        if it is None:
            continue
        chosen, rejected = ("a", "b") if p["preference"] > 0 else ("b", "a")
        out.append({"prompt": it.task, "context": it.context,
                    "chosen": it.variant(chosen).text,
                    "rejected": it.variant(rejected).text,
                    "weight": abs(p["preference"]) / 2.0,
                    "item": p["item"], "dimension": p["dimension"],
                    "situation": p.get("situation", [])})
    return out


def kto_examples(records: list[dict], items: dict[str, corpus.Item]) -> list[dict]:
    """
    One example per labelled presentation: approve is desirable, flag is not,
    none is dropped. Uses the ~2x larger single-presentation set that DPO
    cannot touch, so it is the ablation that says whether the paired design was
    load-bearing for *training* -- it stays load-bearing for measurement either
    way.
    """
    out = []
    for r in records:
        if r["label"] == "none":
            continue
        it = items.get(r["item"])
        if it is None:
            continue
        out.append({"prompt": it.task, "context": it.context,
                    "completion": it.variant(r["variant"]).text,
                    "desirable": r["label"] == "approve",
                    "item": r["item"], "dimension": r["dimension"],
                    "situation": r.get("situation", [])})
    return out


def split_by_item(examples: list[dict], holdout_fraction: float = 0.25,
                  seed: int = 0) -> tuple[list[dict], list[dict]]:
    """
    Both variants of an item, and every showing of each, stay on one side.
    Splitting between them leaks the prompt -- the same failure as splitting
    overlapping windows in M1, where a random split reported ~98% and meant
    nothing.
    """
    import random
    ids = sorted({e["item"] for e in examples})
    rng = random.Random(seed)
    rng.shuffle(ids)
    n_hold = max(1, int(len(ids) * holdout_fraction)) if ids else 0
    held = set(ids[:n_hold])
    return ([e for e in examples if e["item"] not in held],
            [e for e in examples if e["item"] in held])
