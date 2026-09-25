import numpy as np
import pytest

torch = pytest.importorskip("torch")

from whip import accel, despike, evaluate, events
from whip import model as gm
from whip.realtime import Engine, EventLog, GestureEvent, RouterConfig
from probe.simulate import make_accel_payload


def make_provenance(labels=("none", "flick", "double_flick", "wave")):
    return {"labels": list(labels), "channels": ["shape", "scale"],
            "direction_names": ["none", "up", "down", "left", "right"]}


def trained_stub(labels):
    """A real (untrained) GestureNet -- the parity test needs consistency, not skill."""
    torch.manual_seed(0)
    return gm.GestureNet(n_classes=len(labels), n_channels=4)


def synthetic_counts(n_seconds=30.0, bursts=((8.0, 4000), (15.0, 6000)), seed=0):
    """A raw count stream: quiet noise with gesture-sized bursts."""
    rng = np.random.default_rng(seed)
    n = int(n_seconds * 25)
    t = np.arange(n) / 25.0
    x = rng.normal(0, 40, (3, n))
    for at, amp in bursts:
        idx = (t >= at) & (t < at + 1.0)
        x[0, idx] += amp * np.sin(2 * np.pi * 6 * t[idx])
        x[1, idx] += amp * np.cos(2 * np.pi * 6 * t[idx])
    return t, x


# ---------------------------------------------------------------- streaming despike

def test_streaming_hampel_matches_batch_on_the_interior():
    """
    The one documented difference is the MAD floor (running vs whole-trace);
    once the running median has converged the outputs must agree.
    """
    rng = np.random.default_rng(0)
    x = rng.normal(0, 50, (3, 500))
    x[0, 100] = 9000.0
    x[1, 300] = -9000.0

    batch = despike.hampel(x)

    stream = despike.StreamingHampel()
    out = []
    for i in range(x.shape[1]):
        out.extend(stream.push(x[:, i]))
    out.extend(stream.drain())
    streamed = np.stack(out, axis=1)

    assert streamed.shape == x.shape
    interior = slice(50, 450)
    assert np.allclose(streamed[:, interior], batch[:, interior], atol=1e-9)


def test_streaming_hampel_removes_the_spike_and_keeps_the_peak():
    t, x = synthetic_counts()
    # A glitch is a lone sample with quiet neighbours; one landing ON a burst
    # is indistinguishable from the burst and is kept by design (a snap at
    # the ring is a 1-2 sample shock, and the filter must not eat it).
    x[0, 100] = 30000.0                      # artifact, in the quiet before the first burst
    stream = despike.StreamingHampel()
    filtered = []
    for i in range(x.shape[1]):
        filtered.extend(stream.push(x[:, i]))
    vals = np.stack(filtered, axis=1)
    assert abs(vals[0]).max() < 25000, "the artifact must not survive"
    assert abs(vals[0]).max() > 3000, "the genuine burst must"


def test_streaming_lag_is_exactly_half_window():
    stream = despike.StreamingHampel()
    for i in range(20):
        got = stream.push([float(i), 0.0, 0.0])
        if got:
            # first non-empty push flushes the leading edge plus one filtered
            assert i == 2 * stream.half_window
            assert len(got) == stream.half_window + 1
            break
    else:
        raise AssertionError("never emitted")


def test_stream_output_length_equals_input_length():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 30, (3, 137))
    stream = despike.StreamingHampel()
    n = 0
    for i in range(x.shape[1]):
        n += len(stream.push(x[:, i]))
    n += len(stream.drain())
    assert n == x.shape[1]


# ---------------------------------------------------------------- engine parity

@pytest.mark.parametrize("directions, expected", [
    (["up", "down", "none"], "up"),
    (["down", "up", "none"], "down"),
    (["up", "down", "down"], "down"),
    (["none", "none", "none"], "none"),
])
def test_sustained_event_direction_uses_same_deterministic_vote_policy(directions, expected):
    provenance = make_provenance()
    engine = Engine(trained_stub(provenance["labels"]), provenance)
    engine._run_meta.extend((i * events.STRIDE_S, .8, d) for i, d in enumerate(directions))
    event = events.Event("wave", 0, 2 * events.STRIDE_S, 3)
    assert engine._enrich(event).direction == expected


