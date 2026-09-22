"""Identify and exercise the permanent optical-off candidate without flashing.

    python -m probe.validate_optical_off --check-only --address <ring>
    python -m probe.validate_optical_off --cycles 3 --duration 120 --address <ring>

The active test refuses unpatched/mixed firmware. It sends A1 04 to start and
A1 05 / A1 02 to stop, NEVER the CE optical STOP or 3B keep-awake workaround.
Each cycle uses a new connection. Sampled code fingerprints are not whole-image
attestation. LED darkness remains a human observation, not a BLE measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from probe.ledcheck import accel_freshness
from whip import capture, fwidentity, fwoptical, protocol

BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"
STATE_READS = (
    ("raw_mode", 0x209CAC, 1),
    ("accel_state", 0x20BDC4, 12),
    ("idle_counter", 0x20CC4C, 3),
    ("connection_state", 0x209E09, 1),
)


def stream_report(records: list[tuple[float, bytes]], begin: float,
                  end: float, warmup_s: float = 2.0) -> dict:
    """Check freshness as well as packet rate; exclude asynchronous wake time."""
    accel_packets = [(t, p) for t, p in records
                     if begin + warmup_s <= t <= end and p[:2] == b"\xa1\x03"]
    samples = [(t, p) for t, p in accel_packets if len(p) == 16]
    duration = max(0.0, end - begin - warmup_s)
    rate = len(samples) / duration if duration else 0.0
    freshness = accel_freshness(samples, begin)
    first_gap = samples[0][0] - begin - warmup_s if samples else duration
    last_gap = end - samples[-1][0] if samples else duration
    max_gap = max([first_gap, last_gap] + [b[0] - a[0] for a, b in zip(samples, samples[1:])])
    invalid = sum(len(p) != 16 or protocol.checksum(p[:-1]) != p[-1] for _, p in accel_packets)
    distinct = len({p[2:8] for _, p in samples})
    # This test explicitly asks for movement as well as rest. Diversity and
    # dynamic range reject tiny fixed replays, but do not prove no possible
    # replay exists: the active FIFO-state check is independent evidence.
    axes = [tuple(int.from_bytes(p[i:i + 2], "big", signed=True) / 8005
                  for i in (6, 2, 4)) for _, p in samples]
    spans = [max(v[i] for v in axes) - min(v[i] for v in axes) for i in range(3)] if axes else [0.0] * 3
    motion = max(spans) >= 0.25
    repeats = freshness["max_identical_accel_s"]
    passed = (duration >= 5 and 24 <= rate <= 26 and max_gap <= 0.25
              and repeats is not None and repeats <= 0.5 and not invalid
              and distinct >= max(10, len(samples) * 0.5) and motion)
    return {"kind": "stream_result", "samples": len(samples), "observed_s": duration,
            "hz": rate, "max_gap_s": max_gap, "invalid_checksums": invalid,
            "distinct_xyz": distinct, "axis_span_g": spans, "motion_observed": motion, **freshness,
            "sample_checks_passed": passed, "led_darkness": "human_observation_required"}


class Session:
    """One notification owner, serialized read-only diagnostics, durable batches."""

    def __init__(self, client, log, cycle):
        self.client, self.log, self.cycle = client, log, cycle
        self.origin = time.perf_counter()
        self.records: list[tuple[float, bytes]] = []
        self.replies: asyncio.Queue = asyncio.Queue()
        self.written = 0
        self.phase = "identity"
        self.poisoned = False

    def now(self):
        return time.perf_counter() - self.origin

    def emit(self, event):
        event = {"cycle": self.cycle, "phase": self.phase, **event}
        self.log.write(json.dumps(event) + "\n")
        self.log.flush()
        if event.get("kind") != "packet":
            print(json.dumps(event), flush=True)

    def notify(self, _sender, data):
        record = self.now(), bytes(data)
        self.records.append(record)
        if data[:1] == b"\xcd":
            self.replies.put_nowait(record[1])

    def flush(self):
        for t, p in self.records[self.written:]:
            self.log.write(json.dumps({"kind": "packet", "cycle": self.cycle,
                                       "phase": self.phase, "t": t, "p": p.hex()}) + "\n")
        self.written = len(self.records)
        self.log.flush()

    async def read(self, packet, timeout=3.0):
        if self.poisoned or not self.replies.empty():
            self.poisoned = True
            raise RuntimeError("Diagnostic correlation lost; reconnect before another read")
        try:
            await self.client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
            reply = await asyncio.wait_for(self.replies.get(), timeout)
            if len(reply) != 16 or reply[0] != 0xCD or protocol.checksum(reply[:-1]) != reply[-1]:
                raise RuntimeError("Invalid diagnostic reply")
            return reply
        except BaseException:
            # No register/address echo: never retry after a late/ambiguous reply.
            self.poisoned = True
            raise

    async def identify(self, base):
        samples = {}
        for site in fwidentity.read_sites():
            reply = await self.read(fwidentity.read_packet(site))
            samples[site.name] = fwidentity.decode_reply(site, reply)
            self.emit({"kind": "code_read", "name": site.name,
                       "address": hex(site.address), "data": samples[site.name].hex()})
        classification = fwidentity.classify(base, samples)
        self.emit({"kind": "identity", "classification": classification,
                   "scope": "critical_code_sites_only_not_full_image"})
        return classification

    async def state(self):
        values = {}
        for name, address, length in STATE_READS:
            packet = protocol.make_packet(0xCD, bytes([1, length]) + address.to_bytes(4, "big"))
            reply = await self.read(packet)
            values[name] = reply[1:1 + length]
        result = {"kind": "state", "t": self.now(),
                  "raw_mode": values["raw_mode"][0],
                  "fifo_consumer_active": values["accel_state"][1],
                  "pending_idle_request": values["accel_state"][6],
                  "inactivity_counter": values["idle_counter"][2],
                  "connection_state": values["connection_state"][0]}
        self.emit(result)
        return result

    async def observe(self, duration):
        deadline = self.now() + duration
        while self.now() < deadline:
            await asyncio.sleep(min(10.0, max(0.0, deadline - self.now())))
            self.flush()

    async def stop_raw(self):
        errors = []
        for packet in protocol.STOP_RAW_SENSOR_PACKETS:
            try:
                await self.client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
                await asyncio.sleep(0.15)
            except Exception as exc:
                errors.append(str(exc))
        self.emit({"kind": "stop_commands", "errors": errors})
        return not errors


async def exercise(client, log, base, *, cycle=1, check_only=False,
                   duration=60.0, idle_duration=15.0):
    session = Session(client, log, cycle)
    attempted_start = False
    try:
        await client.start_notify(protocol.UART_TX_CHAR_UUID, session.notify)
        classification = await session.identify(base)
        if check_only:
            return {"classification": classification}
        if classification != "optical_off_candidate":
            raise RuntimeError("Active validation requires the optical-off candidate fingerprint; no start sent")
        await session.state()
        session.flush()
        session.phase = "tracking_A104_only"
        begin = session.now()
        attempted_start = True
        await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, protocol.ENABLE_RAW_SENSOR, response=False)
        session.emit({"kind": "start", "t": begin, "command": "A1 04",
                      "instruction": "Observe LEDs; alternate motion and stillness"})
        await session.observe(duration)
        result = stream_report(session.records, begin, session.now())
        state = await session.state()
        result["tracking_state_passed"] = (state["raw_mode"] == 4 and
                                            state["fifo_consumer_active"] == 1 and
                                            state["connection_state"] == 2)
        session.emit(result)
        session.flush()
        session.phase = "stopped_observation"
        stop_ok = await session.stop_raw()
        stopped_at = session.now()
        session.emit({"kind": "stop_observation", "t": stopped_at,
                      "instruction": "Leave the ring still while idle resumes"})
        await session.observe(idle_duration)
        state = await session.state()
        late = sum(t > stopped_at + 2 and p[:2] == b"\xa1\x03" for t, p in session.records)
        session.emit({"kind": "stop_result", "late_accel_packets": late,
                      "producer_stopped": stop_ok and late == 0 and state["raw_mode"] == 0,
                      "idle_observed": state["fifo_consumer_active"] == 0,
                      "note": "Motion can defer idle; an active flag is not itself proof of a bug"})
        return {**result, "producer_stopped": stop_ok and late == 0 and state["raw_mode"] == 0,
                "idle_observed": state["fifo_consumer_active"] == 0}
    finally:
        try:
            if attempted_start:
                await session.stop_raw()
        finally:
            session.flush()
            await client.stop_notify(protocol.UART_TX_CHAR_UUID)


async def run(args):
    base = BASE.read_bytes()
    fwidentity.validate_images(base)  # Refuse a corrupt local reference before BLE.
    directory = Path("data/ledcheck")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"firmware_validation_{time.time_ns()}.jsonl"
    results = []
    with path.open("x") as log:
        log.write(json.dumps({"kind": "header", "started_wall": time.time(),
                              "check_only": args.check_only, "flashing": False}) + "\n")
        try:
            for cycle in range(1, (1 if args.check_only else args.cycles) + 1):
                device = await capture.find_ring(address=args.address)
                async with capture.connected(device) as client:
                    info = await capture.read_device_info(client, device)
                    if (info.hardware != fwoptical.HARDWARE or
                            info.firmware != "RT02CR_3.12.07_260514" or
                            not protocol.is_expected_ring(info.name)):
                        raise RuntimeError("Unexpected ring or firmware family; no diagnostic memory reads sent")
                    battery = await capture.read_battery(client)
                    log.write(json.dumps({"kind": "connection", "cycle": cycle,
                                          "device": info.as_dict(), "battery": battery}) + "\n")
                    log.flush()
                    if battery is None or battery[1] or battery[0] < 20:
                        raise RuntimeError("Need a battery reading >=20% and the ring off its charger")
                    results.append(await exercise(client, log, base, cycle=cycle, check_only=args.check_only,
                                                  duration=args.duration, idle_duration=args.idle_duration))
                if cycle < args.cycles and not args.check_only:
                    await asyncio.sleep(3)
        finally:
            print(f"Saved {path}. No flash performed.", flush=True)
    if args.check_only:
        print("Read-only identity check complete; no raw start/stop or optical commands sent.")
        return 0 if results[0]["classification"] != "mixed_or_unknown" else 2
    passed = all(r["sample_checks_passed"] and r["tracking_state_passed"]
                 and r["producer_stopped"] and r["idle_observed"] for r in results)
    print("Measured checks passed." if passed else "Some measured checks failed or idle was not observed.")
    print("LED darkness needs visual confirmation. Abrupt disconnect, reboot and battery remain separate gates.")
    return 0 if passed else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="explicit ring address")
    parser.add_argument("--check-only", action="store_true", help="read code only; never start/stop sensors")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--idle-duration", type=float, default=15)
    args = parser.parse_args(argv)
    if (args.cycles < 1 or not math.isfinite(args.duration) or args.duration < 10
            or not math.isfinite(args.idle_duration) or args.idle_duration < 10):
        parser.error("cycles >=1 and finite duration/idle-duration >=10 seconds are required")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"Validation stopped: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
