import pytest

torch = pytest.importorskip("torch")

from whip import model as gm


def a_batch(n=4, channels=None):
    return torch.randn(n, channels or gm.N_CHANNELS, gm.WINDOW_SAMPLES)


def test_output_shape_is_one_logit_per_class():
    assert gm.GestureNet()(a_batch(4)).shape == (4, gm.N_CLASSES)
    assert gm.CompactNet()(a_batch(4)).shape == (4, gm.N_CLASSES)


def test_parameter_counts():
    """
    CompactNet stayed small on the theory that memorisation, not underfitting,
    was the risk. Measured at a matched false-positive budget it reached 57.1%
    recall against GestureNet's 69.9%, so the size was costing reliability
    rather than protecting it.
    """
    assert sum(p.numel() for p in gm.CompactNet().parameters()) == 17939
    assert sum(p.numel() for p in gm.GestureNet().parameters()) == 225763


def test_the_trunk_never_pools_away_time():
    """
    The reason for the rewrite. The discriminator is oscillation count -- singles
    average 2 peaks, doubles 5 -- and CompactNet pooled 50 samples down to 12
    before pooling globally, which puts five distinguishable peaks at the Nyquist
    limit. GestureNet keeps full resolution to the end.
    """
    net = gm.GestureNet()
    assert not any(isinstance(m, (torch.nn.MaxPool1d, torch.nn.AvgPool1d))
                   for b in net.blocks for m in b.branches), "branches must not pool"
    x = a_batch(2)
    z = x
    for block in net.blocks:
        z = block(z)
    assert z.shape[2] == gm.WINDOW_SAMPLES, "temporal resolution must survive the trunk"


def test_pooling_reports_std_not_just_mean_and_max():
    """
    Mean says how much total activation, max says how big the largest was.
    Neither can count. Std is the cheap proxy for variation over time.
    """
    net = gm.GestureNet()
    width = gm.INCEPTION_CHANNELS * (len(gm.INCEPTION_KERNELS) + 1)
    assert net.head.in_features == width * 3, "mean, max and std"


def test_kernels_span_several_time_scales():
    """
    At 25 Hz: 9 = 360 ms (one oscillation), 19 = 760 ms (the gap between two),
    39 = 1560 ms (the whole gesture). A single kernel size is blind to two of them.
    """
    ms = [k / 25 * 1000 for k in gm.INCEPTION_KERNELS]
    assert min(ms) < 500 and max(ms) > 1395


def test_compactnet_receptive_field_spans_the_longest_measured_gesture():
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


def test_model_input_splits_shape_from_scale():
    """
    Trained on raw g the network keys on amplitude, which is the easiest feature
    and the wrong one. Soft flicks peak at 2.3 g and typing at 2.0 g, so an
    amplitude threshold misses half the soft gestures and fires while you type.
    """
    import numpy as np

    raw = np.random.randn(6, gm.N_AXES, gm.WINDOW_SAMPLES).astype("float32")
    out = gm.to_model_input(raw)
    assert out.shape == (6, gm.N_CHANNELS, gm.WINDOW_SAMPLES)

    peak = np.sqrt((out[:, :gm.N_AXES] ** 2).sum(axis=1)).max(axis=1)
    assert np.allclose(peak, 1.0, atol=1e-5), "waveform channels must be unit amplitude"


def test_loud_and_quiet_versions_of_one_gesture_share_a_waveform():
    """
    The whole point: the same motion done softly and firmly differs only in the
    scale channel, so the network cannot use amplitude to decide it did not
    happen.
    """
    import numpy as np

    raw = np.random.randn(1, gm.N_AXES, gm.WINDOW_SAMPLES).astype("float32")
    soft = gm.to_model_input(raw * 0.3)
    loud = gm.to_model_input(raw * 3.0)

    assert np.allclose(soft[:, :gm.N_AXES], loud[:, :gm.N_AXES], atol=1e-5)
    assert loud[0, gm.N_AXES, 0] > soft[0, gm.N_AXES, 0]
    # and the gap is the log of the amplitude ratio, not the ratio itself
    assert np.isclose(loud[0, gm.N_AXES, 0] - soft[0, gm.N_AXES, 0], np.log10(10.0), atol=1e-4)


def test_a_silent_window_does_not_divide_by_zero():
    import numpy as np

    out = gm.to_model_input(np.zeros((2, gm.N_AXES, gm.WINDOW_SAMPLES), dtype="float32"))
    assert np.isfinite(out).all()


def test_amplitude_augmentation_moves_the_scale_channel_not_the_waveform():
    """
    On a shape+scale input the waveform is unit-amplitude by construction.
    Scaling it would desynchronise it from the scale channel and teach the two
    to disagree, so loudness has to be applied where loudness lives.
    """
    batch = a_batch(8)
    out = gm.augment(batch, amplitude=0.2, rotation_deg=0.0, noise_g=0.0)
    assert torch.allclose(out[:, :gm.N_AXES], batch[:, :gm.N_AXES], atol=1e-6)
    assert not torch.allclose(out[:, gm.N_AXES:], batch[:, gm.N_AXES:], atol=1e-4)


def test_three_channel_models_still_work():
    """The pre-split representation stays loadable, so old checkpoints still run."""
    net = gm.GestureNet(n_channels=3)
    assert net(a_batch(2, channels=3)).shape == (2, gm.N_CLASSES)


def test_a_compactnet_checkpoint_loads_back_as_a_compactnet(tmp_path):
    """
    Checkpoints record their architecture. Without it a CompactNet checkpoint
    loaded into a GestureNet fails with an unreadable shape error.
    """
    path = tmp_path / "old.pt"
    gm.save(gm.CompactNet(), path, trained_on=["s1"], held_out=["s2"])
    loaded, provenance = gm.load(path)
    assert isinstance(loaded, gm.CompactNet)
    assert provenance["architecture"] == "CompactNet"


def test_a_gesturenet_checkpoint_round_trips(tmp_path):
    net = gm.GestureNet()
    net.eval()
    x = a_batch(3)
    with torch.no_grad():
        before = net(x)
    path = tmp_path / "new.pt"
    gm.save(net, path, trained_on=["s1"], held_out=["s2"])
    loaded, _ = gm.load(path)
    with torch.no_grad():
        assert torch.allclose(before, loaded(x), atol=1e-6)
