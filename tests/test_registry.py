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


def test_labels_follow_registry_order_and_data_presence():
    r = Registry()
    assert r.labels_for({"wave", "flick"}) == ["none", "flick", "wave"]
    assert r.labels_for(set()) == ["none"]
    # a name the registry never declared cannot become a class by accident
    assert r.labels_for({"mystery"}) == ["none"]


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
