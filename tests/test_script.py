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


def test_a_fast_block_is_cut_at_its_widest_gaps_to_the_script_count(tmp_path):
    """Six gestures as fourteen stretches with no real quiet: the five widest gaps are the boundaries."""
    p = tmp_path / "s.txt"; p.write_text("F^ S Fv S F< S\n")
    script = sc.load_script(p)
    # gesture k = strokes at k*0.7 + {0, 0.12, 0.24}... with 0.08 s dips inside and 0.3 s between gestures
    ons = []
    for k in range(6):
        base = 5.0 + k * 0.7
        ons += [base, base + 0.16] if k % 2 == 0 else [base, base + 0.12, base + 0.24]
    ons = np.array(ons); offs = ons + 0.08; peaks = np.full(len(ons), 4.0)
    marks, report, tempo = sc.align(script, ons, offs, peaks, sc.group_blocks(ons, offs))
    assert [m["label"] for m in marks] == [l for l, _ in script[0]]
    assert [round(m["onset_s"], 2) for m in marks] == [round(5.0 + k * 0.7, 2) for k in range(6)]
    assert tempo["under_decoder"] == 5 and "SKIPPED" not in report[0]
