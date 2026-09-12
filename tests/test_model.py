import pytest

torch = pytest.importorskip("torch")

from whip import model as gm


def a_batch(n=4):
    return torch.randn(n, gm.N_AXES, gm.WINDOW_SAMPLES)


def test_output_shape_is_one_logit_per_class():
    assert gm.GestureNet()(a_batch(4)).shape == (4, gm.N_CLASSES)


def test_parameter_count_stays_small():
    """
    17,859 parameters against a few hundred gestures. The measured failure mode
    is memorising the session, not underfitting, so growth here needs a reason.
    """
    assert sum(p.numel() for p in gm.GestureNet().parameters()) == 17859


def test_receptive_field_spans_the_longest_measured_gesture():
    """
    40 samples at 25 Hz is 1600 ms; the longest gesture measured was 1395 ms. If
    the stack ever shrinks below that, the network physically cannot see a whole
    double flick and no amount of data will fix it.
    """
    # rf grows by (kernel - 1) * jump; jump doubles at each pooling layer
    rf, jump = 1, 1
    for kernel, stride in ((5, 1), (2, 2), (5, 1), (2, 2), (7, 1)):
        rf += (kernel - 1) * jump
        jump *= stride
    assert rf == 40
    assert rf / 25 * 1000 >= 1395   # 1600 ms vs the 1395 ms longest gesture


def test_checkpoint_round_trips(tmp_path):
    """
    The first checkpoint pickled the module object, so only the notebook that
    defined the class could load it and `probe.rollout` could not read it at all.
    A state dict against an architecture that lives in the repo is loadable by
    anything that imports this module.
    """
    net = gm.GestureNet()
    net.eval()
    x = a_batch(3)
    with torch.no_grad():
        before = net(x)

    path = tmp_path / "m.pt"
    gm.save(net, path, trained_on=["s1", "s0"], held_out=["s2"])
    loaded, provenance = gm.load(path)

    with torch.no_grad():
        assert torch.allclose(before, loaded(x), atol=1e-6)
    assert provenance["trained_on"] == ["s0", "s1"]
    assert provenance["held_out"] == ["s2"]


def test_checkpoint_records_what_it_trained_on(tmp_path):
    """
    Without this, a report counts recall on a memorised session as evidence.
    Session 1 scores 200/200 and session 2 scores 44/64 from the same model.
    """
    path = tmp_path / "m.pt"
    gm.save(gm.GestureNet(), path, trained_on=["a"], held_out=["b"])
    _, provenance = gm.load(path)
    assert "trained_on" in provenance and provenance["trained_on"]


def test_augmentation_preserves_shape_and_finger_axis():
    """
    Rotation models the ring turning on the finger, which spins axes 1 and 2
    about axis 0. Rotating all three would model wearing it on another finger.
    """
    batch = a_batch(8)
    out = gm.augment(batch, amplitude=0.0, rotation_deg=30.0, noise_g=0.0)
    assert out.shape == batch.shape
    assert torch.allclose(out[:, 0], batch[:, 0], atol=1e-6)
    # the other two moved
    assert not torch.allclose(out[:, 1], batch[:, 1], atol=1e-3)


def test_rotation_preserves_magnitude_in_the_rotated_plane():
    batch = a_batch(8)
    out = gm.augment(batch, amplitude=0.0, rotation_deg=25.0, noise_g=0.0)
    before = (batch[:, 1] ** 2 + batch[:, 2] ** 2).sqrt()
    after = (out[:, 1] ** 2 + out[:, 2] ** 2).sqrt()
    assert torch.allclose(before, after, atol=1e-5)


def test_augmentation_defaults_are_the_gentle_ones():
    """
    The aggressive first version -- +/-30% amplitude, +/-30 degrees, time warp --
    cost more than ten points and manufactured false positives on the adversarial
    session. Time warp is absent entirely: interpolating between samples smooths
    the oscillation peaks that separate a single flick from a double.
    """
    assert gm.AMPLITUDE_RANGE <= 0.2
    assert gm.ROTATION_DEGREES <= 10.0
    assert not hasattr(gm, "time_warp")


def test_augmentation_can_be_turned_off_entirely():
    batch = a_batch(4)
    out = gm.augment(batch, amplitude=0.0, rotation_deg=0.0, noise_g=0.0)
    assert torch.allclose(out, batch, atol=1e-6)
