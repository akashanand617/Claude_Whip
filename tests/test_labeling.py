"""
M3 labeling: record shape, the ring join contract, per-session scoring, and
cross-session aggregation. Labels here come from a deterministic persona over
real session plans -- a fixture for the machinery, not a claim about anyone's
taste.
"""

import pytest

from whip import corpus, labeling

PERSONA = {  # pole the persona approves; None = genuinely indifferent
    "scope": "minimal", "verbosity": "terse", "comments": "sparse",
    "abstraction": "concrete", "defensiveness": "trusting",
    "dependencies": "handroll", "initiative": "act-first",
    "proactivity": "exact", "idiom": "conform", "hedging": "committed",
    "cleverness": None, "testing": "focused",
}


@pytest.fixture(scope="module")
def taxonomy():
    return corpus.load_taxonomy()


@pytest.fixture(scope="module")
def items():
    return corpus.load_items()


def persona_label(p, persona=PERSONA):
    liked = persona[p["dimension"]]
    if liked is None:
        return "none"
    return "approve" if p["pole"] == liked else "flag"


def label_session(taxonomy, items, session, seed=7, pairs=12, persona=PERSONA,
                  t0=1_000_000.0, step=30.0):
    plan = corpus.plan_session(taxonomy, items, session, pairs, seed, "artifact")
    records = []
    for p in plan["presentations"]:
        shown = t0 + p["slot"] * step
        records.append(labeling.make_record(
            plan, p, persona_label(p, persona), "key", shown, shown + 20.0))
    return plan, records


def test_record_shape(taxonomy, items):
    plan, records = label_session(taxonomy, items, 1)
    r = records[0]
    for key in ("session", "seed", "slot", "item", "variant", "pole", "dimension",
                "sentinel_phase", "label", "source", "wall_shown", "wall_labeled",
                "ring"):
        assert key in r
    assert r["source"] == "key" and r["ring"] is None
    with pytest.raises(ValueError):
        labeling.make_record(plan, plan["presentations"][0], "meh", "key", 0, 1)
    with pytest.raises(ValueError):
        labeling.make_record(plan, plan["presentations"][0], "flag", "mouse", 0, 1)


def _event(wall, action, name="flick", direction="down"):
    return {"name": name, "direction": direction, "t_s": 0.0, "confidence": 0.9,
            "run_length": 5, "action": action, "wall": wall}


def test_join_uses_wall_and_mapped_action_only(taxonomy, items):
    _, records = label_session(taxonomy, items, 1)
    r0, r1 = records[0], records[1]
    events = [
        _event(r0["wall_labeled"] + 1.3, "flag"),           # inside slot 0
        _event(r1["wall_labeled"] + 1.0, None, "wave"),     # unmapped, ignored
        _event(r1["wall_labeled"] + 5.0, "approve"),        # past slot 1 window
    ]
    joined = labeling.join_ring_events(records, events)
    assert joined[0]["ring"]["status"] == "ok"
    assert joined[0]["ring"]["label"] == "flag"
    assert joined[0]["ring"]["confidence"] == 0.9
    assert joined[0]["ring"]["direction"] == "down"
    assert joined[1]["ring"] == {"status": "missing", "label": None}
    assert all(j["ring"]["status"] == "missing" for j in joined[2:])


def test_join_ambiguous_and_consumed_once(taxonomy, items):
    _, records = label_session(taxonomy, items, 1, step=21.0)  # windows overlap
    r0, r1 = records[0], records[1]
    # slot 0 window [t, t+22]; slot 1 starts at t+21 -> an event at t+21.5 lies
    # in both and must be consumed by slot 0 only
    shared = _event(r0["wall_shown"] + 21.5, "approve")
    joined = labeling.join_ring_events(records, [shared])
    assert joined[0]["ring"]["label"] == "approve"
    assert joined[1]["ring"]["status"] == "missing"
    conflicting = [_event(r1["wall_labeled"] + 0.5, "flag"),
                   _event(r1["wall_labeled"] + 1.5, "approve")]
    joined = labeling.join_ring_events(records, conflicting)
    assert joined[1]["ring"]["status"] == "ambiguous"
    assert joined[1]["ring"]["label"] is None


