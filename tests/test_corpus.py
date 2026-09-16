"""
The M2 corpus and its session planner, tested against the real corpus files --
so the shipped taxonomy and items are validated as a side effect, the same way
test_fwimage runs against the real firmware images.
"""

import json

import pytest

from whip import corpus


@pytest.fixture(scope="module")
def taxonomy():
    return corpus.load_taxonomy()


@pytest.fixture(scope="module")
def items():
    return corpus.load_items()


@pytest.fixture(scope="module")
def gold(items):
    return [it for it in items if it.status == "gold"]


def test_taxonomy_shape(taxonomy):
    assert len(taxonomy) == 12
    for dim in taxonomy.values():
        a, b = dim.pole_keys()
        assert a != b
        for pole in dim.poles:
            assert pole.summary
            assert pole.context_statement.endswith(".")


def test_corpus_validates_clean(taxonomy, items):
    assert corpus.validate(taxonomy, items) == []


def test_every_dimension_has_five_gold(taxonomy, items):
    for key in taxonomy:
        gold = [it for it in items
                if it.dimension == key and it.status == "gold"]
        assert len(gold) >= 5, key
        domains = {it.domain for it in gold}
        assert len(domains) >= 3, f"{key}: domain leak, only {domains}"


def test_gold_items_are_complete(gold):
    assert len(gold) >= 60
    for it in gold:
        assert it.task and it.a.text and it.b.text and it.notes
        assert it.a.pole != it.b.pole


def test_sentinels_exist(gold):
    assert 2 <= sum(1 for it in gold if it.sentinel) <= 3


def test_validate_catches_duplicate_id(taxonomy, gold):
    problems = corpus.validate(taxonomy, [gold[0], gold[0]])
    assert any("duplicate" in p for p in problems)


def test_validate_catches_wrong_pole(taxonomy, gold):
    it = gold[0]
    broken = corpus.Item(
        id=it.id, dimension=it.dimension, status=it.status, domain=it.domain,
        sentinel=it.sentinel, task=it.task, context=it.context,
        a=corpus.Variant(pole="nonsense", text=it.a.text), b=it.b,
        notes=it.notes)
    problems = corpus.validate(taxonomy, [broken])
    assert any("poles" in p for p in problems)


def _length_leak_clones(taxonomy, dimension):
    a_pole, b_pole = taxonomy[dimension].pole_keys()
    return [
        corpus.Item(
            id=f"{dimension}-9{i}", dimension=dimension,
            status="gold", domain="python-tooling", sentinel=False,
            task="t", context="", notes="n",
            a=corpus.Variant(pole=a_pole, text="short"),
            b=corpus.Variant(pole=b_pole, text="a much longer response " * 5))
        for i in range(4)
    ]


def test_validate_catches_length_leak(taxonomy):
    # cleverness: length is incidental to the axis, so a constant longer-pole
    # is a leak
    problems = corpus.validate(taxonomy, _length_leak_clones(taxonomy,
                                                             "cleverness"))
    assert any("length predicts the pole" in p for p in problems)


def test_length_leak_exempts_constitutive_dimensions(taxonomy):
    # verbosity: explanatory is longer than terse by definition; not a leak
    assert taxonomy["verbosity"].length_constitutive
    problems = corpus.validate(taxonomy, _length_leak_clones(taxonomy,
                                                             "verbosity"))
    assert not any("length predicts the pole" in p for p in problems)


def test_label_pair_mapping():
    assert corpus.label_pair("approve", "flag") == {"preference": 2,
                                                    "review": False}
    assert corpus.label_pair("flag", "approve")["preference"] == -2
    assert corpus.label_pair("none", "none")["preference"] == 0
    assert corpus.label_pair("approve", "none")["preference"] == 1
    assert corpus.label_pair("flag", "flag")["review"] is True
    with pytest.raises(ValueError):
        corpus.label_pair("meh", "none")


def _plan(taxonomy, items, session=1, pairs=12, seed=7):
    return corpus.plan_session(taxonomy, items, session, pairs, seed)


def test_plan_is_deterministic(taxonomy, items):
    a = json.dumps(_plan(taxonomy, items))
    b = json.dumps(_plan(taxonomy, items))
    assert a == b
    different = json.dumps(_plan(taxonomy, items, seed=8))
    assert a != different


def test_plan_covers_every_dimension(taxonomy, items):
    plan = _plan(taxonomy, items, pairs=12)
    assert {p["dimension"] for p in plan["presentations"]} == set(taxonomy)


def test_plan_shows_each_pair_variant_once(taxonomy, items):
    plan = _plan(taxonomy, items)
    regular = [p for p in plan["presentations"] if p["sentinel_phase"] is None]
    shown = {}
    for p in regular:
        shown.setdefault(p["item"], []).append(p["variant"])
    for variants in shown.values():
        assert sorted(variants) == ["a", "b"]


def test_pair_members_are_separated(taxonomy, items):
    plan = _plan(taxonomy, items)
    regular = [p for p in plan["presentations"] if p["sentinel_phase"] is None]
    positions = {}
    for idx, p in enumerate(regular):
        positions.setdefault(p["item"], []).append(idx)
    for first, second in positions.values():
        assert second - first >= corpus.MIN_SEPARATION


def test_first_shown_pole_is_balanced(taxonomy, items):
    plan = _plan(taxonomy, items)
    regular = [p for p in plan["presentations"] if p["sentinel_phase"] is None]
    first_variant = {}
    for p in regular:
        first_variant.setdefault(p["item"], p["variant"])
    a_first = sum(1 for v in first_variant.values() if v == "a")
    assert abs(a_first - (len(first_variant) - a_first)) <= 1


def test_sentinels_repeat_same_variant_early_and_late(taxonomy, items):
    plan = _plan(taxonomy, items)
    pres = plan["presentations"]
    early = [p for p in pres if p["sentinel_phase"] == "early"]
    late = [p for p in pres if p["sentinel_phase"] == "late"]
    assert len(early) == len(late) >= 1
    n = len(pres)
    for e in early:
        match = next(l for l in late if l["item"] == e["item"])
        assert match["variant"] == e["variant"]
        assert e["slot"] < n / 4
        assert match["slot"] >= 3 * n / 4 - 1


def test_full_session_always_contains_the_sentinels(taxonomy, items, gold):
    # The pool (60) outgrows a session (40 pairs); sentinels must be selected
    # deliberately, not left to the draw, or the fatigue check silently
    # disappears from some sessions.
    sentinel_ids = {it.id for it in gold if it.sentinel}
    for seed in range(5):
        plan = corpus.plan_session(taxonomy, items, 1, 40, seed)
        planned = {p["item"] for p in plan["presentations"]}
        assert sentinel_ids <= planned, seed
        early = [p for p in plan["presentations"]
                 if p["sentinel_phase"] == "early"]
        assert len(early) == min(len(sentinel_ids), corpus.MAX_SENTINELS)


def test_plan_rejects_too_few_pairs(taxonomy, items):
    with pytest.raises(ValueError):
        corpus.plan_session(taxonomy, items, 1, 2, 7)


def test_plan_rejects_more_pairs_than_gold(taxonomy, items, gold):
    with pytest.raises(ValueError):
        corpus.plan_session(taxonomy, items, 1, len(gold) + 1, 7)
