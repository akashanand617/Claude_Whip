import json

import pytest

from whip import events
from whip.registry import GestureSpec, Registry, load_registry


def test_legacy_aliases_resolve_to_canonical_names():
    r = Registry()
    assert r.canonical("flag") == "flick"
    assert r.canonical("approve") == "double_flick"
    assert r.canonical("waving") == "wave"
    assert r.canonical("snapping") == "snap"
    assert r.canonical("clapping") == "clap"


def test_unknown_names_resolve_to_nothing():
    """'dismissive flick' stays a hard negative, never silently a class."""
    r = Registry()
    assert r.resolve("dismissive flick") is None
    assert r.resolve("so-so wobble") is None


import dataclasses

from whip.registry import DEFAULT_GESTURES


def split_registry():
    return Registry(tuple(
        dataclasses.replace(g, split_by_direction=True) if g.name in ("flick", "double_flick") else g
        for g in DEFAULT_GESTURES))


def unsplit_registry():
    return Registry(tuple(
        dataclasses.replace(g, split_by_direction=False) if g.name in ("flick", "double_flick") else g
        for g in DEFAULT_GESTURES))


def test_labels_follow_registry_order_and_data_presence():
    r = unsplit_registry()
    assert r.labels_for({"wave", "flick"}) == ["none", "flick", "wave"]
    assert r.labels_for(set()) == ["none"]
    # a name the registry never declared cannot become a class by accident
    assert r.labels_for({"mystery"}) == ["none"]
    # under a split, the bare name of a split gesture is not a training class
    r = split_registry()
    assert r.labels_for({"wave", "flick_left"}) == ["none", "flick_left", "wave"]
    assert r.labels_for({"flick"}) == ["none"]


def test_flicks_are_direction_split_by_default_measured():
    """
    Trained on two sessions and tested on a fresh third, the split costs no
    recall (90.6% vs 90.6-93.8% unsplit, n=32, two seeds) and delivers
    direction at 93-96%. The earlier one-session result (6-9 points lost, a
    clean permutation) was data quantity plus posture being subtracted out.
    Only the flicks have a direction; snap/wave/clap do not split.
    """
    r = Registry()
    assert {g.name for g in r.gestures if g.split_by_direction} == {"flick", "double_flick"}
    assert r.collapse("flick_up") == ("flick", "up")
    assert r.collapse("snap") == ("snap", "none")


def test_split_sub_classes_collapse_back_to_the_gesture():
    r = split_registry()
    assert r.collapse("flick_up") == ("flick", "up")
    assert r.collapse("double_flick_left") == ("double_flick", "left")
    assert r.collapse("wave") == ("wave", "none")
    assert r.collapse("none") == ("none", "none")
    assert r.collapsed_names(["none", "flick_up", "flick_down", "wave"]) == ["none", "flick", "wave"]


def test_collapsing_probabilities_sums_sub_class_mass():
    """flick_up at 0.3 plus flick_left at 0.3 is a 0.6 flick to the threshold."""
    import numpy as np

    r = split_registry()
    labels = ["none", "flick_up", "flick_left", "wave"]
    probs = np.array([[0.3, 0.3, 0.3, 0.1]])
    out = r.collapse_probabilities(probs, labels)
    assert out.shape == (1, 3)
    assert np.allclose(out[0], [0.3, 0.6, 0.1])


def test_a_sustained_gesture_cannot_have_a_bounded_run():
    """max_run exists to reject sustained motion; a bounded wave is unfirable."""
    with pytest.raises(ValueError, match="max_run=None"):
        GestureSpec("wobble", "sustained", max_run=10)


def test_policies_are_runpolicies_keyed_by_canonical_name():
    r = Registry()
    policies = r.policies(["flick", "wave"])
    assert isinstance(policies["flick"], events.RunPolicy)
    assert not policies["flick"].sustained
    assert policies["wave"].sustained
    assert policies["wave"].refractory_s > 0


def test_registry_override_file_is_loaded(tmp_path):
    path = tmp_path / "gestures.json"
    path.write_text(json.dumps([
        {"name": "shake", "kind": "sustained", "min_run": 4, "refractory_s": 1.0},
        {"name": "tap", "kind": "impulsive"},
    ]))
    r = load_registry(path)
    assert r.names == ["shake", "tap"]
    assert r.resolve("shake").max_run is None, "sustained forces max_run off"


def test_duplicate_aliases_fail_loudly():
    with pytest.raises(ValueError, match="duplicate"):
        Registry((GestureSpec("a", "impulsive", aliases=("x",)),
                  GestureSpec("b", "impulsive", aliases=("x",))))


def test_double_clap_is_declared_impulsive_and_distinct_from_the_clap_span():
    r = load_registry()
    spec = r.resolve("double_clap")
    assert spec is not None and spec.kind == "impulsive" and spec.max_run is not None
    assert r.resolve("clap").kind == "sustained"
    assert "double_clap" in r.training_names()
