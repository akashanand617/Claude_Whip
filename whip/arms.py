"""
M6: three arms, a context-fill sweep, and adherence.

The research question, as a measurement. Three arms over one base model:

    A base      no preferences at all
    B context   the preferences file in the system prompt
    C weights   the M5 adapter, no preferences file

swept across how full the context is. Two numbers answer the question: the gap
between B and C at zero fill, and the two slopes as fill grows.

**The context arm is generated mechanically** from `preferences.json`, never
hand-tuned. A prompt someone polished would measure prompt engineering, and the
arms would no longer differ only in where the preference lives.

**The filler must be style-neutral with respect to the axes.** Code exhibiting a
pole primes the model toward that pole and contaminates the comparison -- prose
and tables, not source. The preference block sits at the top so fill pushes it
away from the generation point, which is the realistic failure mode.

Layer 2 sharpens the prediction. "Be terse" is a local constraint on every
output; a conditional policy has to fire at a decision point buried in a full
context, after the model recognises which situation it is in. So the context arm
should degrade **fastest on conditional axes and slowest on unconditional ones**
-- a per-dimension prediction that a pooled adherence number would hide.
"""

from __future__ import annotations

from dataclasses import dataclass

from whip import corpus, reward
from whip.evaluate import bootstrap_recall_ci

# Fill levels in approximate tokens. The largest usable level depends on the
# base model's window and is appended by the caller.
FILL_LEVELS = (0, 8_000, 32_000, 64_000)

# No tokenizer is a dependency here, so fill is sized by characters at this
# ratio. The real harness should re-measure with the base model's own
# tokenizer; an approximate axis is fine for a sweep but must not be reported
# as an exact token count.
CHARS_PER_TOKEN = 4

FILLER_RULE = (
    "Filler must be prose or tabular data, never source code, and must not "
    "exhibit any pole of any axis: no opinions about testing, comments, "
    "abstraction or autonomy. The same filler is used for every arm."
)

CONTEXT_HEADER = "Preferences for how to work on this codebase:"


def context_file_text(preferences: dict[str, reward.Preference],
                      taxonomy: dict[str, corpus.Dimension],
                      statements: dict[str, str]) -> str:
    """
    Arm B's system prompt, ordered by how strongly each preference was
    expressed. `statements` is `preferences.json`'s per-dimension
    `context_statement`, already composed into a policy for conditional axes.
    """
    lines = [CONTEXT_HEADER]
    ranked = sorted((k for k, p in preferences.items()
                     if not p.flat and statements.get(k)),
                    key=lambda k: -abs(preferences[k].margin))
    for i, key in enumerate(ranked, 1):
        lines.append(f"{i}. {statements[key]}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Arm:
    name: str
    system_prompt: str = ""
    adapter: str | None = None


def arms(context_text: str, adapter: str | None) -> list[Arm]:
    return [Arm("base"), Arm("context", system_prompt=context_text),
            Arm("weights", adapter=adapter)]


def assemble(arm: Arm, task: str, filler: str, fill_tokens: int) -> str:
    """
    System prompt, then filler, then the task. Filler is repeated or truncated
    to the requested size; a caller with no filler at a nonzero level is asking
    for a level it cannot actually produce, which is an error, not a silent 0.
    """
    chars = fill_tokens * CHARS_PER_TOKEN
    if chars and not filler:
        raise ValueError(f"fill level {fill_tokens} requested with no filler")
    body = ""
    if chars:
        body = (filler * (chars // len(filler) + 1))[:chars]
    parts = [p for p in (arm.system_prompt, body, task) if p]
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# adherence

def adheres(dimension: str, pole_prob: float, situation: dict[str, str],
            preferences, taxonomy) -> bool | None:
    """
    Did this response land on the pole the coder wants here? None when the axis
    carries no preference, or when a conditional axis's situation is unknown --
    those are excluded rather than scored as failures.
    """
    pref = preferences.get(dimension)
    dim = taxonomy.get(dimension)
    if pref is None or dim is None or pref.flat:
        return None
    wanted, weight = reward.wanted_pole(pref, situation)
    if wanted is None or weight == 0.0:
        return None
    exhibited = dim.pole_keys()[0] if pole_prob >= 0.5 else dim.pole_keys()[1]
    return exhibited == wanted


def adherence(judgements: list[dict], preferences, taxonomy,
              seed: int = 0) -> dict:
    """
    judgements: [{"dimension", "pole_prob", "situation"}]. Reported per
    dimension and pooled, each with a bootstrap interval -- the sampling
    variance, which is the one this project has been caught reporting without
    before.
    """
    per_dim: dict[str, list[bool]] = {}
    for j in judgements:
        hit = adheres(j["dimension"], j["pole_prob"], j.get("situation", {}),
                      preferences, taxonomy)
        if hit is not None:
            per_dim.setdefault(j["dimension"], []).append(hit)
    out = {}
    for key, hits in sorted(per_dim.items()):
        lo, hi = bootstrap_recall_ci(hits, seed=seed)
        out[key] = {"n": len(hits), "adherence": sum(hits) / len(hits),
                    "ci": (lo, hi),
                    "conditional": preferences[key].result == "conditional"}
    pooled = [h for hits in per_dim.values() for h in hits]
    lo, hi = bootstrap_recall_ci(pooled, seed=seed)
    return {"per_dimension": out,
            "pooled": {"n": len(pooled),
                       "adherence": (sum(pooled) / len(pooled)) if pooled else float("nan"),
                       "ci": (lo, hi)}}


def slope(levels: list[int], values: list[float]) -> float:
    """
    Adherence points per 10k tokens of fill. Negative means degrading. Reported
    as a slope rather than an endpoint difference so a single noisy level
    cannot decide the comparison.
    """
    import numpy as np
    if len(levels) < 2:
        return float("nan")
    m = np.polyfit(np.asarray(levels, dtype=float) / 10_000.0,
                   np.asarray(values, dtype=float), 1)[0]
    return float(m)


def sweep_summary(by_arm_level: dict[str, dict[int, dict]]) -> dict:
    """
    by_arm_level[arm][fill] = an `adherence` result. Produces the two numbers
    the research question reduces to, plus the per-dimension slopes that would
    show "weights hold for style axes, context for behavioural ones" -- a
    plausible honest result that pooling hides.
    """
    levels = sorted({lvl for a in by_arm_level.values() for lvl in a})
    out = {"levels": levels, "arms": {}, "per_dimension": {}}
    for arm, by_level in by_arm_level.items():
        vals = [by_level[l]["pooled"]["adherence"] for l in levels if l in by_level]
        got = [l for l in levels if l in by_level]
        out["arms"][arm] = {
            "adherence": dict(zip(got, vals)),
            "slope_per_10k": slope(got, vals),
            "at_zero": by_level.get(0, {}).get("pooled", {}).get("adherence"),
        }
    dims = {d for a in by_arm_level.values() for l in a.values()
            for d in l["per_dimension"]}
    for d in sorted(dims):
        out["per_dimension"][d] = {}
        for arm, by_level in by_arm_level.items():
            got = [l for l in levels if l in by_level and d in by_level[l]["per_dimension"]]
            vals = [by_level[l]["per_dimension"][d]["adherence"] for l in got]
            out["per_dimension"][d][arm] = {
                "slope_per_10k": slope(got, vals),
                "conditional": any(by_level[l]["per_dimension"][d]["conditional"]
                                   for l in got),
            }
    b = out["arms"].get("context", {}).get("at_zero")
    c = out["arms"].get("weights", {}).get("at_zero")
    out["context_weights_gap_at_zero"] = (
        None if b is None or c is None else c - b)
    return out
