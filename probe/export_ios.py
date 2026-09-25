"""Export the pinned model + a Python replay oracle; never train or touch BLE.

Run with torch, numpy and coremltools 9 installed. Output is generated ONLY after
CPU float32 Core ML probabilities pass the 1e-5 parity gate on the replay windows.
This is conversion evidence, not iPhone/background or firmware validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from whip import accel, model as gm, realtime

MODEL_SHA = "77ed774f03ce3eaddbb8ac29ac8dfc1be32fdd7bef997b56c54157891aff26d5"
CHANNELS = ["shape", "scale", "saturation", "room"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=Path("data/model.pt"))
    parser.add_argument("--replay", type=Path, default=Path("data/live/console_20260922_012043.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    if hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() != MODEL_SHA:
        raise ValueError("Checkpoint changed; review model contract before exporting")
    torch.set_num_threads(1)
    model, meta = gm.load(args.checkpoint)
    if meta["channels"] != CHANNELS or meta["n_channels"] != 8 or meta["window_samples"] != 50:
        raise ValueError("Unexpected preprocessing contract")

    class Probabilities(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model

        def forward(self, samples):
            return torch.softmax(self.model(samples), dim=1)

    import coremltools as ct
    wrapper = Probabilities().eval()
    traced = torch.jit.trace(wrapper, torch.zeros(1, 8, 50))
    converted = ct.convert(traced, inputs=[ct.TensorType(name="samples", shape=(1, 8, 50), dtype=np.float32)],
                           outputs=[ct.TensorType(name="probabilities", dtype=np.float32)],
                           minimum_deployment_target=ct.target.iOS17, convert_to="mlprogram",
                           compute_precision=ct.precision.FLOAT32, compute_units=ct.ComputeUnit.CPU_ONLY)
    samples = []
    for line in args.replay.read_text().splitlines():
        row = json.loads(line)
        if "p" in row and row["p"].startswith("a103"):
            payload = bytes.fromhex(row["p"])
            samples.append([row["t"], *[int.from_bytes(payload[i:i + 2], "big", signed=True) for i in (6, 2, 4)]])
    if len(samples) < 50:
        raise ValueError("Replay has no complete motion window")
    engine = realtime.Engine(model, meta, threshold=0.5)
    engine.auto_frame = False
    expected_events = []
    for t, *xyz in samples:
        expected_events.extend(engine.feed_sample(t, xyz))
    # Do NOT finish: session teardown drops pending gestures rather than firing them.
    windows, max_error = [], 0.0
    for start in range(0, len(samples) - 49, 6):
        counts = np.asarray([row[1:] for row in samples[start:start + 50]], dtype=np.float64).T
        means = counts.mean(axis=1, keepdims=True)
        features = gm.to_model_input(((counts - means) / accel.COUNTS_PER_G)[None], CHANNELS,
                                    gravity=(means[:, 0] / accel.COUNTS_PER_G)[None])
        with torch.no_grad():
            expected = wrapper(torch.from_numpy(features)).numpy()
        actual = converted.predict({"samples": features})["probabilities"]
        error = float(np.max(np.abs(expected - actual)))
        max_error = max(max_error, error)
        if not np.isfinite(actual).all() or error > 1e-5:
            raise ValueError(f"Float32 parity failed at sample {start}: max error {error}")
        # Freeze representative preprocessing vectors as well as full-stream events.
        if start % 300 == 0:
            windows.append({"start": start, "features": features.reshape(-1).tolist(),
                            "probabilities": expected.reshape(-1).tolist()})
    manifest = dict(checkpoint_sha256=MODEL_SHA, replay_sha256=hashlib.sha256(args.replay.read_bytes()).hexdigest(),
                    channels=CHANNELS, labels=meta["labels"], window_samples=50, stride_samples=6,
                    threshold=0.5, despike=False, frame="identity", conversion="float32 CPU only",
                    torch_version=torch.__version__, coremltools_version=ct.__version__,
                    windows_checked=(len(samples) - 50) // 6 + 1, max_probability_error=max_error)
    converted.user_defined_metadata["checkpoint_sha256"] = MODEL_SHA
    converted.user_defined_metadata["contract"] = json.dumps(manifest, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.fixtures.parent.mkdir(parents=True, exist_ok=True)
    converted.save(str(args.output))
    args.fixtures.write_text(json.dumps(dict(manifest=manifest, samples=samples, windows=windows,
                                           events=[vars(event) for event in expected_events]), separators=(",", ":")) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
