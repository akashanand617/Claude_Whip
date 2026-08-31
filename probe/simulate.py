"""
Generate a synthetic capture so the whole analysis pipeline can be exercised
before the ring arrives.

This is a test fixture, not a model of the ring. It fabricates notifications at
a chosen rate with a chosen dropout pattern, which is enough to prove the
report, the gate logic and the decoders all work end to end.

    python -m probe.simulate --rate 21 --duration 60 --label sim_marginal
    python -m probe.simulate --rate 52 --duration 60 --accel-only --label sim_good
    python -m probe.report data/raw/sim_marginal_*.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

from whip import protocol

DATA_DIR = Path("data/raw")


def encode_reference(value: int) -> tuple[int, int]:
    """Inverse of the reference 12 bit unpacker, for round trip testing."""
    v = value + (1 << 11) if value < 0 else value
    return (v >> 4) & 0xFF, v & 0x0F


def make_accel_payload(x: int, y: int, z: int) -> bytes:
    payload = bytearray(16)
    payload[0] = protocol.CMD_RAW_SENSOR
    payload[1] = protocol.SUBTYPE_ACCEL
    payload[2], payload[3] = encode_reference(y)
    payload[4], payload[5] = encode_reference(z)
    payload[6], payload[7] = encode_reference(x)
    payload[-1] = protocol.checksum(payload[:-1])
    return bytes(payload)


def make_other_payload(subtype: int, value: int) -> bytes:
    payload = bytearray(16)
    payload[0] = protocol.CMD_RAW_SENSOR
    payload[1] = subtype
    payload[2] = (value >> 8) & 0xFF
    payload[3] = value & 0xFF
    payload[-1] = protocol.checksum(payload[:-1])
    return bytes(payload)


def generate(
    rate_hz: float,
    duration: float,
    accel_only: bool,
    dropout_rate: float,
    stall_every: float,
    stall_len: float,
    seed: int,
) -> list[tuple[float, bytes]]:
    rng = random.Random(seed)
    records: list[tuple[float, bytes]] = []

    interval = 1.0 / rate_hz
    t = 0.0
    i = 0

    while t < duration:
        in_stall = stall_every > 0 and (t % stall_every) < stall_len
        if not in_stall and rng.random() >= dropout_rate:
            # A ring at rest reads gravity on one axis plus a little noise.
            wobble = math.sin(t * 2.0) * 12
            x = int(60 + wobble + rng.gauss(0, 6))
            y = int(1024 + rng.gauss(0, 6))
            z = int(40 + rng.gauss(0, 6))
            records.append((t, make_accel_payload(x, y, z)))

            if not accel_only:
                # Stock firmware interleaves PPG and SpO2 on the same channel.
                records.append((t + interval * 0.33, make_other_payload(protocol.SUBTYPE_PPG, 10000 + i % 500)))
                records.append((t + interval * 0.66, make_other_payload(protocol.SUBTYPE_SPO2, 97)))

        t += interval * rng.uniform(0.9, 1.1)
        i += 1

    records.sort(key=lambda r: r[0])
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic capture for pipeline testing")
    parser.add_argument("--rate", type=float, default=21.0, help="accelerometer rate to simulate")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--label", default="sim")
    parser.add_argument("--accel-only", action="store_true", help="no PPG/SpO2 interleaving")
    parser.add_argument("--dropout-rate", type=float, default=0.01)
    parser.add_argument("--stall-every", type=float, default=20.0, help="seconds between stalls, 0 for none")
    parser.add_argument("--stall-len", type=float, default=0.5, help="stall duration in seconds")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    records = generate(
        args.rate, args.duration, args.accel_only, args.dropout_rate, args.stall_every, args.stall_len, args.seed
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{args.label}_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"

    with path.open("w") as f:
        f.write(
            json.dumps(
                {
                    "kind": "header",
                    "started_wall": time.time(),
                    "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "param": protocol.RAW_ENABLE_ALL,
                    "label": args.label,
                    "device": {"name": "SIMULATED", "address": "00:00:00:00:00:00", "firmware": "sim", "hardware": "sim"},
                    "simulated": True,
                }
            )
            + "\n"
        )
        for t, payload in records:
            f.write(json.dumps({"t": round(t, 6), "p": payload.hex()}) + "\n")

    print(f"wrote {len(records)} synthetic packets to {path}")
    print(f"\n  python -m probe.report {path} --stationary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