def test_engine_events_are_identical_to_the_offline_pipeline():
    """
    THE test. The same despiked samples through the live engine and through the
    offline chain (windowing -> to_model_input -> model -> labels_at -> detect)
    must yield the same events. If this holds, live behaviour is whatever
    offline evaluation measured, and not a second implementation's opinion.
    """
    labels = ["none", "flick", "double_flick", "wave"]
    model = trained_stub(labels)
    engine = Engine(model, make_provenance(labels), threshold=0.30)

    # bursts above the 1 g onset (8005 counts) so the burst decoder has movements to judge
    t, x = synthetic_counts(n_seconds=40.0, bursts=((8.0, 14000), (20.0, 20000), (30.0, 11000)))
    x = despike.hampel(x)     # pre-despiked: parity isolates window/model/tracker

    live_events = []
    for i in range(x.shape[1]):
        live_events.extend(engine.feed_sample(float(t[i]), x[:, i]))
    live_events.extend(engine.finish())

    # offline: same windows, same maths
    starts, rows = [], []
    for s in range(0, x.shape[1] - 50 + 1, 6):
        win = x[:, s:s + 50]
        centred = (win - win.mean(axis=1, keepdims=True)) / accel.COUNTS_PER_G
        rows.append(centred)
        starts.append(float(t[s]))
    batch = gm.to_model_input(np.stack(rows), ("shape", "scale"))
    with torch.no_grad():
        probs = torch.softmax(model(torch.tensor(batch, dtype=torch.float32)), 1).numpy()
    mags = events.impulsive_magnitude(x / accel.COUNTS_PER_G)
    offline = events.detect_bursts(evaluate.labels_at(probs, labels, 0.30), starts, t, mags,
                                   policies=engine.tracker.policies)

    # the same movements were segmented on both sides (three bursts), and judged the same way
    tracker = events.BurstTracker(policies=engine.tracker.policies)
    due = np.searchsorted(t, np.asarray(starts)) + 49; wi = 0
    labels_off = evaluate.labels_at(probs, labels, 0.30)
    for i, (tt, m) in enumerate(zip(t, mags)):
        while wi < len(starts) and due[wi] <= i:
            tracker.feed_window(starts[wi], labels_off[wi]); wi += 1
        tracker.feed_sample(float(tt), float(m))
    tracker.finish()
    assert len(engine.tracker.bursts) == 3
    assert [(b.on_s, b.off_s, b.outcome) for b in engine.tracker.bursts] == \
           [(b.on_s, b.off_s, b.outcome) for b in tracker.bursts]
    assert [(e.name, round(e.t_s, 6), e.run_length) for e in live_events] == \
           [(e.label, round(e.centre_s, 6), e.run_length) for e in offline]


def test_engine_ignores_non_accelerometer_payloads():
    engine = Engine(trained_stub(["none", "flick"]),
                    make_provenance(["none", "flick"]))
    assert engine.feed(0.0, bytes([0xA1, 0x02] + [0] * 14)) == []   # PPG subtype
    assert engine.feed(0.0, b"\x03") == []                          # short battery frame


def test_engine_reports_live_probabilities_for_the_ui():
    labels = ["none", "flick", "double_flick", "wave"]
    engine = Engine(trained_stub(labels), make_provenance(labels))
    t, x = synthetic_counts(n_seconds=5.0, bursts=())
    for i in range(x.shape[1]):
        engine.feed_sample(float(t[i]), x[:, i])
    probs = engine.last_probabilities
    assert set(probs) == set(labels)
    assert abs(sum(probs.values()) - 1.0) < 1e-5


# ---------------------------------------------------------------- router

def test_direction_qualified_mapping_wins_over_the_bare_gesture():
    config = RouterConfig(mappings={"flick": "flag", "flick:up": "approve"})
    up = GestureEvent("flick", "up", 1.0, 0.9, 5)
    down = GestureEvent("flick", "down", 2.0, 0.9, 5)
    assert config.action_for(up) == "approve"
    assert config.action_for(down) == "flag"


