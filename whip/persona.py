"""
Synthetic labelers and arm simulation, so M4-M6 can be exercised before a
single real session exists.

This is a test fixture, not a model of anyone -- exactly as `probe/simulate.py`
fabricates captures so the M0 pipeline could run without a ring. Its whole job
is to answer "does the chain wire together, and does the harness detect the
effect it claims to detect", which is a question about the code, never about
the coder. Nothing produced here may be reported as a finding.

Building the eval harness first, against fixtures, is deliberate: a flaw in the
M6 design found *after* four labeling sessions and an adapter is the expensive
failure. Real labels replace `Persona` and real generations replace
`simulate_response`; nothing else in the chain changes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from whip import corpus, labeling


@dataclass
class Persona:
    """
    A synthetic coder. `wants` maps dimension -> pole, or None for genuine
    indifference. `conditional` maps dimension -> factor -> level -> pole and
    overrides `wants` when the item's situation matches, which is how a
    conditional preference is planted so the aggregator can be asked to find it.
    """
    wants: dict[str, str | None]
    conditional: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    noise: float = 0.0          # chance of answering against preference
    indifference: float = 0.0   # chance of shrugging on a decided axis
    seed: int = 0

    def __post_init__(self):
        self._rng = random.Random(self.seed)

    def preferred_pole(self, dimension: str, situation) -> str | None:
        for factor, levels in self.conditional.get(dimension, {}).items():
            for level in (situation or []):
                if level in levels:
                    return levels[level]
        return self.wants.get(dimension)

    def label(self, presentation: dict) -> str:
        liked = self.preferred_pole(presentation["dimension"],
                                    presentation.get("situation"))
        if liked is None:
            return "none"
        if self._rng.random() < self.indifference:
            return "none"
        agrees = presentation["pole"] == liked
        if self._rng.random() < self.noise:
            agrees = not agrees
        return "approve" if agrees else "flag"


def label_plan(plan: dict, persona: Persona, t0: float = 1_000_000.0,
               step: float = 30.0) -> list[dict]:
    """One label record per presentation, shaped exactly as probe.label writes."""
    records = []
    for p in plan["presentations"]:
        shown = t0 + p["slot"] * step
        records.append(labeling.make_record(
            plan, p, persona.label(p), "key", shown, shown + step * 0.6))
    return records


# --------------------------------------------------------------------------
# arm simulation -- a fixture for the M6 harness, never a result

def simulate_response(arm_name: str, dimension: str, situation,
                      persona: Persona, taxonomy, fill_tokens: int,
                      rng: random.Random, is_conditional: bool = False,
                      base_rate: float = 0.5,
                      carried: float = 0.95,
                      context_halflife: int = 32_000,
                      weights_decay: float = 0.0,
                      conditional_penalty: float = 0.5) -> float:
    """
    A stand-in for "generate, then judge the generation", returning P(pole A).

    The shape encodes the hypothesis under test so the harness can be checked
    for the power to see it: the base arm ignores the preference, the context
    arm follows it with a probability that decays as fill pushes the preference
    away from the generation point, and the weights arm does not decay.
    `conditional_penalty` shortens the context arm's half-life on conditional
    axes, because a policy has to be recognised *and* applied at the decision
    point where a style rule only has to be applied -- layer 2's sharpest
    prediction. Planting it is what lets the per-dimension breakdown be checked
    for the power to see it.

    Finding any of this here proves only that the metric can see an effect of
    this shape. It is not evidence that the effect is real.
    """
    dim = taxonomy[dimension]
    first = dim.pole_keys()[0]
    wanted = persona.preferred_pole(dimension, situation)
    if wanted is None:
        p_follow = base_rate
    elif arm_name == "base":
        p_follow = base_rate
    elif arm_name == "context":
        halflife = context_halflife
        if is_conditional:
            halflife *= conditional_penalty
        decay = 0.5 ** (fill_tokens / halflife) if halflife else 1.0
        p_follow = base_rate + (carried - base_rate) * decay
    else:
        decay = max(0.0, 1.0 - weights_decay * fill_tokens / 10_000.0)
        p_follow = base_rate + (carried - base_rate) * decay
    follows = rng.random() < p_follow
    exhibited = wanted if (wanted and follows) else (
        dim.pole_keys()[1] if wanted == first else first)
    if wanted is None:
        exhibited = first if rng.random() < 0.5 else dim.pole_keys()[1]
    return 0.9 if exhibited == first else 0.1


def oracle_pole_judge(items: dict[str, corpus.Item], taxonomy,
                      accuracy: float = 1.0, seed: int = 0):
    """
    A pole judge that reads the answer off the corpus, wrong `1 - accuracy` of
    the time. Stands in for the LLM judge so `pole_judge_accuracy` and the
    trust gate can be exercised without a model.
    """
    rng = random.Random(seed)
    by_text = {}
    for it in items.values():
        for v in ("a", "b"):
            by_text[(it.dimension, it.variant(v).text)] = it.variant(v).pole

    def judge(dimension: str, prompt: str, response: str) -> float:
        pole = by_text.get((dimension, response))
        if pole is None:
            return 0.5
        first = taxonomy[dimension].pole_keys()[0]
        correct = rng.random() < accuracy
        is_first = (pole == first) if correct else (pole != first)
        return 0.9 if is_first else 0.1

    return judge
