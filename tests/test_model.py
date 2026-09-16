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
    assert sum(p.numel() for p in gm.CompactNet().parameters()) == 18068
    # 226,148 for the trunk + gesture head; the direction head adds 1,925.
    assert sum(p.numel() for p in gm.GestureNet().parameters()) == 228073


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
    gm.save(net, path, trained_on=["s1", "s0"], held_out=["s2"],
            labels=["none", "flick", "double_flick", "wave"])
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
    gm.save(gm.GestureNet(), path, trained_on=["a"], held_out=["b"],
            labels=["none", "flick", "double_flick", "wave"])
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
    gm.save(gm.CompactNet(), path, trained_on=["s1"], held_out=["s2"],
            labels=["none", "flick", "double_flick", "wave"])
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
    gm.save(net, path, trained_on=["s1"], held_out=["s2"],
            labels=["none", "flick", "double_flick", "wave"])
    loaded, provenance = gm.load(path)
    with torch.no_grad():
        assert torch.allclose(before, loaded(x), atol=1e-6)
    assert provenance["labels"] == ["none", "flick", "double_flick", "wave"]


def test_the_checkpoint_class_count_follows_its_labels(tmp_path):
    """Six recorded classes, six logits -- the model is sized by the data."""
    net = gm.GestureNet(n_classes=6)
    path = tmp_path / "six.pt"
    gm.save(net, path, trained_on=["s"], held_out=[],
            labels=["none", "flick", "double_flick", "snap", "wave", "clap"])
    loaded, _ = gm.load(path)
    assert loaded(a_batch(2)).shape == (2, 6)


def test_a_checkpoint_without_labels_is_refused(tmp_path):
    """Pre-vocabulary checkpoints mean something else; fail with instructions."""
    path = tmp_path / "old.pt"
    torch.save({"state_dict": gm.GestureNet().state_dict(),
                "architecture": "GestureNet", "n_channels": gm.N_CHANNELS}, path)
    with pytest.raises(ValueError, match="Retrain"):
        gm.load(path)


def test_direction_head_shares_the_trunk():
    net = gm.GestureNet()
    net.eval()
    x = a_batch(2)
    with torch.no_grad():
        gesture, direction = net.forward_heads(x)
        assert gesture.shape == (2, gm.N_CLASSES)
        assert direction.shape == (2, 5)
        assert torch.allclose(gesture, net(x), atol=1e-6), "same trunk, same logits"


def test_channel_groups_have_the_advertised_widths():
    import numpy as np

    raw = np.random.randn(4, gm.N_AXES, gm.WINDOW_SAMPLES).astype("float32")
    for groups in (("shape", "scale"),
                   ("gravity", "linear", "scale"),
                   ("gravity", "linear", "scale", "saturation"),
                   ("shape", "scale", "saturation")):
        out = gm.to_model_input(raw, groups)
        assert out.shape == (4, gm.n_channels_for(groups), gm.WINDOW_SAMPLES)


def test_gravity_and_linear_decompose_the_waveform_exactly():
    """
    Same information, split by frequency. If they did not sum back to `shape`
    the comparison between the two representations would be confounded by
    whatever the split was losing.
    """
    import numpy as np

    raw = np.random.randn(3, gm.N_AXES, gm.WINDOW_SAMPLES).astype("float32")
    g = gm.to_model_input(raw, ("gravity",))
    lin = gm.to_model_input(raw, ("linear",))
    shape = gm.to_model_input(raw, ("shape",))
    assert np.allclose(g + lin, shape, atol=1e-5)


def test_gravity_channel_keeps_slow_motion_and_linear_keeps_fast():
    """
    A wrist rotation moves the gravity vector slowly; a flick's oscillation is
    fast. The split is only useful if the cutoff actually separates them.
    """
    import numpy as np

    t = np.arange(gm.WINDOW_SAMPLES) / 25.0
    slow = np.zeros((1, 3, gm.WINDOW_SAMPLES), dtype="float32")
    slow[0, 0] = np.sin(2 * np.pi * 1.0 * t)          # 1 Hz, below the 2.8 Hz cutoff
    fast = np.zeros_like(slow)
    fast[0, 0] = np.sin(2 * np.pi * 8.0 * t)          # 8 Hz, a flick oscillation

    slow_g = np.abs(gm.to_model_input(slow, ("gravity",))).mean()
    slow_l = np.abs(gm.to_model_input(slow, ("linear",))).mean()
    fast_g = np.abs(gm.to_model_input(fast, ("gravity",))).mean()
    fast_l = np.abs(gm.to_model_input(fast, ("linear",))).mean()

    assert slow_g > slow_l, "1 Hz belongs to the gravity channel"
    assert fast_l > fast_g, "8 Hz belongs to the linear channel"


def test_saturation_channel_fires_only_on_clipped_windows():
    """
    Hard flicks hit the +/-4.09 g rail, which flat-tops the shape channel exactly
    where shape carries the discrimination. The model cannot tell a clipped
    plateau from a real one without being told.
    """
    import numpy as np

    quiet = np.zeros((1, gm.N_AXES, gm.WINDOW_SAMPLES), dtype="float32")
    clipped = quiet.copy()
    clipped[0, 0, 10:20] = gm.FULL_SCALE_G

    assert gm.to_model_input(quiet, ("saturation",)).max() == 0.0
    assert gm.to_model_input(clipped, ("saturation",)).max() > 0.0


