import numpy as np

from probe import axes


def rotate_about(axis, angle):
    """Rodrigues rotation matrix."""
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def gravity_rotating_about(axis, n=60, sweep=0.6, tilt=0.7):
    """
    A gravity trajectory produced by rotating about `axis`.

    The starting vector is deliberately off-axis: gravity exactly parallel to the
    rotation axis does not move at all, and would make every direction look
    equally like the answer.
    """
    start = np.cross(axis, [0.0, 0.0, 1.0])
    if np.linalg.norm(start) < 1e-6:
        start = np.cross(axis, [0.0, 1.0, 0.0])
    start = start / np.linalg.norm(start)
    start = np.cos(tilt) * np.asarray(axis, dtype=float) + np.sin(tilt) * start
    angles = np.linspace(-sweep, sweep, n)
    return np.stack([rotate_about(axis, t) @ start for t in angles], axis=1)


def test_recovers_the_axis_a_trajectory_was_rotated_about():
    for axis in ([1.0, 0, 0], [0, 1.0, 0], [0.3, -0.9, 0.2]):
        unit = np.asarray(axis, dtype=float)
        unit /= np.linalg.norm(unit)
        found, _ = axes.rotation_axis(gravity_rotating_about(unit))
        assert abs(float(np.dot(found, unit))) > 0.99


def test_flatness_is_low_for_a_rotation_and_high_for_noise():
    """
    The guard that stops a meaningless answer being reported as a measurement.
    Measured on real flicks the ratio is 0.008-0.010, i.e. a very clean rotation.
    """
    _, clean = axes.rotation_axis(gravity_rotating_about(np.array([1.0, 0.0, 0.0])))
    assert clean[0] / clean[2] < 0.05

    rng = np.random.default_rng(0)
    _, noise = axes.rotation_axis(rng.normal(0, 1, (3, 60)))
    assert noise[0] / noise[2] > 0.1


def test_gravity_track_low_passes_away_the_oscillation():
    """
    A flick's oscillation is fast; the gravity vector it swings is slow. The
    track must keep the second and discard the first, or the covariance is
    dominated by the oscillation rather than by the rotation.
    """
    from whip import accel

    class S:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    n = 100
    t = np.arange(n)
    fast = 0.5 * np.sin(2 * np.pi * 8 * t / 25)
    samples = [S(int((1.0 + fast[i]) * accel.COUNTS_PER_G), 0, 0) for i in range(n)]
    track = axes.gravity_track(samples)
    interior = track[0, 10:-10]
    assert interior.std() < 0.5 * fast.std(), "the 8 Hz component should be attenuated"


def test_describe_axis_names_the_closest_stored_axis():
    assert axes.describe_axis(np.array([0.95, 0.1, 0.2])).startswith("x")
    assert axes.describe_axis(np.array([0.1, -0.95, 0.2])).startswith("y")
    assert axes.describe_axis(np.array([0.1, 0.2, 0.95])).startswith("z")


def test_sign_of_an_eigenvector_does_not_change_the_answer():
    """Eigenvector sign is arbitrary, so alignment must be measured on |cos|."""
    unit = np.array([1.0, 0.0, 0.0])
    found, _ = axes.rotation_axis(gravity_rotating_about(unit))
    assert abs(float(np.dot(found, unit))) > 0.99
    assert abs(float(np.dot(-found, unit))) > 0.99
