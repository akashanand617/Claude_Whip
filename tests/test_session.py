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

    args = argparse.Namespace(structured=True, soft=5, hard=8, seed=11, prompts=40)
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