def test_an_unknown_channel_group_is_refused():
    import numpy as np

    with pytest.raises(ValueError, match="unknown channel"):
        gm.to_model_input(np.zeros((1, 3, 50), dtype="float32"), ("shpae",))


def test_posture_channel_is_the_unit_gravity_vector_held_constant():
    import numpy as np

    raw = np.random.randn(2, gm.N_AXES, gm.WINDOW_SAMPLES).astype("float32")
    gravity = np.array([[0.0, 0.0, -1.0], [0.6, 0.0, -0.8]], dtype="float32")
    out = gm.to_model_input(raw, ("posture",), gravity=gravity)
    assert out.shape == (2, 3, gm.WINDOW_SAMPLES)
    assert np.allclose(out[0, :, 0], [0, 0, -1])
    assert np.allclose(out[1, :, 7], [0.6, 0, -0.8])
    assert np.allclose(out[:, :, 0], out[:, :, -1]), "constant over the window"


def test_posture_requires_gravity():
    import numpy as np

    with pytest.raises(ValueError, match="gravity"):
        gm.to_model_input(np.zeros((1, 3, 50), dtype="float32"), ("posture",))


def test_gref_channels_ignore_any_rotation_of_the_ring_frame():
    """
    The gravity-referenced group resolves motion along and across gravity.
    Rotating the whole frame -- window and gravity vector together, about any
    axis -- must leave it unchanged, and it must refuse to run without gravity.
    """
    import numpy as np

    rng = np.random.default_rng(0)
    raw = rng.standard_normal((4, gm.N_AXES, gm.WINDOW_SAMPLES)).astype("float32")
    grav = rng.standard_normal((4, 3)).astype("float32")
    # a rotation about an arbitrary axis (Rodrigues)
    k = np.array([0.3, -0.5, 0.8]); k /= np.linalg.norm(k); th = 1.1
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    Rm = (np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K).astype("float32")
    rot = np.einsum("ij,njw->niw", Rm, raw)
    grot = grav @ Rm.T
    a = gm.to_model_input(raw, ("gref",), gravity=grav)
    b = gm.to_model_input(rot, ("gref",), gravity=grot)
    assert a.shape[1] == gm.CHANNEL_WIDTHS["gref"] == 2
    assert np.allclose(a, b, atol=1e-4)
    # the perpendicular channel is a magnitude, never negative
    assert (a[:, 1] >= 0).all()
    with pytest.raises(ValueError):
        gm.to_model_input(raw, ("gref",))


def test_invariant_channels_ignore_a_spin_about_the_finger():
    """
    The ring turning on the finger rotates axes 1 and 2 into each other. The
    invariant group must not change at all under that -- no reference needed.
    """
    import numpy as np

    raw = np.random.randn(3, gm.N_AXES, gm.WINDOW_SAMPLES).astype("float32")
    theta = 0.7
    spun = raw.copy()
    spun[:, 1] = np.cos(theta) * raw[:, 1] - np.sin(theta) * raw[:, 2]
    spun[:, 2] = np.sin(theta) * raw[:, 1] + np.cos(theta) * raw[:, 2]
    a = gm.to_model_input(raw, ("invariant",))
    b = gm.to_model_input(spun, ("invariant",))
    assert np.allclose(a, b, atol=1e-5)
    # while the plain shape channels obviously do change
    assert not np.allclose(gm.to_model_input(raw, ("shape",)), gm.to_model_input(spun, ("shape",)))


def test_frame_flips_are_proper_rotations_and_gref_ignores_them():
    """
    Every training frame is right-handed (det +1): a mirror would swap the
    rotation sense that tells left from right. And the gravity-referenced
    channels do not change under any of them, which is the point of them.
    """
    import numpy as np

    rng = np.random.default_rng(1)
    frames = gm.random_frames(64, rng, flips=True)
    assert frames.shape == (64, 3, 3)
    assert np.allclose(np.linalg.det(frames), 1.0, atol=1e-5)
    assert np.allclose(np.einsum("nij,nkj->nik", frames, frames), np.eye(3)[None], atol=1e-5)
    # all four flips get used
    flips_seen = {tuple(np.sign(np.round(np.diag(f))).astype(int)) for f in gm.random_frames(200, rng, flips=True, spin_deg=0.0)}
    assert flips_seen == {(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)}
    raw = rng.standard_normal((64, gm.N_AXES, gm.WINDOW_SAMPLES)).astype("float32")
    grav = rng.standard_normal((64, 3)).astype("float32")
    xr, gr = gm.rotate_frame(raw, grav, frames)
    assert np.allclose(gm.to_model_input(raw, ("gref", "scale", "saturation"), gravity=grav),
                       gm.to_model_input(xr, ("gref", "scale", "saturation"), gravity=gr), atol=1e-4)
    # while the shape channels do change (that is what the model must learn to ignore)
    assert not np.allclose(gm.to_model_input(raw, ("shape",)), gm.to_model_input(xr, ("shape",)))
    # flips=False is the old behaviour: a small spin about the finger axis only
    spin = gm.random_frames(8, rng, flips=False)
    assert np.allclose(spin[:, 0, 0], 1.0) and np.allclose(spin[:, 0, 1:], 0.0)
