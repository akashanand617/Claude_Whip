import json
from pathlib import Path

from whip import session


def test_schedule_is_class_balanced():
    s = session.build_schedule(40, seed=1)
    assert len(s) == 40
    labels = [p.label for p in s]
    assert labels.count("flag") == labels.count("approve") == 20


def test_schedule_never_runs_more_than_two_of_a_class():
    """
    Blocked recording lets session drift -- ring position, sensor bias, how the
    ring settled -- correlate with the label for free. Drawing shuffled pairs
    bounds any run at two, which no independent draw would guarantee.
    """
    for seed in range(20):
        labels = [p.label for p in session.build_schedule(60, seed=seed)]
        run = longest = 1
        for a, b in zip(labels, labels[1:]):
            run = run + 1 if a == b else 1
            longest = max(longest, run)
        assert longest <= 2, f"seed {seed} produced a run of {longest}"


def test_odd_counts_are_handled():
    s = session.build_schedule(7, seed=3)
    assert len(s) == 7


def test_every_factor_varies_across_a_schedule():
    """Marginal balance is what decorrelates a factor from the label."""
    s = session.build_schedule(120, seed=7)
    assert len({p.direction for p in s}) == len(session.DIRECTIONS)
    assert len({p.amplitude for p in s}) == len(session.AMPLITUDES)
    assert len({p.windup for p in s}) == len(session.WINDUPS)
    assert len({p.posture for p in s}) == len(session.POSTURES)
    assert len({p.tempo for p in s}) == len(session.TEMPOS)


def test_factors_are_not_correlated_with_the_class():
    """
    The whole point of randomising: within each class every factor level should
    still appear. If a factor were drawn per-class it could become a shortcut.
    """
    s = session.build_schedule(200, seed=11)
    for label in session.CLASSES:
        subset = [p for p in s if p.label == label]
        assert len({p.direction for p in subset}) == len(session.DIRECTIONS)
        assert len({p.amplitude for p in subset}) == len(session.AMPLITUDES)


def test_seed_reproduces_a_schedule():
    assert session.build_schedule(30, seed=5) == session.build_schedule(30, seed=5)


def test_pacing_never_puts_two_gestures_in_one_window():
    """
    The real invariant, which an earlier version of this test missed by pinning
    an arbitrary gap constant instead.

    `approve` IS two flicks, so two `flag`s inside one 2.0 s window look exactly
    like an `approve` and no label for that window is correct. Cue-to-cue must
    therefore clear the longest gesture (1.4 s) plus the window (2.0 s), and the
    countdown counts toward that.
    """
    from probe.collect import COUNTDOWN_S
    from whip import dataset

    # Derive the requirement rather than trusting the constant: the latest
    # positive window starts (1 - coverage) into the gesture and runs a full
    # window, so the next gesture must begin after that.
    longest_gesture_s = 1.4
    window_s = dataset.WINDOW_SAMPLES / dataset.SAMPLE_RATE_HZ
    required = (1 - dataset.MIN_POSITIVE_COVERAGE) * longest_gesture_s + window_s

    assert session.MIN_CUE_TO_CUE_S >= required
    assert COUNTDOWN_S + session.MIN_GAP_S >= session.MIN_CUE_TO_CUE_S
    assert session.MAX_GAP_S > session.MIN_GAP_S


def test_prompt_names_the_class_first():
    p = session.build_schedule(2, seed=0)[0]
    assert p.spoken().startswith(("SINGLE", "DOUBLE"))


def test_notes_round_trip(tmp_path):
    notes = session.SessionNotes(
        session_id="prompted_x", started_wall=1.0, kind="prompted",
        hand="left", ring_position="index, logo up", note="test",
    )
    for p in session.build_schedule(4, seed=2):
        notes.add_mark(p, cue_at=float(p.index) * 5)

    path = tmp_path / "n.json"
    notes.write(path)
    back = session.load_notes(path)

    assert back.session_id == notes.session_id
    assert len(back.marks) == 4
    assert back.marks[0]["cue_at"] == 0.0
    assert "label" in back.marks[0]


def test_marks_carry_every_factor(tmp_path):
    """Offline analysis needs the full factor set to check for leakage."""
    notes = session.SessionNotes(
        session_id="s", started_wall=0.0, kind="prompted", hand="left", ring_position="index"
    )
    notes.add_mark(session.build_schedule(2, seed=0)[0], cue_at=1.0)
    mark = notes.marks[0]
    for field in ("label", "direction", "amplitude", "windup", "posture", "tempo", "cue_at"):
        assert field in mark