def test_direction_is_observed_but_never_routed_on(taxonomy, items):
    # Direction is accurate enough to route on, and deliberately not routed on:
    # the join keys on action only, so a wrong direction cannot change a label.
    _, records = label_session(taxonomy, items, 1)
    gesture = [r for r in records if r["label"] != "none"]
    events = [_event(gesture[0]["wall_labeled"] + 1.0, gesture[0]["label"],
                     direction="up"),
              _event(gesture[1]["wall_labeled"] + 1.0, gesture[1]["label"],
                     direction="down")]
    joined = labeling.join_ring_events(records, events)
    agreed = labeling.ring_agreement(joined)
    assert agreed["matched"] == 2           # both count, despite differing
    habit = agreed["direction_habit"]
    assert sum(sum(v.values()) for v in habit.values()) == 2
    assert {d for v in habit.values() for d in v} == {"up", "down"}


def test_ring_agreement_breakdown(taxonomy, items):
    _, records = label_session(taxonomy, items, 1)
    gesture = [r for r in records if r["label"] != "none"]
    none = [r for r in records if r["label"] == "none"]
    assert gesture and none
    events = [_event(gesture[0]["wall_labeled"] + 1.0, gesture[0]["label"]),
              _event(gesture[1]["wall_labeled"] + 1.0,
                     "flag" if gesture[1]["label"] == "approve" else "approve"),
              _event(none[0]["wall_labeled"] + 1.0, "flag")]
    joined = labeling.join_ring_events(records, events)
    a = labeling.ring_agreement(joined)
    assert a["matched"] == 1 and a["mismatched"] == 1
    assert a["missed"] == len(gesture) - 2
    assert a["spurious"] == 1 and a["silent"] == len(none) - 1
    assert a["recall"] == pytest.approx(2 / len(gesture))
    assert a["agreement_when_fired"] == 0.5


def test_score_session_accepts_consistent_persona(taxonomy, items):
    _, records = label_session(taxonomy, items, 1)
    s = labeling.score_session(records, taxonomy)
    assert s["sentinel_agreement"] == 1.0
    assert s["sentinels_scored"] == 2
    assert len(s["dimensions_present"]) == 12
    assert s["pairs"] == 12
    assert s["review"] == []
    assert s["accepted"], s["checks"]


def test_score_session_flags_drift_and_boredom(taxonomy, items):
    _, records = label_session(taxonomy, items, 1)
    drifted = [dict(r, label="none" if r.get("sentinel_phase") == "late" and r["label"] != "none"
                    else r["label"]) for r in records]
    s = labeling.score_session(drifted, taxonomy)
    assert s["sentinel_agreement"] < labeling.SENTINEL_AGREEMENT_MIN
    assert not s["checks"]["sentinel_agreement"]
    bored = [dict(r, label="none") for r in records]
    s = labeling.score_session(bored, taxonomy)
    assert not s["checks"]["reaction_coverage"]


def test_aggregate_recovers_persona(taxonomy, items):
    sessions = [label_session(taxonomy, items, n, seed=n)[1] for n in range(1, 5)]
    prefs = labeling.aggregate_preferences(sessions, taxonomy)
    for dim, liked in PERSONA.items():
        entry = prefs["dimensions"][dim]
        assert entry["result"] == (liked or "indifferent"), (dim, entry)
        if liked:
            assert entry["margin"] == 1.0
            assert entry["context_statement"]
    assert len(prefs["context_file"]) == 11
    assert prefs["review"] == []