def test_unmapped_gestures_resolve_to_no_action_not_an_error():
    """Other apps may care about events this one ignores; dropping them silently
    would defeat the point of a general classifier."""
    config = RouterConfig()
    assert config.action_for(GestureEvent("snap", "none", 1.0, 0.9, 4)) is None


def test_router_config_round_trips(tmp_path):
    path = tmp_path / "config.json"
    config = RouterConfig(mappings={"wave": "flag"}, threshold=0.75)
    config.save(path)
    loaded = RouterConfig.load(path)
    assert loaded.mappings == {"wave": "flag"}
    assert loaded.threshold == 0.75


def test_missing_config_gives_the_whip_defaults(tmp_path):
    config = RouterConfig.load(tmp_path / "absent.json")
    assert config.mappings == {"flick": "flag", "double_flick": "approve"}


def test_event_log_writes_consumable_jsonl(tmp_path):
    import json

    log = EventLog(tmp_path)
    log.write(GestureEvent("flick", "up", 12.5, 0.91, 6), action="flag")
    log.write(GestureEvent("snap", "none", 14.0, 0.85, 4), action=None)
    log.close()
    lines = [json.loads(l) for l in log.path.read_text().splitlines()]
    assert lines[0]["action"] == "flag" and lines[0]["direction"] == "up"
    assert lines[1]["action"] is None
    assert all("wall" in l for l in lines)


# ---------------------------------------------------------------- ring frame

def _payload(x: int, y: int, z: int) -> bytes:
    """A raw A1/03 packet encoded exactly as `accel.decode` reads it (signed16 big-endian; x at 6:8, y at 2:4, z at 4:6)."""
    from whip import protocol
    p = bytearray(16); p[0] = protocol.CMD_RAW_SENSOR; p[1] = protocol.SUBTYPE_ACCEL
    p[2:4] = int(y).to_bytes(2, "big", signed=True); p[4:6] = int(z).to_bytes(2, "big", signed=True); p[6:8] = int(x).to_bytes(2, "big", signed=True)
    return bytes(p)


def _pose(along_sign, n=50, still=True, seed=0):
    """A fingers-at-the-floor pose in counts: gravity along the finger axis, sign given."""
    from whip.model import FINGER_AXIS
    rng = np.random.default_rng(seed)
    g = np.zeros(3); g[FINGER_AXIS] = along_sign * 8005.0
    noise = rng.normal(0, 40 if still else 3000, (n, 3))
    return g[None, :] + noise


def test_frame_from_pose_reads_the_finger_sign_and_refuses_a_bad_pose():
    from whip.realtime import Engine
    assert Engine.frame_from_pose(_pose(+1)) == "identity"
    assert Engine.frame_from_pose(_pose(-1)) == "flip_axis0"
    assert Engine.frame_from_pose(_pose(-1, still=False)) is None        # moving
    sideways = _pose(+1); sideways[:, :] = np.roll(sideways, 1, axis=1)   # gravity on another axis
    assert Engine.frame_from_pose(sideways) is None


def test_a_frame_makes_the_engine_see_a_flipped_stream_as_canonical():
    """Feeding samples worn back to front, with the matching frame, must give the same windows as the canonical stream."""
    from whip.realtime import Engine
    labels = ["none", "flick", "double_flick", "wave"]
    prov = {"labels": labels, "channels": ["shape", "scale"], "direction_names": ["none", "up", "down", "left", "right"], "direction_trained": False}
    t, x = synthetic_counts()
    flip = np.diag([1.0, -1.0, -1.0])
    seen = {}
    net = gm.GestureNet(n_classes=len(labels), n_channels=4)      # ONE network for both runs
    for name, stream, frame in (("canon", x, "identity"), ("flipped", flip @ x, "flip_axis0")):
        eng = Engine(net, prov, threshold=0.5)
        eng.auto_frame = False; eng.set_frame(frame)
        probs = []
        orig = eng._classify_window
        def spy(orig=orig, eng=eng, probs=probs):
            out = orig(); probs.append(eng._last_probs.copy()); return out
        eng._classify_window = spy
        for i in range(stream.shape[1]):
            eng.feed(t[i], _payload(int(stream[0, i]), int(stream[1, i]), int(stream[2, i])))
        seen[name] = np.array(probs)
    assert seen["canon"].shape == seen["flipped"].shape
    assert np.allclose(seen["canon"], seen["flipped"], atol=1e-5)


