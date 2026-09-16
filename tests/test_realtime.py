import numpy as np
import pytest

torch = pytest.importorskip("torch")

from whip import accel, despike, evaluate, events
from whip import model as gm
from whip.realtime import Engine, EventLog, GestureEvent, RouterConfig


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

    t, x = synthetic_counts(n_seconds=40.0, bursts=((8.0, 4000), (20.0, 7000), (30.0, 2500)))
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
    offline = events.detect(evaluate.labels_at(probs, labels, 0.30), starts,
                            policies=engine.tracker.policies)

    assert [(e.name, round(e.t_s, 6)) for e in live_events] == \
           [(e.label, round(e.centre_s, 6)) for e in offline]


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
