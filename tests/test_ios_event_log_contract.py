"""
The iOS app's research event log is consumed by `probe.label join` unchanged.

The fixture is byte-for-byte what `GestureEventLog` writes (pinned by the
Swift test `GestureEventLogTests.testSharedFixtureMatchesTheSwiftLineShape`);
these tests pin the other side: the same keys as `whip.realtime.EventLog`,
values already in `GestureEvent.as_dict()` form, and a working wall/action join.
"""

import glob
import json
import shutil
from pathlib import Path

from whip import labeling
from whip.realtime import GestureEvent

FIXTURE = (Path(__file__).resolve().parents[1]
           / "ios" / "R02RingTests" / "Fixtures" / "ios-event-log-sample.jsonl")


def _lines():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_keys_match_the_python_event_log():
    python_keys = set(GestureEvent(name="flick", direction="up", t_s=0.0, confidence=1.0,
                                   run_length=1).as_dict()) | {"action", "wall"}
    lines = _lines()
    assert len(lines) == 3
    for line in lines:
        assert set(line) == python_keys


def test_types_and_number_text_match_python_json():
    # Same JSON types EventLog writes (31.0 stays a float), and re-dumping
    # with sorted keys and compact separators reproduces each line byte for
    # byte, so the app's number text is Python's own.
    for raw, line in zip(FIXTURE.read_text().splitlines(), _lines()):
        assert json.dumps(line, sort_keys=True, separators=(",", ":")) == raw
        assert isinstance(line["name"], str) and isinstance(line["direction"], str)
        assert isinstance(line["run_length"], int) and not isinstance(line["run_length"], bool)
        assert isinstance(line["wall"], float)
        for key in ("t_s", "confidence", "latency_s", "end_s"):
            assert line[key] is None or isinstance(line[key], float), key
        assert line["action"] is None or isinstance(line["action"], str)
    assert _lines()[2]["t_s"] == 31.0 and isinstance(_lines()[2]["t_s"], float)


def test_values_are_already_in_as_dict_form():
    for line in _lines():
        event = GestureEvent(name=line["name"], direction=line["direction"], t_s=line["t_s"],
                             confidence=line["confidence"], run_length=line["run_length"],
                             latency_s=line["latency_s"], end_s=line["end_s"])
        assert {**event.as_dict(), "action": line["action"], "wall": line["wall"]} == line
    null_line = _lines()[2]
    assert null_line["action"] is None and null_line["latency_s"] is None and null_line["end_s"] is None


def _slot(slot, shown, labeled):
    return {"slot": slot, "wall_shown": shown, "wall_labeled": labeled, "label": "none",
            "source": "key", "ring": None}


def test_join_assigns_flag_and_approve_and_ignores_the_null_action(tmp_path):
    # Named the way the app names it, next to a lifecycle journal that the
    # documented `--events …/events_*.jsonl` glob must not pick up.
    shutil.copy(FIXTURE, tmp_path / "events_20260928_120000.jsonl")
    (tmp_path / "lifecycle_20260928.jsonl").write_text(
        json.dumps({"kind": "session_start", "wall": 1790000011.0, "action": "flag"}) + "\n")
    paths = sorted(glob.glob(str(tmp_path / "events_*.jsonl")))
    assert [Path(p).name for p in paths] == ["events_20260928_120000.jsonl"]

    events = labeling.load_events(paths)
    assert [e["wall"] for e in events] == sorted(e["wall"] for e in events)
    records = [
        _slot(0, 1790000000.0, 1790000011.0),   # flag at +1.5 s
        _slot(1, 1790000015.0, 1790000019.5),   # approve at +1.25 s
        _slot(2, 1790000025.0, 1790000031.0),   # wave at +1.0 s, action null
    ]
    joined = labeling.join_ring_events(records, events)
    assert [r["ring"]["status"] for r in joined] == ["ok", "ok", "missing"]
    assert [r["ring"]["label"] for r in joined] == ["flag", "approve", None]
    assert joined[0]["ring"]["name"] == "flick" and joined[0]["ring"]["direction"] == "right"
    assert joined[1]["ring"]["name"] == "double_flick" and joined[1]["ring"]["direction"] == "up"
    assert joined[0]["ring"]["confidence"] == 0.912