def test_auto_frame_switches_when_the_fingers_point_at_the_floor():
    from whip.realtime import Engine
    labels = ["none", "flick", "double_flick", "wave"]
    prov = {"labels": labels, "channels": ["shape", "scale"], "direction_trained": False}
    eng = Engine(gm.GestureNet(n_classes=len(labels), n_channels=4), prov)
    pose = _pose(-1, n=60)
    for i in range(60):
        eng.feed(i / 25.0, _payload(int(pose[i, 0]), int(pose[i, 1]), int(pose[i, 2])))
    assert eng.frame_name == "flip_axis0" and eng.frame_changes and eng.frame_changes[0][1] == "flip_axis0"
    # calibrate() with an explicit canonical pose puts it back
    assert eng.calibrate(_pose(+1), t_s=9.0) == "identity" and eng.frame_name == "identity"


def test_pose_calibrator_accrues_only_while_the_pose_is_accepted():
    """The gate every tracking session passes through: progress restarts when the pose breaks, with the reason."""
    from whip.realtime import PoseCalibrator
    from whip.model import FINGER_AXIS
    rng = np.random.default_rng(1)
    cal = PoseCalibrator(hold_s=3.0)
    down = np.zeros(3); down[FINGER_AXIS] = -8005.0
    statuses = []
    t = 0.0
    for _ in range(80):                                   # 3.2 s of a still fingers-down pose
        r = cal.feed(t, down + rng.normal(0, 40, 3)); statuses.append(r["status"]); t += 0.04
    assert statuses[0] == "collecting" and "hold" in statuses and statuses[-1] == "ok"
    assert r["frame"] == "flip_axis0" and r["wearing"] == "reversed" and r["off_deg"] < 2
    assert cal.feed(t, down)["status"] == "ok"            # sticky once accepted

    cal.reset()
    tilted = np.array([5000.0, 0.0, 5000.0]); tilted[FINGER_AXIS] = -5000.0
    t = 0.0
    for _ in range(60):
        r = cal.feed(t, tilted + rng.normal(0, 40, 3)); t += 0.04
    assert r["status"] == "retry" and r["reason"] == "not_down" and 40 < r["off_deg"] < 60 and r["held_s"] == 0

    cal.reset(); t = 0.0
    for _ in range(60):
        r = cal.feed(t, -down + rng.normal(0, 3000, 3)); t += 0.04
    assert r["status"] == "retry" and r["reason"] == "moving" and r["motion"] > 0.25

    # a good pose that breaks after 2.5 s restarts from zero, it does not carry the credit
    cal.reset(); t = 0.0
    for _ in range(62):
        r = cal.feed(t, -down + rng.normal(0, 40, 3)); t += 0.04
    assert r["status"] == "hold" and r["held_s"] >= 2.4
    for _ in range(10):
        r = cal.feed(t, -down + rng.normal(0, 3000, 3)); t += 0.04
    assert r["status"] == "retry" and r["held_s"] == 0
    for _ in range(80):
        r = cal.feed(t, -down + rng.normal(0, 40, 3)); t += 0.04
    assert r["status"] == "ok" and r["frame"] == "identity" and r["wearing"] == "canonical"


def test_pose_check_explains_a_refused_pose():
    chk = Engine.pose_check(_pose(-1))
    assert chk["frame"] == "flip_axis0" and chk["still"] and chk["down"]
    chk = Engine.pose_check(_pose(-1, still=False))
    assert chk["frame"] is None and not chk["still"] and chk["motion"] > Engine.POSE_MAX_MOTION_G
