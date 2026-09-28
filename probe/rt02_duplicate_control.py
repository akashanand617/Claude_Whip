"""Capture the exact RT02 25 Hz control used for consecutive-duplicate comparison.

This tool never flashes or sends diagnostic memory commands. It requires the
explicit CoreBluetooth identifier plus exact RT02CR hardware/firmware identity,
records one A1/03 stream, and always attempts A1 05 followed by A1 02 through
``capture.stream`` cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import time
from pathlib import Path

from whip import capture, protocol


EXPECTED_HARDWARE = "RT02CR_V3.1"
EXPECTED_FIRMWARE = "RT02CR_3.12.07_260514"


def analyse(records: list[tuple[float, bytes]], warmup: float = 2.0) -> dict:
    samples = [
        (t, packet) for t, packet in records
        if t >= warmup and len(packet) == 16 and packet[:2] == b"\xa1\x03"
        and protocol.checksum(packet[:-1]) == packet[-1]
    ]
    if len(samples) < 2:
        raise RuntimeError("fewer than two checksum-valid A1/03 samples")
    times = [sample[0] for sample in samples]
    payloads = [sample[1][2:8] for sample in samples]
    gaps = [right - left for left, right in zip(times, times[1:])]
    duplicates = sum(right == left for left, right in zip(payloads, payloads[1:]))
    decoded = [
        tuple(int.from_bytes(packet[offset:offset + 2], "big", signed=True)
              for offset in (6, 2, 4))
        for _, packet in samples
    ]
    spans = [max(value[axis] for value in decoded) - min(value[axis] for value in decoded)
             for axis in range(3)]
    return {
        "kind": "result",
        "samples": len(samples),
        "observed_s": times[-1] - times[0],
        # Identical definition to whip.domain_analysis.analyse.
        "notification_rate_hz": (len(times) - 1) / (times[-1] - times[0]),
        "consecutive_duplicate_count": duplicates,
        "consecutive_duplicate_fraction": duplicates / (len(payloads) - 1),
        "distinct_payloads": len(set(payloads)),
        "gap_median_s": statistics.median(gaps),
        "gap_p95_s": sorted(gaps)[math.ceil(0.95 * len(gaps)) - 1],
        "gap_max_s": max(gaps),
        "axis_span_counts": spans,
        "motion_observed": max(spans) >= 2_000,
    }


def analyse_archive(path: Path, phase: str = "optical_stop_mode3") -> dict:
    """Recompute the live-control metric from a pinned historical JSONL phase."""
    device = None
    phase_row = None
    result_row = None
    cleanup_row = None
    records: list[tuple[float, bytes]] = []
    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON at {path}:{line_number}") from exc
            if row.get("kind") == "device":
                device = row.get("device")
            elif row.get("kind") == "phase" and row.get("phase") == phase:
                phase_row = row
            elif row.get("kind") == "packet" and row.get("phase") == phase:
                try:
                    records.append((float(row["t"]), bytes.fromhex(row["p"])))
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError(f"invalid packet at {path}:{line_number}") from exc
            elif row.get("kind") == "result" and row.get("phase") == phase:
                result_row = row
            elif row.get("kind") == "cleanup":
                cleanup_row = row

    if not isinstance(device, dict) or (device.get("hardware"), device.get("firmware")) != (
        EXPECTED_HARDWARE, EXPECTED_FIRMWARE
    ):
        raise RuntimeError(f"archive identity mismatch: {device!r}")
    if phase_row is None or result_row is None or result_row.get("reason") != "time_limit":
        raise RuntimeError("archive lacks a completed measured phase")
    if cleanup_row is None or cleanup_row.get("errors") != [] \
            or cleanup_row.get("restoration") != "verified_000100":
        raise RuntimeError("archive lacks verified clean restoration")

    report = analyse(records, warmup=0)
    report.update({
        "source": str(path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "phase": phase,
        "phase_elapsed_s": float(result_row["elapsed_s"]),
        "device": device,
        "cleanup": cleanup_row["restoration"],
    })
    return report


async def run(args) -> int:
    output = args.output or (
        Path("firmware/research/2026-09-27/rt02-duplicate-control")
        / f"rt02_duplicate_{time.time_ns()}.jsonl"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    device = await capture.find_ring(address=args.address, timeout=args.timeout)
    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        if (info.address != args.address or info.hardware != EXPECTED_HARDWARE
                or info.firmware != EXPECTED_FIRMWARE):
            raise RuntimeError(
                f"identity mismatch: {info.as_dict()}; no raw command sent"
            )
        battery = await capture.read_battery(client)
        if battery is None or battery[1] or battery[0] < 20:
            raise RuntimeError("need a battery reading >=20% with the ring off its charger")
        recording = capture.Capture(
            device=info, started_wall=time.time(), param=protocol.RAW_ENABLE_ALL,
            label="rt02_duplicate_control",
            notes={
                "session_kind": "rt02_duplicate_control",
                "flashing": False,
                "cleanup": "A1 05 then A1 02",
                "battery_start": battery[0],
                "instruction": "alternate natural motion and stillness",
            },
        )
        print(f"Connected to exact RT02 {info.name}; battery {battery[0]}%.", flush=True)
        print(f"Move it naturally and include stillness for {args.duration:.0f} seconds.", flush=True)
        records = await capture.stream(
            client, duration=args.duration, capture=recording, sink=output
        )
    result = analyse(records, warmup=args.warmup)
    with output.open("a") as stream:
        stream.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    print(f"Saved {output}. No flash performed; A1 05/A1 02 cleanup attempted.", flush=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--address", help="exact CoreBluetooth identifier")
    source.add_argument("--archive", type=Path, nargs="+",
                        help="recompute controls from completed RT02 JSONL captures; no BLE")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--warmup", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if (not math.isfinite(args.duration) or args.duration < 10
            or not math.isfinite(args.warmup) or not 0 <= args.warmup < args.duration - 2
            or not math.isfinite(args.timeout) or args.timeout < 10):
        parser.error("duration >=10, 0<=warmup<duration-2, timeout>=10 required")
    if args.archive:
        try:
            results = [analyse_archive(path) for path in args.archive]
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"RT02 archive control stopped: {exc}", flush=True)
            return 2
        print(json.dumps(results, indent=2, sort_keys=True), flush=True)
        return 0
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, TimeoutError, ValueError) as exc:
        print(f"RT02 control stopped: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