def test_aggregate_marks_cross_session_disagreement_contested(taxonomy, items):
    flipped = dict(PERSONA, scope="opportunistic")
    sessions = [label_session(taxonomy, items, 1, seed=1)[1],
                label_session(taxonomy, items, 2, seed=2)[1],
                label_session(taxonomy, items, 3, seed=3, persona=flipped)[1],
                label_session(taxonomy, items, 4, seed=4, persona=flipped)[1]]
    prefs = labeling.aggregate_preferences(sessions, taxonomy)
    assert prefs["dimensions"]["scope"]["result"] == "contested"
    assert prefs["dimensions"]["verbosity"]["result"] == "terse"


def test_aggregate_routes_flag_flag_to_review(taxonomy, items):
    _, records = label_session(taxonomy, items, 1)
    both_flag = [dict(r, label="flag") if r["dimension"] == "testing"
                 and r.get("sentinel_phase") is None else r for r in records]
    prefs = labeling.aggregate_preferences([both_flag], taxonomy)
    assert prefs["review"]
    assert prefs["dimensions"]["testing"]["result"] == "unmeasured"


# ---------------------------------------------------------------------------
# conditional preferences: the agency layer's reason for existing

def _agency_records(taxonomy, dimension, per_level, session=1, t0=2_000_000.0):
    """
    Synthetic records for one axis at two levels of its first conditioner.
    Built directly rather than through plan_session so the test measures the
    aggregation, not the corpus's current item count.
    """
    factors = corpus.load_situation_factors()
    dim = taxonomy[dimension]
    a_pole, b_pole = dim.pole_keys()
    factor = factors[dim.conditioners[0]]
    records, slot = [], 0
    for level, liked in per_level.items():
        for n in range(4):
            item = f"{dimension}-{level}-{n}"
            for variant, pole in (("a", a_pole), ("b", b_pole)):
                label = "approve" if pole == liked else "flag"
                shown = t0 + slot * 30.0
                records.append({
                    "session": session, "seed": 1, "slot": slot, "item": item,
                    "variant": variant, "pole": pole, "dimension": dimension,
                    "layer": "agency", "situation": [level],
                    "sentinel_phase": None, "label": label, "source": "key",
                    "wall_shown": shown, "wall_labeled": shown + 20.0,
                    "ring": None})
                slot += 1
    assert factor  # the conditioner exists in the schema
    return records


def test_detects_a_preference_that_flips_with_the_situation(taxonomy):
    # wants big autonomous steps when the work is undoable, small ones when
    # it is not -- the policy the agency layer exists to capture
    records = _agency_records(taxonomy, "step_size",
                              {"reversible": "stretches",
                               "irreversible": "increments"})
    prefs = labeling.aggregate_preferences([records], taxonomy)
    entry = prefs["dimensions"]["step_size"]
    assert entry["result"] == "conditional"
    assert entry["conditional"] is True
    # a clean flip has no default pole: it cancels out in aggregate, which is
    # the honest reading, not a tie to be broken
    assert entry["default"] is None
    assert len(entry["conditionals"]) == 1
    levels = entry["conditionals"][0]["levels"]
    assert levels["reversible"]["pole"] == "stretches"
    assert levels["irreversible"]["pole"] == "increments"
    statement = entry["context_statement"]
    assert "the work is easy to undo" in statement
    assert "cannot be cheaply undone" in statement
    assert statement.count("When ") == 2  # one clause per situation


def test_unflipped_axis_is_reported_unconditional(taxonomy):
    records = _agency_records(taxonomy, "step_size",
                              {"reversible": "stretches",
                               "irreversible": "stretches"})
    entry = labeling.aggregate_preferences([records], taxonomy)["dimensions"]["step_size"]
    assert entry["result"] == "stretches"
    assert entry["conditional"] is False
    assert "Exception:" not in entry["context_statement"]
    poles = {p.key: p for p in taxonomy["step_size"].poles}
    assert entry["context_statement"] == poles["stretches"].context_statement


