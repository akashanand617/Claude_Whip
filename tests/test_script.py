"""A scripted free run is labelled by order: blocks from the stills, marks from the script; a miscounted block is skipped."""
import numpy as np

from probe import script as sc
from whip import events


def _bursts(times):
    """Bursts at the given onsets (0.2 s of 4 g), run through the real tracker."""
    t = np.arange(0, max(times) + 4, 0.04); mag = np.zeros_like(t)
    for on in times:
        mag[(t >= on) & (t < on + 0.2)] = 4.0
    tr = events.BurstTracker()
    for tt, m in zip(t, mag):
        tr.feed_sample(float(tt), float(m))
    tr.finish()
    return tr.bursts


def test_blocks_come_from_the_stills_and_labels_from_the_order(tmp_path):
    p = tmp_path / "s.txt"; p.write_text("F^ S Fv\n\nC F<\n")
    script = sc.load_script(p)
    assert script == [[("flick", "up"), ("snap", "none"), ("flick", "down")], [("double_clap", "none"), ("flick", "left")]]
    blocks = sc.group_blocks(_bursts([5.0, 6.2, 7.5, 12.0, 13.1]))
    assert [len(b) for b in blocks] == [3, 2]
    marks, report = sc.align(script, blocks)
    assert [(m["label"], m["direction"]) for m in marks] == script[0] + script[1]
    assert marks[0]["cue_at"] == round(blocks[0][0].on_s - sc.CUE_LEAD_S, 3)
    assert all("labelled" in r for r in report)


def test_a_block_with_the_wrong_count_is_skipped_not_guessed(tmp_path):
    p = tmp_path / "s.txt"; p.write_text("F^ S Fv\n\nC F<\n")
    script = sc.load_script(p)
    blocks = sc.group_blocks(_bursts([5.0, 6.2, 12.0, 13.1]))     # first block has one movement missing
    marks, report = sc.align(script, blocks)
    assert [(m["label"], m["direction"]) for m in marks] == script[1]
    assert "SKIPPED" in report[0] and "redo" in report[0]
