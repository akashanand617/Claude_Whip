import numpy as np

from probe import directions


def rotate_about(axis, angle):
    a = np.asarray(axis, float); a /= np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def flick_stream(axis, g_rest, cue_at=3.0, n_s=8.0, sweep=1.4, seed=0):
    """Gravity at rest, then a wrist rotation about `axis` starting at the cue."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(n_s * 25)) / 25.0
    x = np.repeat(np.asarray(g_rest, float)[:, None], len(t), axis=1)
    win = (t >= cue_at) & (t < cue_at + 1.2)
    phase = np.sin(np.pi * (t[win] - cue_at) / 1.2) * sweep
    for i, ang in zip(np.where(win)[0], phase):
        x[:, i] = rotate_about(axis, ang) @ np.asarray(g_rest, float)
    return t, x + rng.normal(0, 0.005, x.shape)


def test_geometry_recovers_the_rotation_axis_and_the_posture():
    """
    A large sweep, as a real flick makes (they saturate the +/-4 g range). A
    gentle ~30 degree arc is nearly a straight line, and the least-variance
    direction is then ambiguous between the axis and the arc's curvature --
    which is a property of the estimator worth knowing, not a bug in it.
    """
    axis = np.array([0.2, 0.9, -0.3]); axis /= np.linalg.norm(axis)
    g_rest = np.array([0.0, 0.3, -0.95])
    t, x = flick_stream(axis, g_rest)
    got_axis, g_gesture, g0, flatness = directions.gesture_geometry(x, t, 3.0)
    assert abs(np.dot(got_axis, axis)) > 0.98
    assert np.dot(g0, g_rest / np.linalg.norm(g_rest)) > 0.99
    assert flatness < 0.05, "a single-axis rotation is a flat gravity trajectory"


def test_geometry_needs_rest_before_and_motion_after_the_cue():
    t, x = flick_stream([1, 0, 0], [0, 0, -1], cue_at=0.5)   # no rest window before
    assert directions.gesture_geometry(x, t, 0.5) is None


def test_unsigned_consistency_is_high_even_when_the_sense_flips():
    """
    The trap that produced 'up is random': a repeatable axis whose SENSE
    estimate flips reads ~0 signed and ~1 unsigned. The unsigned figure is what
    judges the session.
    """
    axes = np.array([[1, 0, 0], [-1, 0, 0]] * 5, float)
    signed = np.linalg.norm(axes.mean(axis=0))
    _, _, vt = np.linalg.svd(axes, full_matrices=False)
    aligned = axes * np.sign(axes @ vt[0])[:, None]
    unsigned = np.linalg.norm(aligned.mean(axis=0))
    assert signed < 0.05 and unsigned > 0.99
