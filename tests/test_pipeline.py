"""
M4-M6: the factored reward, the M5 dataset builders, and the M6 arms.

All of it is pure -- judges and generations are injected -- so the whole chain
is testable before a model, a GPU or a single real label exists. That is the
point: a flaw in the M6 design found after four labeling sessions and an
adapter is the expensive failure.
"""

import pytest

from whip import arms, corpus, labeling, persona, reward


@pytest.fixture(scope="module")
def taxonomy():
    return corpus.load_taxonomy()


@pytest.fixture(scope="module")
def items():
    return corpus.load_items()


def _pref(result, default=None, margin=0.8, conditionals=()):
    return reward.Preference("step_size", result, default, margin, list(conditionals))


COND = [{"factor": "reversibility",
         "levels": {"reversible": {"pole": "stretches", "decided": 5, "majority": 0.8},
                    "irreversible": {"pole": "increments", "decided": 5, "majority": 1.0}}}]


# --------------------------------------------------------------------------
# direction and weight

def test_unconditional_direction(taxonomy):
    keys = taxonomy["step_size"].pole_keys()          # (increments, stretches)
    s, w = reward.direction(_pref("increments"), {}, keys)
    assert (s, w) == (1.0, 0.8)
    s, w = reward.direction(_pref("stretches"), {}, keys)
    assert (s, w) == (-1.0, 0.8)


def test_flat_results_carry_no_signal(taxonomy):
    keys = taxonomy["step_size"].pole_keys()
    for result in reward.FLAT_RESULTS:
        assert reward.direction(_pref(result), {}, keys) == (0.0, 0.0)


def test_conditional_direction_follows_the_situation(taxonomy):
    keys = taxonomy["step_size"].pole_keys()
    pref = _pref("conditional", default=None, margin=0.0, conditionals=COND)
    s_rev, w_rev = reward.direction(pref, {"reversibility": "reversible"}, keys)
    s_irr, w_irr = reward.direction(pref, {"reversibility": "irreversible"}, keys)
    assert s_rev == -1.0 and s_irr == 1.0       # stretches vs increments
    assert w_rev == 0.8 and w_irr == 1.0        # the level's own majority
    # a clean flip with the situation unknown has no preference to apply, and
    # must not silently fall back to one
    assert reward.direction(pref, {}, keys) == (0.0, 0.0)


def test_reward_rewards_the_wanted_pole(taxonomy):
    prefs = {"step_size": _pref("stretches")}
    tax = {"step_size": taxonomy["step_size"]}
    exhibits_stretches = reward.reward({"step_size": 0.05}, {}, prefs, tax)
    exhibits_increments = reward.reward({"step_size": 0.95}, {}, prefs, tax)
    assert exhibits_stretches["reward"] > 0 > exhibits_increments["reward"]
    assert exhibits_stretches["terms"][0]["dimension"] == "step_size"


def test_reward_is_explainable(taxonomy):
    prefs = {k: _pref("increments") if k == "step_size" else
             reward.Preference(k, "indifferent", None, 0.0)
             for k in ("step_size", "narration")}
    tax = {k: taxonomy[k] for k in ("step_size", "narration")}
    out = reward.reward({"step_size": 0.9, "narration": 0.9}, {}, prefs, tax)
    assert [t["dimension"] for t in out["terms"]] == ["step_size"]
    assert out["reward"] == pytest.approx(0.8 * (2 * 0.9 - 1))


def test_untrusted_dimension_is_excluded(taxonomy):
    prefs = {"step_size": _pref("increments")}
    tax = {"step_size": taxonomy["step_size"]}
    out = reward.reward({"step_size": 0.9}, {}, prefs, tax, trusted=set())
    assert out["reward"] == 0.0 and out["terms"] == []


# --------------------------------------------------------------------------
# judges validate against the corpus's own variant labels

def test_perfect_judge_scores_every_axis(taxonomy, items):
    by_id = {it.id: it for it in items}
    judge = persona.oracle_pole_judge(by_id, taxonomy, accuracy=1.0)
    acc = reward.pole_judge_accuracy(items, judge, taxonomy)
    assert len(acc) == 23
    assert all(v["accuracy"] == 1.0 and v["trusted"] for v in acc.values())
    assert len(reward.trusted_dimensions(acc)) == 23


def test_a_weak_judge_loses_trust(taxonomy, items):
    by_id = {it.id: it for it in items}
    judge = persona.oracle_pole_judge(by_id, taxonomy, accuracy=0.5, seed=2)
    acc = reward.pole_judge_accuracy(items, judge, taxonomy)
    assert len(reward.trusted_dimensions(acc)) < 5


# --------------------------------------------------------------------------
# M5 datasets

def test_dpo_drops_indifferent_and_weights_strong_pairs(items):
    by_id = {it.id: it for it in items}
    it = items[0]
    pairs = [
        {"item": it.id, "dimension": it.dimension, "preference": 2,
         "a_pole": it.a.pole, "b_pole": it.b.pole, "situation": []},
        {"item": it.id, "dimension": it.dimension, "preference": -1,
         "a_pole": it.a.pole, "b_pole": it.b.pole, "situation": []},
        {"item": it.id, "dimension": it.dimension, "preference": 0,
         "a_pole": it.a.pole, "b_pole": it.b.pole, "situation": []},
    ]
    out = reward.dpo_examples(pairs, by_id)
    assert len(out) == 2                       # the indifferent pair is dropped
    assert out[0]["chosen"] == it.a.text and out[0]["weight"] == 1.0
    assert out[1]["chosen"] == it.b.text and out[1]["weight"] == 0.5


