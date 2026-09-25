"""Bounded post-flash validation for the compact unified candidate.

This never flashes. It refuses every sampled identity except the exact unified
candidate, verifies Health is the initial raw-mode state, exercises one dark
fresh 25 Hz Gesture interval, sends both audited stop packets, then proves the
stock realtime heart-rate path produces fresh BPM readings again.

LED state is physical and must still be observed by the wearer.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import time
from pathlib import Path

from probe import validate_optical_off
from whip import capture, fwidentity, fwimage, fwoptical, protocol

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "firmware/rt02cr-25hz.bin"
CANDIDATE = ROOT / "firmware/rt02cr-25hz-health-default-gesture-v1-experimental.bin"
STOCK = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
STOCK_SHA256 = "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0"
START_HR = bytes(protocol.make_packet(0x69, bytes([0x01, 0x01])))
STOP_HR = (
    bytes(protocol.make_packet(0x69, bytes([0x06, 0x04]))),
    bytes(protocol.make_packet(0x6A, bytes([0x01, 0x00, 0x00]))),
)


def validate_local_artifacts() -> tuple[bytes, bytes]:
    base, candidate, stock = BASE.read_bytes(), CANDIDATE.read_bytes(), STOCK.read_bytes()
    fwidentity.validate_images(base, unified_candidate=candidate)
    if hashlib.sha256(candidate).hexdigest() != fwidentity.UNIFIED_CANDIDATE_SHA256:
        raise ValueError("unified candidate SHA-256 mismatch")
    stock_image = fwimage.inspect(STOCK)
    if (hashlib.sha256(stock).hexdigest() != STOCK_SHA256
            or stock_image.hardware_string != fwoptical.HARDWARE
            or stock_image.size != len(stock)):
        raise ValueError("stock rollback image is absent or inconsistent")
    return base, candidate


async def health_resume(client, log, timeout: float) -> dict:
    records: list[tuple[float, bytes]] = []
    started = time.perf_counter()

    def notify(_sender, data):
        packet = bytes(data)
        records.append((time.perf_counter() - started, packet))

    await client.start_notify(protocol.UART_TX_CHAR_UUID, notify)
    try:
        await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, START_HR, response=False)
        deadline = time.perf_counter() + timeout
        readings: list[int] = []
        while time.perf_counter() < deadline and len(readings) < 5:
            readings = [p[3] for _, p in records
                        if len(p) == 16 and p[:3] == b"\x69\x01\x00"
                        and protocol.checksum(p[:-1]) == p[-1] and 30 <= p[3] <= 240]
            if len(readings) < 5:
                await asyncio.sleep(0.1)
        result = {
            "kind": "health_resume_result",
            "valid_bpm_readings": readings,
            "passed": len(readings) >= 5,
            "instruction": "Confirm the green emitter lit during this measurement",
        }
        log.write(json.dumps(result) + "\n")
        log.flush()
        return result
    finally:
        for packet in STOP_HR:
            try:
                await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
                await asyncio.sleep(0.15)
            except Exception as exc:  # teardown records the failure; raw cleanup follows outside
                log.write(json.dumps({"kind": "health_stop_error", "error": str(exc)}) + "\n")
                log.flush()
        await client.stop_notify(protocol.UART_TX_CHAR_UUID)


async def run(args) -> int:
    base, _candidate = validate_local_artifacts()
    directory = ROOT / "data/unified_validation"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"unified_validation_{time.time_ns()}.jsonl"
    with path.open("x") as log:
        log.write(json.dumps({"kind": "header", "started_wall": time.time(),
                              "candidate_sha256": fwidentity.UNIFIED_CANDIDATE_SHA256,
                              "flashing": False}) + "\n")
        device = await capture.find_ring(address=args.address, timeout=args.connect_timeout)
        async with capture.connected(device) as client:
            info = await capture.read_device_info(client, device)
            if (info.hardware != fwoptical.HARDWARE
                    or info.firmware != "RT02CR_3.12.07_260514"
                    or not protocol.is_expected_ring(info.name)):
                raise RuntimeError("unexpected ring or firmware family; no active command sent")
            battery = await capture.read_battery(client)
            log.write(json.dumps({"kind": "connection", "device": info.as_dict(),
                                  "battery": battery}) + "\n")
            log.flush()
            if battery is None or battery[1] or battery[0] < 40:
                raise RuntimeError("need battery >=40% and ring off charger")

            gesture = await validate_optical_off.exercise(
                client, log, base, duration=args.gesture_duration,
                idle_duration=args.stopped_duration,
                expected_classification=fwidentity.UNIFIED_CANDIDATE,
            )
            # The Health scheduler may wake the shared FIFO after raw Gesture
            # stops, so unified approval requires producer stop, not global idle.
            gesture_passed = (gesture["sample_checks_passed"]
                              and gesture["tracking_state_passed"]
                              and gesture["producer_stopped"])
            health = await health_resume(client, log, args.health_timeout)
            summary = {"kind": "summary", "gesture_passed": gesture_passed,
                       "health_resume_passed": health["passed"],
                       "human_led_checks_required": True,
                       "steps_sleep_continuity": "separate app/overnight gate"}
            log.write(json.dumps(summary) + "\n")
            log.flush()
    print(f"Saved {path}. No flash performed.")
    if gesture_passed and health["passed"]:
        print("Measured Gesture and Health-resume gates passed; confirm LED observations.")
        return 0
    print("Unified validation failed; remain on the current image or use the pinned stock rollback.")
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--gesture-duration", type=float, default=20)
    parser.add_argument("--stopped-duration", type=float, default=10)
    parser.add_argument("--health-timeout", type=float, default=45)
    parser.add_argument("--connect-timeout", type=float, default=90)
    args = parser.parse_args(argv)
    values = (args.gesture_duration, args.stopped_duration, args.health_timeout,
              args.connect_timeout)
    if any(not math.isfinite(value) or value < 10 for value in values):
        parser.error("all durations must be finite and at least 10 seconds")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
        print(f"Validation stopped: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