def test_capture_header_survives_a_notes_key_collision(tmp_path):
    """
    A session recorder putting its own "kind" in notes clobbered `kind: header`,
    so the loader parsed the header as a sample and every affected capture
    failed to load. Structural fields must win over caller notes.
    """
    from whip import capture

    rec = capture.Capture(
        device=capture.DeviceInfo(address="a", name="n"),
        started_wall=0.0, param=0xA1, label="x",
        notes={"kind": "negative", "label": "clobber", "hand": "left"},
    )
    header = rec.header()
    assert header["kind"] == "header"
    assert header["label"] == "x"
    assert header["hand"] == "left"


def test_loader_identifies_the_header_structurally(tmp_path):
    """Captures written before the fix carry the session kind in that field."""
    import json
    from whip import capture

    path = tmp_path / "c.jsonl"
    path.write_text(
        json.dumps({"kind": "negative", "device": {"name": "r"}}) + "\n"
        + json.dumps({"t": 0.0, "p": "a103" + "00" * 14}) + "\n"
        + json.dumps({"t": 0.04, "p": "a103" + "00" * 14}) + "\n"
    )
    header, records = capture.load_capture(path)
    assert header["kind"] == "negative"
    assert len(records) == 2


def test_structured_schedule_matches_the_requested_design():
    """10 soft + 15 hard per class, in each of four directions."""
    s = session.build_structured_schedule(seed=1)
    assert len(s) == 200
    for direction in session.DIRECTIONS:
        block = [p for p in s if p.direction == direction]
        assert len(block) == 50
        for label in session.CLASSES:
            per = [p for p in block if p.label == label]
            assert sum(1 for p in per if p.amplitude == "soft") == 10
            assert sum(1 for p in per if p.amplitude == "hard") == 15


def test_structured_schedule_interleaves_classes_within_every_block():
    """
    Blocking by direction is safe -- direction is not the label. Blocking by
    *class* would let fatigue and ring settling separate the classes for free,
    so the classes must alternate inside each direction block.
    """
    for seed in range(10):
        s = session.build_structured_schedule(seed=seed)
        for direction in session.DIRECTIONS:
            labels = [p.label for p in s if p.direction == direction]
            run = longest = 1
            for a, b in zip(labels, labels[1:]):
                run = run + 1 if a == b else 1
                longest = max(longest, run)
            assert longest <= 2, f"seed {seed}, {direction}: run of {longest}"


def test_amplitude_does_not_predict_the_class():
    """Both classes must span both amplitudes, or amplitude becomes a shortcut."""
    s = session.build_structured_schedule(seed=4)
    for label in session.CLASSES:
        amps = {p.amplitude for p in s if p.label == label}
        assert amps == {"soft", "hard"}


def test_directions_are_named_the_way_a_person_thinks():
    assert session.DIRECTIONS == ("up", "down", "left", "right")


def test_prompt_leads_with_the_class():
    p = session.build_structured_schedule(seed=0)[0]
    assert p.spoken().startswith(("SINGLE", "DOUBLE"))
    assert p.direction in p.spoken()


def test_preview_and_record_build_the_same_schedule():
    """
    They were built in two places and drifted: --soft/--hard reached the preview
    but not the recording, so the preview promised 104 prompts and the session
    ran 200.
    """
    import argparse

    from probe.collect import schedule_for

    args = argparse.Namespace(gestures=None, structured=True, soft=5, hard=8, seed=11, prompts=40)
    a = schedule_for(args)
    b = schedule_for(args)
    assert len(a) == len(b) == 104
    assert [p.spoken() for p in a] == [p.spoken() for p in b]

    args.soft, args.hard = 10, 15
    assert len(schedule_for(args)) == 200


def test_stream_publishes_its_clock_origin():
    """
    Cue timestamps are taken with perf_counter and must be expressed relative to
    the stream's start. Leaving stream_t0 at 0.0 recorded raw perf_counter --
    105,000 s outside a 660 s capture -- so every label missed and the session
    produced zero positive windows.
    """
    from whip import capture

    rec = capture.Capture(
        device=capture.DeviceInfo(address="a", name="n"),
        started_wall=0.0, param=0xA1, label="x", notes={"stream_t0": 0.0},
    )
    assert rec.notes["stream_t0"] == 0.0  # before streaming

    import inspect
    src = inspect.getsource(capture.stream)
    assert 'capture.notes["stream_t0"] = t0' in src, "stream must publish its clock origin"


def test_notes_tolerate_unknown_fields(tmp_path):
    """Notes accumulate metadata; an unknown key must not make a session unreadable."""
    import json

    path = tmp_path / "n.json"
    path.write_text(json.dumps({
        "session_id": "s", "started_wall": 0.0, "kind": "prompted",
        "hand": "left", "ring_position": "middle", "note": "",
        "marks": [], "recovered_offset_s": 12.5, "some_future_field": True,
    }))
    notes = session.load_notes(path)
    assert notes.session_id == "s"


