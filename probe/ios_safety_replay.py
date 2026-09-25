"""Expand offline phone parity; never train, connect, or modify model/firmware.

Checks every window in the existing test split against the bundled Core ML
model, then writes independent Python oracles for Swift numerical/decoder tests.
This is implementation parity, NOT a fresh accuracy/ambient or hardware result.
Direction ties use the earliest contributing vote, independent of hash seed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import torch

from probe.export_ios import CHANNELS, MODEL_SHA
from whip import accel, model as gm, realtime


def features(counts):
    x = np.asarray(counts, dtype=np.float64).T
    means = x.mean(axis=1, keepdims=True)
    return gm.to_model_input(((x - means) / accel.COUNTS_PER_G)[None], CHANNELS,
                             gravity=(means[:, 0] / accel.COUNTS_PER_G)[None])


def synthetic_trace(name, meta, pulses, label="flick_up", *, reset_at=None, tie=None, pulse_counts=32020):
    """Known probabilities isolate decoding from Core ML numerical conversion."""
    class Scripted(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.probabilities = []

        def forward_heads(self, x):
            index = len(self.probabilities)
            current = (tie[index - 7] if 7 <= index < 7 + len(tie) else "none") if tie else label
            logits = torch.full((1, len(meta["labels"])), -20.0)
            logits[0, list(meta["labels"]).index(current)] = 20
            self.probabilities.append(torch.softmax(logits, 1)[0].tolist())
            return logits, torch.zeros(1, 5)

    scripted = Scripted()
    engine = realtime.Engine(scripted, meta)
    engine.auto_frame = False
    samples, expected, resets = [], [], []
    for i in range(225):
        t = i * .04
        xyz = [pulse_counts if any(lo <= i <= hi for lo, hi in pulses) else 0, 8005, 0]
        if i == reset_at:
            engine = realtime.Engine(scripted, meta)
            engine.auto_frame = False
            resets.append(i)
        samples.append([t, *xyz])
        expected.extend(engine.feed_sample(t, xyz))
    # No finish(): teardown is required to drop pending movements.
    return dict(name=name, samples=samples, probabilities=scripted.probabilities,
                reset_indices=resets, events=[vars(e) for e in expected])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.fixtures.exists() or args.report.exists():
        parser.error("Output exists; choose new paths (no overwrite)")
    checkpoint = Path("data/model.pt")
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == MODEL_SHA
    torch.set_num_threads(1)
    model, meta = gm.load(checkpoint)
    assert meta["channels"] == CHANNELS
    split = Path("data/split/test.npz")
    z = np.load(split, allow_pickle=False)
    assert list(z["labels"]) == list(meta["labels"])
    import coremltools as ct
    ml = ct.models.MLModel("ios/R02Ring/Gesture/GestureClassifier.mlpackage", compute_units=ct.ComputeUnit.CPU_ONLY)
    inputs = gm.to_model_input(z["X"], CHANNELS, gravity=z["gravity"])
    worst, failures, predictions = 0.0, [], []
    for start in range(0, len(inputs), 128):
        with torch.no_grad():
            expected = torch.softmax(model(torch.from_numpy(inputs[start:start + 128])), 1).numpy()
        for j, wanted in enumerate(expected):
            actual = ml.predict({"samples": inputs[start + j:start + j + 1]})["probabilities"].reshape(-1)
            error = float(np.max(np.abs(actual - wanted)))
            worst = max(worst, error)
            if not np.isfinite(actual).all() or error > 1e-5:
                failures.append(dict(window=start + j, error=error))
            predictions.append(int(actual.argmax()))
        if start % 1024 == 0:
            print(f"Core ML parity: {min(start + 128, len(inputs))}/{len(inputs)} windows", flush=True)

    golden = []
    rotations = {"identity": np.eye(3), "flip_axis0": np.diag([1, -1, -1]),
                 "quarter_spin": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])}
    for label_index, label in enumerate(z["labels"]):
        choices = np.flatnonzero(z["y"] == label_index)
        assert len(choices), f"class absent: {label}"
        for index in choices[np.linspace(0, len(choices) - 1, 3, dtype=int)]:
            # Reconstruct the saved centred window + gravity, without pretending
            # these float32 corpus values are a new integer sensor recording.
            counts = (z["X"][index].astype(np.float64) + z["gravity"][index, :, None]) * accel.COUNTS_PER_G
            for rotation, matrix in rotations.items():
                samples = (matrix @ counts).T
                x = features(samples)
                with torch.no_grad():
                    probabilities = torch.softmax(model(torch.from_numpy(x)), 1)[0].tolist()
                golden.append(dict(name=f"{label}:{index}:{rotation}", label=str(label), rotation=rotation,
                                   counts=samples.tolist(), features=x.reshape(-1).tolist(), probabilities=probabilities))

    traces = [synthetic_trace(label, meta, [(75, 77)], label) for label in meta["labels"]]
    traces += [synthetic_trace("single_sample_below_floor", meta, [(75, 75)], pulse_counts=10000),
               synthetic_trace("double_internal_gap_not_split", meta, [(75, 77), (87, 89)], "double_clap"),
               synthetic_trace("consecutive_same_class", meta, [(75, 79), (105, 109)]),
               synthetic_trace("reset_discards_pending", meta, [(75, 77)], reset_at=80),
               synthetic_trace("direction_vote_tie", meta, [(75, 77)], tie=("flick_up", "flick_down")),
               synthetic_trace("direction_vote_tie_reversed", meta, [(75, 77)], tie=("flick_down", "flick_up")),
               synthetic_trace("direction_vote_tie_horizontal", meta, [(75, 77)], tie=("flick_right", "flick_left")),
               synthetic_trace("direction_vote_tie_horizontal_reversed", meta, [(75, 77)], tie=("flick_left", "flick_right"))]
    expected_counts = {"none": 0, "single_sample_below_floor": 0,
                       "reset_discards_pending": 0, "consecutive_same_class": 2}
    for trace in traces:
        assert len(trace["events"]) == expected_counts.get(trace["name"], 1), trace["name"]
    # Real wave + all-posture flick captures test the full model/decoder chain.
    replays = []
    for stem, tail in [("prompted_20260916_040358", None), ("prompted_20260916_044426", 1750)]:
        source = Path("data/sessions") / (stem + ".jsonl")
        samples = []
        for line in source.read_text().splitlines():
            row = json.loads(line)
            if row.get("p", "").startswith("a103"):
                packet = bytes.fromhex(row["p"])
                samples.append([row["t"], *[int.from_bytes(packet[i:i + 2], "big", signed=True) for i in (6, 2, 4)]])
        if tail: samples = samples[-tail:]
        assert len(samples) >= 50
        engine = realtime.Engine(model, meta); engine.auto_frame = False
        expected = []
        for t, *xyz in samples: expected.extend(engine.feed_sample(t, xyz))
        replays.append(dict(name=stem, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                            frame="identity", samples=samples, events=[vars(e) for e in expected]))
    report = dict(checkpoint_sha256=MODEL_SHA, split_sha256=hashlib.sha256(split.read_bytes()).hexdigest(),
                  windows_checked=len(inputs), max_probability_error=worst, failures=failures,
                  class_window_counts={str(label): int((z["y"] == i).sum()) for i, label in enumerate(z["labels"])},
                  predicted_labels=sorted({str(meta["labels"][i]) for i in predictions}),
                  golden_windows=len(golden), synthetic_traces=len(traces),
                  direction_tie_policy="first_non_none_vote", pythonhashseed=os.environ.get("PYTHONHASHSEED", "random"),
                  replays=[dict(name=r["name"], samples=len(r["samples"]), events=len(r["events"])) for r in replays],
                  limitation="Numerical/decoder parity only; not accuracy, freshness, health acquisition, or firmware validation")
    for path in (args.fixtures, args.report): path.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as f: json.dump(report, f, indent=2, allow_nan=False)
    with args.fixtures.open("x") as f:
        json.dump(dict(manifest=report, windows=golden, traces=traces, replays=replays), f, separators=(",", ":"), allow_nan=False)
        f.write("\n")
    print(json.dumps(report, indent=2), flush=True)
    if failures: raise SystemExit("Core ML parity FAILED; see report")


if __name__ == "__main__":
    main()