def test_kto_uses_singles_that_dpo_cannot(taxonomy, items):
    by_id = {it.id: it for it in items}
    plan = corpus.plan_session(taxonomy, items, 1, 12, 7, "artifact")
    who = persona.Persona(wants={k: d.pole_keys()[0] for k, d in taxonomy.items()})
    records = persona.label_plan(plan, who)
    out = reward.kto_examples(records, by_id)
    assert out and all("desirable" in e for e in out)
    assert len(out) == sum(1 for r in records if r["label"] != "none")


def test_split_by_item_never_separates_an_items_variants():
    ex = [{"item": f"d-{i}", "n": n} for i in range(8) for n in range(3)]
    train, held = reward.split_by_item(ex, 0.25, seed=1)
    assert train and held
    assert not ({e["item"] for e in train} & {e["item"] for e in held})


# --------------------------------------------------------------------------
# M6 arms

def test_context_file_is_ordered_by_margin(taxonomy):
    prefs = {"step_size": reward.Preference("step_size", "stretches", "stretches", 0.4),
             "narration": reward.Preference("narration", "silent", "silent", 0.9),
             "register": reward.Preference("register", "indifferent", None, 0.0)}
    text = arms.context_file_text(prefs, taxonomy,
                                  {"step_size": "S.", "narration": "N.",
                                   "register": "R."})
    lines = text.splitlines()
    assert lines[0] == arms.CONTEXT_HEADER
    assert lines[1].endswith("N.") and lines[2].endswith("S.")
    assert "R." not in text          # indifferent axes never enter the prompt


def test_assemble_places_preferences_before_fill():
    arm = arms.Arm("context", system_prompt="PREFS")
    out = arms.assemble(arm, "TASK", "filler ", 1_000)
    assert out.startswith("PREFS")
    assert out.endswith("TASK")
    assert len(out) > 1_000 * arms.CHARS_PER_TOKEN


def test_a_fill_level_with_no_filler_is_an_error():
    with pytest.raises(ValueError):
        arms.assemble(arms.Arm("base"), "TASK", "", 8_000)


def test_adherence_excludes_axes_with_nothing_to_adhere_to(taxonomy):
    prefs = {"step_size": _pref("conditional", None, 0.0, COND),
             "narration": reward.Preference("narration", "indifferent", None, 0.0)}
    tax = {k: taxonomy[k] for k in ("step_size", "narration")}
    js = [{"dimension": "narration", "pole_prob": 0.9, "situation": {}},
          {"dimension": "step_size", "pole_prob": 0.9, "situation": {}},
          {"dimension": "step_size", "pole_prob": 0.1,
           "situation": {"reversibility": "reversible"}}]
    out = arms.adherence(js, prefs, tax)
    assert "narration" not in out["per_dimension"]      # no preference
    assert out["per_dimension"]["step_size"]["n"] == 1  # unknown situation dropped
    assert out["per_dimension"]["step_size"]["adherence"] == 1.0
    assert out["per_dimension"]["step_size"]["conditional"] is True


def test_slope_sign_and_sweep_gap():
    assert arms.slope([0, 10_000], [0.9, 0.5]) < 0
    assert arms.slope([0, 10_000], [0.5, 0.5]) == pytest.approx(0.0)
    by_arm = {
        "context": {0: {"pooled": {"adherence": 0.9}, "per_dimension": {}},
                    10_000: {"pooled": {"adherence": 0.5}, "per_dimension": {}}},
        "weights": {0: {"pooled": {"adherence": 0.8}, "per_dimension": {}},
                    10_000: {"pooled": {"adherence": 0.8}, "per_dimension": {}}},
    }
    s = arms.sweep_summary(by_arm)
    assert s["arms"]["context"]["slope_per_10k"] < s["arms"]["weights"]["slope_per_10k"]
    assert s["context_weights_gap_at_zero"] == pytest.approx(-0.1)


# --------------------------------------------------------------------------
# the chain, end to end on fixtures

def test_the_chain_recovers_a_planted_conditional(taxonomy, items):
    who = persona.Persona(
        wants={"step_size": "stretches", "narration": "silent"},
        conditional={"step_size": {"reversibility": {"reversible": "stretches",
                                                     "irreversible": "increments"}}},
        seed=5)
    # The whole agency pool per session: a flip needs four decided pairs at
    # each level, so an axis has to recur across the campaign to be measurable
    # at all. Under-sampling it reports the main effect and claims no flip,
    # which is the honest failure mode, not a wrong answer.
    n_pairs = sum(1 for it in items if it.layer == "agency")
    sessions = []
    for n in range(1, 5):
        plan = corpus.plan_session(taxonomy, items, n, n_pairs, 100 + n, "agency")
        sessions.append(persona.label_plan(plan, who, t0=1e6 + n * 1e5))
    prefs = labeling.aggregate_preferences(sessions, taxonomy)
    entry = prefs["dimensions"]["step_size"]
    assert entry["result"] == "conditional"
    levels = entry["conditionals"][0]["levels"]
    assert levels["reversible"]["pole"] == "stretches"
    assert levels["irreversible"]["pole"] == "increments"
    assert prefs["dimensions"]["narration"]["result"] == "silent"


def test_under_sampling_reports_the_main_effect_not_a_wrong_flip(taxonomy, items):
    who = persona.Persona(
        wants={"step_size": "stretches"},
        conditional={"step_size": {"reversibility": {"reversible": "stretches",
                                                     "irreversible": "increments"}}},
        seed=5)
    plan = corpus.plan_session(taxonomy, items, 1, 12, 101, "agency")
    prefs = labeling.aggregate_preferences([persona.label_plan(plan, who)], taxonomy)
    entry = prefs["dimensions"]["step_size"]
    assert entry["result"] != "conditional"
    assert not entry.get("conditional")