def test_a_flip_needs_evidence_at_both_levels(taxonomy):
    # one level below MIN_PAIRS_PER_LEVEL: report the main effect, claim no flip
    records = _agency_records(taxonomy, "step_size", {"reversible": "stretches"})
    thin = _agency_records(taxonomy, "step_size", {"irreversible": "increments"},
                           session=1, t0=3_000_000.0)
    kept = [r for r in thin if r["item"].endswith(("-0", "-1"))]
    entry = labeling.aggregate_preferences([records + kept],
                                           taxonomy)["dimensions"]["step_size"]
    assert entry["conditional"] is False


def test_context_statement_is_a_policy_not_a_constant(taxonomy):
    records = _agency_records(taxonomy, "verification",
                              {"reversible": "asserted",
                               "irreversible": "demonstrated"})
    entry = labeling.aggregate_preferences([records], taxonomy)["dimensions"]["verification"]
    assert entry["conditional"] is True
    s = entry["context_statement"]
    # a policy: each situation names the behaviour it calls for
    assert "When the work is easy to undo, state that the change works" in s
    assert "When the action cannot be cheaply undone, prove the change works" in s
    assert "step_size" not in s and "verification" not in s


# ---------------------------------------------------------------------------
# robustness to the shipped gesture vocabulary (M1 complete, 2026-09-21)

M1_VOCABULARY = ("flick", "double_flick", "snap", "double_clap", "wave")


def test_join_survives_the_full_gesture_vocabulary(taxonomy, items):
    """
    The classifier emits 11 classes; only the two the router maps carry an
    action. Every unmapped gesture must pass straight through the join -- they
    are the ambient false positives, and filtering on `action` rather than on a
    name list is what keeps them out without needing to know the vocabulary.
    """
    _, records = label_session(taxonomy, items, 1)
    gesture = [r for r in records if r["label"] != "none"]
    events = [_event(gesture[0]["wall_labeled"] + 1.0, gesture[0]["label"],
                     name="flick" if gesture[0]["label"] == "flag"
                     else "double_flick", direction="up")]
    # every unmapped class, landing inside slots, must be ignored
    for i, name in enumerate(n for n in M1_VOCABULARY
                             if n not in ("flick", "double_flick")):
        events.append(_event(records[i + 3]["wall_labeled"] + 0.5, None,
                             name=name, direction="none"))
    joined = labeling.join_ring_events(records, events)
    agreed = labeling.ring_agreement(joined)
    assert agreed["matched"] == 1
    assert agreed["spurious"] == 0
    assert all(j["ring"]["label"] in (None, "flag", "approve") for j in joined)


def test_join_spans_a_mid_session_reconnect(taxonomy, items):
    """
    A dropped BLE link starts a new events_*.jsonl. Sessions therefore join
    several files, and `load_events` must order them by wall time regardless of
    the order the files arrive in.
    """
    _, records = label_session(taxonomy, items, 1)
    gesture = [r for r in records if r["label"] != "none"][:2]
    early = _event(gesture[0]["wall_labeled"] + 1.0, gesture[0]["label"])
    late = _event(gesture[1]["wall_labeled"] + 1.0, gesture[1]["label"])
    merged = labeling.join_ring_events(records, [late, early])  # reversed
    fired = [j for j in merged if (j["ring"] or {}).get("label")]
    assert len(fired) == 2
    assert [j["ring"]["wall"] for j in fired] == sorted(j["ring"]["wall"]
                                                        for j in fired)


def test_an_unmapped_gesture_never_becomes_a_label(taxonomy, items):
    _, records = label_session(taxonomy, items, 1)
    none_slots = [r for r in records if r["label"] == "none"]
    assert none_slots
    events = [_event(none_slots[0]["wall_labeled"] + 0.5, None, name="double_clap")]
    joined = labeling.join_ring_events(records, events)
    assert all((j["ring"] or {}).get("label") is None for j in joined)
    assert labeling.ring_agreement(joined)["spurious"] == 0