def test_collect_builds_its_schedule_in_exactly_one_place():
    """
    The preview and the recording path each built their own schedule and drifted
    twice -- first --soft/--hard reached only the preview, then a partial fix
    left the recording path still calling the builder directly. Both times the
    preview promised one count and the session ran another.

    Testing schedule_for() in isolation did not catch it, because the bug was
    that a caller bypassed it. So assert there are no other construction sites.
    """
    import pathlib

    src = pathlib.Path("probe/collect.py").read_text()
    body = src.split("def schedule_for", 1)[1].split("\ndef ", 1)
    inside, rest = body[0], "".join(body[1:])

    assert "build_structured_schedule" in inside, "schedule_for should build the schedule"
    assert "build_structured_schedule" not in rest, "another call site bypasses schedule_for"
    assert "build_schedule(" not in rest, "another call site bypasses schedule_for"


def test_fill_schedule_cues_exactly_the_shortfall_interleaved():
    from whip import session

    short = {"flick_left": 10, "flick_down": 2, "double_flick_right": 5, "snap": 3}
    sched = session.build_fill_schedule(short, seed=3)
    assert len(sched) == 20
    from collections import Counter
    got = Counter((p.label, p.direction) for p in sched)
    assert got == {("flick", "left"): 10, ("flick", "down"): 2, ("double_flick", "right"): 5, ("snap", "any"): 3}
    # no class is cued twice in a row while another is still owed (flick_left is
    # half the schedule, so it can only repeat once the others are exhausted)
    streaks = sum(1 for a, b in zip(sched, sched[1:]) if (a.label, a.direction) == (b.label, b.direction))
    assert streaks <= 1
    # half soft, half hard within each class (odd counts split by one)
    for key, n in got.items():
        amps = Counter(p.amplitude for p in sched if (p.label, p.direction) == key)
        assert abs(amps["soft"] - amps["hard"]) <= 1
    # the tempo word is gone from the protocol: fixed, never varied
    assert {p.tempo for p in sched} == {"natural"}
    assert sched[0].spoken().startswith(("FLICK", "DOUBLE FLICK", "SNAP"))


def test_matrix_schedule_covers_every_posture_by_direction_cell_in_posture_blocks():
    from whip import session
    from collections import Counter

    sched = session.build_matrix_schedule(("flick",), reps=1, seed=4)
    assert len(sched) == 16
    cells = Counter((p.posture, p.direction) for p in sched)
    assert set(cells) == {(po, d) for po in session.MATRIX_POSTURES for d in session.DIRECTIONS}
    assert set(cells.values()) == {1}
    # posture blocks: the posture changes exactly 3 times over 16 prompts
    assert sum(1 for a, b in zip(sched, sched[1:]) if a.posture != b.posture) == 3
    assert "[PALM" in sched[0].spoken()
    # ordinary schedules never speak a posture
    assert "[" not in session.build_gesture_schedule(["flick"], 2, seed=1)[0].spoken()
    assert len(session.build_matrix_schedule(("flick", "double_flick"), reps=2, seed=1)) == 64


def test_blocked_schedule_runs_each_gesture_in_one_block_with_balanced_amplitude():
    from whip import session
    from collections import Counter

    sched = session.build_blocked_schedule(["snap", "double_snap", "clap", "double_clap"], 37, seed=1)
    assert len(sched) == 148
    labels = [p.label for p in sched]
    assert labels == ["snap"] * 37 + ["double_snap"] * 37 + ["clap"] * 37 + ["double_clap"] * 37
    for g in ("snap", "clap"):
        amps = Counter(p.amplitude for p in sched if p.label == g)
        assert abs(amps["soft"] - amps["hard"]) <= 1
    assert sched[0].posture == "block: snap" and "[" not in sched[0].spoken()
    # the exporter treats a block name like "as you are": no posture is being claimed


def test_blocked_fill_schedule_is_one_block_per_class_with_exact_counts():
    from whip import session

    sched = session.build_blocked_fill_schedule({"double_snap": 5, "flick_left": 3, "clap": 2}, seed=2)
    assert len(sched) == 10
    runs = []
    for p in sched:
        key = f"{p.label}_{p.direction}" if p.direction != "any" else p.label
        if not runs or runs[-1][0] != key: runs.append([key, 0])
        runs[-1][1] += 1
    assert sorted(runs) == [["clap", 2], ["double_snap", 5], ["flick_left", 3]]      # each class exactly once, in one run
    assert all(p.posture.startswith("block:") for p in sched)
