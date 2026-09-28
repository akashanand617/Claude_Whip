import numpy as np

from whip.domain_analysis import canonical_mark_label, proper_axis_rotations, score_events, uniform_resample
from whip.realtime import GestureEvent


def test_canonical_mark_label_preserves_split_direction():
    assert canonical_mark_label({"label": "flick", "direction": "left"}) == "flick_left"
    assert canonical_mark_label({"label": "snap", "direction": "any"}) == "snap"


def test_proper_axis_rotations_are_24_unique_determinant_one_matrices():
    rotations = proper_axis_rotations()
    assert len(rotations) == 24
    assert len({matrix.tobytes() for _, matrix in rotations}) == 24
    assert all(round(float(np.linalg.det(matrix))) == 1 for _, matrix in rotations)


def test_uniform_resample_can_remove_short_cached_runs_without_erasing_long_holds():
    times = np.arange(0, 0.40, 0.04)
    x = np.array([[0, 0, 0, 3, 4, 4, 4, 4, 4, 9], [1] * 10, [2] * 10], dtype=float)
    grid, plain = uniform_resample(times, x)
    grid2, fresh = uniform_resample(times, x, collapse_short_duplicate_runs=True)
    assert np.array_equal(grid, grid2)
    assert plain.shape == fresh.shape == (3, len(grid))
    assert fresh[0, 1] > plain[0, 1]
    assert np.count_nonzero(fresh[0] == 4) >= 2


def test_score_events_separates_development_and_third_repetition():
    marks = [
        {"label": "snap", "direction": "any", "cue_at": 1.0, "repetition": 1},
        {"label": "flick", "direction": "left", "cue_at": 5.0, "repetition": 3},
    ]
    events = [
        GestureEvent("snap", "none", 1.2, 0.9, 3),
        GestureEvent("flick", "right", 5.2, 0.8, 3),
    ]
    result = score_events(events, marks)
    assert result["development_recall"] == 1.0
    assert result["validation_recall"] == 0.0
    assert result["confusions"] == {"flick_left->flick_right": 1}
