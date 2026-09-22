"""Observe raw streaming and its matching stop without changing health settings.

    python -m probe.ledcheck
    python -m probe.ledcheck --duration 600 --cycles 2
    python -m probe.ledcheck --optical-stop --dark-duration 60
    python -m probe.ledcheck --optical-stop --read-sensors --dark-duration 60

The saved phases and packets establish delivery and stop behavior. LED darkness
must be observed on the ring; BLE packets cannot prove that the emitters are off.
The optional optical-stop experiment writes only VC30F register 0x7b = 0x00
through the firmware's CE diagnostic command. It leaves A1 streaming enabled.
It does not flash firmware or modify persistent health settings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from whip import capture, protocol


# Only these non-consuming diagnostic reads are allowed. Reading the STK FIFO
# data register would drain it and change the freshness we are measuring.
SENSOR_READS = (
    ("stk_chip_id", 0x1F, 0x00, 1),
    ("stk_xyz", 0x1F, 0x02, 6),
    ("stk_range_bw_power", 0x1F, 0x0F, 3),
    ("stk_fifo_status", 0x1F, 0x0C, 1),
    ("stk_interrupt_map", 0x1F, 0x1A, 1),
    ("vc30f_run", 0x33, 0x7B, 1),
)
RAM_READS = (("accel_state", 0x20BDC4, 12), ("accel_irq", 0x20BD94, 10),
             ("idle_counter", 0x20CC4C, 3), ("motion_control", 0x20BFC0, 3),
             ("connection_state", 0x209E09, 1))


def motion_control_packet(enabled: bool) -> bytearray:
    """Fixed volatile 3B submode 1, audited at file 0x5C44 / 0xD3BC.

    This enables action mode 3 of an existing motion feature, not a RAM write.
    Its event target 0x3E7A is a no-op in this image; action mode 1 could send
    host input events and must not be used for this experiment.
    In connected state it inhibits the inactivity decision and wakes the STK.
    It also enables a motion interrupt, so it is an experiment, not yet a
    production streaming default. Cleanup disables the feature again.
    """
    if type(enabled) is not bool:
        raise ValueError("motion control requires a boolean")
    return protocol.make_packet(0x3B, bytes([2, 1, 3 if enabled else 0]))


def optical_stop_packet() -> bytearray:
    """CE: write one STOP byte to VC30F (I2C 0x33), verified at file 0x49e2.

    The command fields are operation, device, register, length, data. Keep this
    fixed: the diagnostic handler accepts arbitrary addresses and lengths.
    Its reply echoes bytes and does not establish that the I2C write succeeded.
    """
    return protocol.make_packet(0xCE, bytes([0x02, 0x33, 0x7B, 0x01, 0x00]))


def sensor_read_packet(name: str) -> bytearray:
    """Build one of the fixed, at-most-six-byte CE01 diagnostic reads."""
    for label, device, register, length in SENSOR_READS:
        if name == label:
            return protocol.make_packet(0xCE, bytes([0x01, device, register, length]))
    raise ValueError(f"Unknown sensor read: {name}")


async def ce_exchange(client, replies: asyncio.Queue, packet: bytes | bytearray,
                      *, timeout: float = 3.0) -> tuple[float, bytes]:
    """Send exactly one CE request and consume its one reply before continuing.

    CE replies have no operation/register identity: even the CE02 write reply
    starts CE 00. Never proceed after a timeout, because its late reply could
    then be mistaken for a later CE01 read. An already queued reply is likewise
    ambiguous, so fail instead of clearing it and pretending correlation holds.
    """
    if not replies.empty():
        raise RuntimeError("Unexpected pending CE reply; diagnostic correlation lost")
    await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
    try:
        t, reply = await asyncio.wait_for(replies.get(), timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError("CE reply timed out; aborting diagnostics to avoid a stale reply") from exc
    if len(reply) != 16 or reply[0] != packet[0] or protocol.checksum(reply[:-1]) != reply[-1]:
        raise RuntimeError("Invalid diagnostic reply; aborting diagnostics")
    return t, reply


def accel_freshness(accel: list[tuple[float, bytes]], begin: float) -> dict:
    """Measure repeated payloads, separately from notification delivery rate."""
    if not accel:
        return {"max_identical_accel_s": None, "unchanged_accel_tail_s": None,
                "last_accel_change_t": None, "last_accel_change_phase_s": None}
    run_start, previous = accel[0][0], accel[0][1][2:8]
    longest = 0.0
    last_change = None
    for t, packet in accel[1:]:
        value = packet[2:8]
        if value != previous:
            run_start = t
            last_change = t
            previous = value
        longest = max(longest, t - run_start)
    return {"max_identical_accel_s": longest,
            "unchanged_accel_tail_s": accel[-1][0] - run_start,
            "last_accel_change_t": last_change,
            "last_accel_change_phase_s": last_change - begin if last_change is not None else None}


async def run(args: argparse.Namespace) -> int:
    device = await capture.find_ring(address=args.address, timeout=10)
    print(f"Found {device.name}: {device.address}", flush=True)
    async with capture.connected(device) as client:
        info = await capture.read_device_info(client, device)
        battery = await capture.read_battery(client)
        print(f"Hardware {info.hardware}, firmware {info.firmware}, battery {battery}", flush=True)
        if info.hardware != "RT02CR_V3.1":
            raise RuntimeError("Unexpected ring hardware; stopping before raw commands")
        if args.optical_stop and info.firmware != "RT02CR_3.12.07_260514":
            raise RuntimeError("Optical-stop experiment is verified only for the current 25 Hz firmware")
        if battery and battery[1]:
            raise RuntimeError("Take the ring off its charger before testing")

        out = Path("data/ledcheck")
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"check_{time.time_ns()}.jsonl"
        started = time.perf_counter()
        records: list[tuple[float, bytes]] = []
        ce_replies: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue()
        motion_replies: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue()
        motion_control_attempted = False
        phase = "idle"

        def on_notify(_sender, data):
            record = (time.perf_counter() - started, bytes(data))
            records.append(record)
            if record[1][:1] in (b"\xce", b"\xcd"):
                ce_replies.put_nowait(record)
            elif record[1][:1] == b"\x3b":
                motion_replies.put_nowait(record)

        with path.open("x") as log:
            log.write(json.dumps({"kind": "header", "device": info.as_dict(),
                                  "battery": battery, "started_wall": time.time()}) + "\n")
            log.flush()
            await client.start_notify(protocol.UART_TX_CHAR_UUID, on_notify)

            async def read_sensors(label: str, cycle: int):
                for name, device_address, register, length in SENSOR_READS:
                    request = sensor_read_packet(name)
                    t, reply = await ce_exchange(client, ce_replies, request)
                    result = {"kind": "sensor_read", "phase": phase, "cycle": cycle,
                              "snapshot": label, "name": name, "t": t,
                              "device_address": device_address, "register": register,
                              "length": length, "request": request.hex(), "reply": reply.hex()}
                    log.write(json.dumps(result) + "\n")
                    log.flush()
                    print(json.dumps(result), flush=True)
                for name, address, length in RAM_READS:
                    request = protocol.make_packet(0xCD, bytes([1, length]) + address.to_bytes(4, "big"))
                    t, reply = await ce_exchange(client, ce_replies, request)
                    result = {"kind": "ram_read", "phase": phase, "cycle": cycle,
                              "snapshot": label, "name": name, "t": t,
                              "address": hex(address), "length": length,
                              "request": request.hex(), "reply": reply.hex()}
                    log.write(json.dumps(result) + "\n")
                    log.flush()
                    print(json.dumps(result), flush=True)

            try:
                if args.keep_active:
                    # Refuse an already enabled feature or unfamiliar volatile
                    # state rather than replacing another client's settings.
                    request = protocol.make_packet(0xCD, bytes([1, 3]) + (0x20BFC0).to_bytes(4, "big"))
                    t, reply = await ce_exchange(client, ce_replies, request)
                    previous = reply[1:4]
                    log.write(json.dumps({"kind": "motion_control_preflight", "t": t,
                                          "reply": reply.hex()}) + "\n")
                    log.flush()
                    if previous != b"\0\1\0":
                        raise RuntimeError(f"Motion feature already enabled or non-default: {previous.hex()}")
                for cycle in range(1, args.cycles + 1):
                    phases = [("stopped_A105", protocol.raw_sensor_packet(0x05), args.stopped_duration)]
                    if args.optical_stop:
                        phases.insert(0, ("optical_stopped_streaming", optical_stop_packet(), args.dark_duration))
                    if args.keep_active:
                        phases.insert(0, ("motion_control_enabled", motion_control_packet(True), 5.0))
                    if not args.stop_only:
                        phases.insert(0, ("streaming", protocol.raw_sensor_packet(0x04), args.duration))
                    for phase, command, duration in phases:
                        index = len(records)
                        begin = time.perf_counter() - started
                        log.write(json.dumps({"kind": "phase", "phase": phase,
                                              "cycle": cycle, "t": begin,
                                              "command": command.hex()}) + "\n")
                        log.flush()
                        print(f"Cycle {cycle}: {phase}, sending {command[:6].hex(' ')}; "
                              f"watch LEDs for {duration:g}s", flush=True)
                        try:
                            if phase == "motion_control_enabled":
                                motion_control_attempted = True
                                t, reply = await ce_exchange(client, motion_replies, command)
                                if reply[1:4] != command[1:4]:
                                    raise RuntimeError("Unexpected motion-control echo")
                                log.write(json.dumps({"kind": "motion_control_ack", "t": t,
                                                      "reply": reply.hex()}) + "\n")
                                log.flush()
                            elif args.read_sensors and phase == "optical_stopped_streaming":
                                # CE02's echo must be consumed before any CE01 read.
                                t, reply = await ce_exchange(client, ce_replies, command)
                                log.write(json.dumps({"kind": "optical_stop_ack", "phase": phase,
                                                      "cycle": cycle, "t": t, "reply": reply.hex()}) + "\n")
                                log.flush()
                                await asyncio.sleep(max(0, begin + 5 - (time.perf_counter() - started)))
                                await read_sensors("five_seconds_after_optical_stop", cycle)
                            else:
                                await client.write_gatt_char(protocol.UART_RX_CHAR_UUID,
                                                             command, response=False)
                            await asyncio.sleep(max(0, begin + duration - (time.perf_counter() - started)))
                            if args.read_sensors and phase == "streaming":
                                await read_sensors("before_optical_stop", cycle)
                            if args.read_sensors and phase == "motion_control_enabled":
                                await read_sensors("after_motion_control_enable", cycle)
                            if args.read_sensors and phase == "optical_stopped_streaming":
                                await read_sensors("end_optical_stop_phase", cycle)
                        except (TimeoutError, RuntimeError) as exc:
                            log.write(json.dumps({"kind": "diagnostic_error", "phase": phase,
                                                  "cycle": cycle, "error": str(exc)}) + "\n")
                            for t, p in records[index:]:
                                log.write(json.dumps({"kind": "packet", "phase": phase,
                                                      "cycle": cycle, "t": t, "p": p.hex()}) + "\n")
                            log.flush()
                            raise
                        samples = records[index:]
                        accel = [(t, p) for t, p in samples if len(p) >= 8 and p[:2] == b"\xa1\x03"]
                        for t, p in samples:
                            log.write(json.dumps({"kind": "packet", "phase": phase,
                                                  "cycle": cycle, "t": t, "p": p.hex()}) + "\n")
                        # A few notifications may already be queued when STOP is sent.
                        late = sum(t - begin > 2 for t, _ in accel)
                        result = {"kind": "result", "phase": phase, "cycle": cycle,
                                  "accel_packets": len(accel), "packets_after_2s": late,
                                  "accel_hz": ((len(accel) - 1) / (accel[-1][0] - accel[0][0])
                                               if len(accel) > 1 and accel[-1][0] > accel[0][0] else None),
                                  "distinct_accel_values": len({p[2:8] for _, p in accel}),
                                  **accel_freshness(accel, begin),
                                  "led_observation": "requires human observation"}
                        log.write(json.dumps(result) + "\n")
                        log.flush()
                        print(json.dumps(result), flush=True)
            finally:
                for param in (0x05, 0x02):
                    try:
                        await client.write_gatt_char(protocol.UART_RX_CHAR_UUID,
                                                     protocol.raw_sensor_packet(param), response=False)
                        await asyncio.sleep(0.2)
                    except Exception as exc:
                        print(f"Cleanup A1 {param:02X}: {exc}", flush=True)
                if motion_control_attempted:
                    try:
                        # The preflight required mode=0, sensitivity=1, aux=0
                        # so this restores the same three volatile bytes.
                        await client.write_gatt_char(protocol.UART_RX_CHAR_UUID,
                                                     motion_control_packet(False), response=False)
                        await asyncio.sleep(0.5)
                        if args.read_sensors:
                            phase = "cleanup_motion_disabled"
                            await read_sensors("after_motion_control_disable", args.cycles)
                    except Exception as exc:
                        print(f"Cleanup motion control: {exc}", flush=True)
                try:
                    await client.stop_notify(protocol.UART_TX_CHAR_UUID)
                finally:
                    print(f"Saved {path}", flush=True)
    print("Disconnected; report whether LEDs were lit during streaming and after A1 05.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address")
    parser.add_argument("--duration", type=float, default=12)
    parser.add_argument("--stopped-duration", type=float, default=10)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--stop-only", action="store_true", help="send A1 05 without starting a stream")
    parser.add_argument("--optical-stop", action="store_true", help="test a fixed VC30F STOP while raw motion continues")
    parser.add_argument("--dark-duration", type=float, default=60, help="seconds to observe motion with optics stopped")
    parser.add_argument("--read-sensors", action="store_true",
                        help="read fixed sensor registers before and 5s after optical STOP; no FIFO data reads")
    parser.add_argument("--keep-active", action="store_true",
                        help="experimental volatile 3B motion control; requires optical-stop and read-sensors")
    args = parser.parse_args()
    if args.duration <= 0 or args.stopped_duration <= 2 or args.cycles < 1:
        parser.error("duration must be positive, stopped-duration > 2, cycles >= 1")
    if args.optical_stop and (args.stop_only or args.dark_duration <= 0):
        parser.error("--optical-stop needs streaming and a positive dark-duration")
    if args.read_sensors and (not args.optical_stop or args.dark_duration < 5):
        parser.error("--read-sensors needs --optical-stop and dark-duration >= 5")
    if args.keep_active and (not args.read_sensors or args.cycles != 1):
        parser.error("--keep-active needs --read-sensors and exactly one cycle")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
