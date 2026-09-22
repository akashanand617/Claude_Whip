"""A scripted free run is labelled by order: blocks from the stills, marks from the script; a miscounted block is skipped."""
import numpy as np

from probe import script as sc


def _stretches(times):
    """Stretches of 0.2 s at 4 g at the given onsets: (ons, offs, peaks)."""
    ons = np.array(times, dtype=float); return ons, ons + 0.2, np.full(len(ons), 4.0)


def test_blocks_come_from_the_stills_and_labels_from_the_order(tmp_path):
    p = tmp_path / "s.txt"; p.write_text("F^ S Fv\n\nC F<\n")
    script = sc.load_script(p)
    assert script == [[("flick", "up"), ("snap", "none"), ("flick", "down")], [("double_clap", "none"), ("flick", "left")]]
    ons, offs, peaks = _stretches([5.0, 6.2, 7.5, 12.0, 13.1])
    blocks = sc.group_blocks(ons, offs)
    assert [len(b) for b in blocks] == [3, 2]
    marks, report, tempo = sc.align(script, ons, offs, peaks, blocks)
    assert [(m["label"], m["direction"]) for m in marks] == script[0] + script[1]
    assert marks[0]["cue_at"] == round(5.0 - sc.CUE_LEAD_S, 3)
    assert all("labelled" in r for r in report) and tempo["under_decoder"] == 0


def test_a_block_with_the_wrong_count_is_skipped_not_guessed(tmp_path):
    p = tmp_path / "s.txt"; p.write_text("F^ S Fv\n\nC F<\n")
    script = sc.load_script(p)
    ons, offs, peaks = _stretches([5.0, 6.2, 12.0, 13.1])     # first block has one movement missing
    marks, report, _ = sc.align(script, ons, offs, peaks, sc.group_blocks(ons, offs))
    assert [(m["label"], m["direction"]) for m in marks] == script[1]
    assert "SKIPPED" in report[0] and "redo" in report[0]


def test_the_cut_follows_the_gestures_not_the_widest_gaps(tmp_path):
    """A double clap with a 0.9 s internal gap next to flicks 0.5 s apart: the widest gap is INSIDE a gesture."""
    p = tmp_path / "s.txt"; p.write_text("F^ C Fv\n")
    script = sc.load_script(p)
    # flick (2 strokes, 0.3 s), 0.5 s, double clap (2 claps 0.9 s apart), 0.5 s, flick (2 strokes)
    ons = np.array([5.0, 5.30, 5.80, 6.70, 7.20, 7.50]); offs = ons + 0.04; peaks = np.full(6, 4.0)
    parts, margin = sc.cut_block(ons, offs, peaks, list(range(6)), script[0])
    assert [p_["n_strokes"] for p_ in parts] == [2, 2, 2]
    assert [round(p_["on_s"], 2) for p_ in parts] == [5.0, 5.8, 7.2]
    assert margin > sc.MARGIN_OK


def test_an_ambiguous_block_is_skipped_rather_than_guessed(tmp_path):
    """Six identical single strokes for three gestures: several splits fit equally, so nothing is labelled."""
    p = tmp_path / "s.txt"; p.write_text("F^ Fv F<\n")
    script = sc.load_script(p)
    ons = np.array([5.0, 5.3, 5.6, 5.9, 6.2, 6.5]); offs = ons + 0.04; peaks = np.full(6, 4.0)
    marks, report, _ = sc.align(script, ons, offs, peaks, [list(range(6))])
    assert marks == [] and "not trustworthy" in report[0]
