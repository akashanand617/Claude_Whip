import asyncio
import io
import json
from pathlib import Path

import pytest

from probe import batterycheck as check
from probe.ledcheck import motion_control_packet, optical_stop_packet
from whip import fwidentity, fwoptical, protocol

BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"


def accel(value):
    return bytes(protocol.make_packet(0xA1, bytes([3]) + value.to_bytes(2, "big") + b"\0" * 4))


def test_fresh_rest_noise_passes_without_gesture_motion():
    records = [(i / 25, accel(i % 7)) for i in range(300)]
    result = check.stream_health(records, 0, 12)
    assert result["passed"] and result["hz"] == 25
    frozen = [(t, accel(1)) for t, _ in records]
    assert not check.stream_health(frozen, 0, 12)["passed"]
    assert not check.stream_health(records[::2], 0, 12)["passed"]
    assert not check.stream_health(records[:-40], 0, 12)["passed"]
    assert not check.stream_health([], 0, 12)["passed"]


def test_bad_checksum_and_malformed_acceleration_fail():
    records = [(i / 25, accel(i % 7)) for i in range(300)]
    records.append((10.1, b"\xa1\x03"))
    records.append((10.2, accel(1)[:-1] + b"\xff"))
    result = check.stream_health(sorted(records), 0, 12)
    assert result["invalid_packets"] == 2
    assert not result["passed"]


class Client:
    def __init__(self, *, image=None, levels=(90, 90, 89), charging=False,
                 motion=b"\0\1\0", frozen=False, active_flag=True,
                 fail_start=False, fail_first_stop=False, bad_ce=False):
        self.image = BASE.read_bytes() if image is None else image
        self.levels = list(levels)
        self.charging, self.motion, self.frozen = charging, motion, frozen
        self.active_flag = active_flag
        self.fail_start, self.fail_first_stop, self.bad_ce = fail_start, fail_first_stop, bad_ce
        self.writes = []
        self.active = False
        self.is_connected = True
        self.subscriptions = self.unsubscriptions = 0

    async def start_notify(self, _uuid, callback):
        self.subscriptions += 1
        self.callback = callback

    async def stop_notify(self, _uuid):
        self.unsubscriptions += 1

    async def write_gatt_char(self, _uuid, packet, response=False):
        packet = bytes(packet)
        self.writes.append(packet)
        if packet[0] == 0xCD:
            assert packet[1] == 1  # Never a memory write.
            length, address = packet[2], int.from_bytes(packet[3:7], "big")
            site = next((s for s in fwidentity.read_sites() if s.address == address), None)
            if site:
                assert length == site.length
                value = self.image[site.file_offset:site.file_offset + length]
            elif address == 0x20BFC0:
                assert length == 3
                value = self.motion
            else:
                assert address == 0x20BDC4 and length == 2
                value = bytes([1, int(self.active and self.active_flag)])
            self.callback(None, protocol.make_packet(0xCD, value))
        elif packet[0] == 0x03:
            level = self.levels.pop(0) if len(self.levels) > 1 else self.levels[0]
            self.callback(None, protocol.make_packet(0x03, bytes([level, int(self.charging)])))
        elif packet[0] == 0x3B:
            assert packet in (bytes(motion_control_packet(True)), bytes(motion_control_packet(False)))
            self.motion = bytes([packet[3], 1, 0])
            self.callback(None, packet)
        elif packet[0] == 0xCE:
            assert packet == bytes(optical_stop_packet())
            self.callback(None, protocol.make_packet(0xCE, b"\1" if self.bad_ce else b""))
        elif packet[:2] == b"\xa1\x04":
            self.active = True
            if self.fail_start:
                raise RuntimeError("start failed after write")
        elif packet[:2] in (b"\xa1\x05", b"\xa1\x02"):
            if self.fail_first_stop and packet[1] == 5:
                raise RuntimeError("first stop failed")
            self.active = False
        else:
            pytest.fail(f"unexpected command {packet.hex()}")


@pytest.fixture
def virtual_sampling(monkeypatch):
    monkeypatch.setattr(check.Session, "now", lambda self: getattr(self, "virtual_time", 0.0))

    async def pause(session, seconds):
        if not session.client.is_connected:
            raise RuntimeError("Ring disconnected")
        start = session.now()
        for i in range(round(seconds * 25)):
            session.virtual_time = start + (i + 1) / 25
            if session.client.active:
                value = 1 if session.client.frozen else round(session.now() * 25) % 7
                session.notify(None, accel(value))
        session.virtual_time = start + seconds
        session.flush()

    monkeypatch.setattr(check.Session, "pause", pause)


def exercise(client, **kwargs):
    log = io.StringIO()
    result = asyncio.run(check.exercise(client, log, BASE.read_bytes(), duration=20, **kwargs))
    return result, [json.loads(line) for line in log.getvalue().splitlines()]


def test_one_continuous_start_one_subscription_and_final_timed_battery(virtual_sampling):
    client = Client()
    result, events = exercise(client)
    assert result == "time_limit"
    assert client.subscriptions == client.unsubscriptions == 1
    assert sum(p[:2] == b"\xa1\x04" for p in client.writes) == 1
    assert sum(p == bytes(optical_stop_packet()) for p in client.writes) == 1
    assert [e["t"] for e in events if e["kind"] == "battery"] == [0, 5, 25]
    assert [e["percent"] for e in events if e["kind"] == "battery"] == [90, 90, 89]
    assert next(e for e in events if e["kind"] == "cleanup")["restoration"] == "verified_000100"
    packets = [e for e in events if e["kind"] == "packet" and e["p"].startswith("a103")]
    assert packets[0]["phase"] == "setup_raw_and_mode3"
    assert packets[-1]["phase"] == "optical_stop_mode3"
    assert all("wall" in e for e in packets)


def test_battery_floor_stops_early_without_restart(virtual_sampling):
    result, events = exercise(Client(levels=(90, 90, 40)), poll_seconds=5)
    assert result == "battery_floor"
    assert next(e for e in events if e["kind"] == "result")["elapsed_s"] == 5


@pytest.mark.parametrize("client, message", [
    (lambda: Client(charging=True), "Charging"),
    (lambda: Client(levels=(40,)), "safety floor"),
    (lambda: Client(motion=b"\1\1\0"), "000100"),
    (lambda: Client(image=fwoptical.build(BASE.read_bytes())), "original25Hz"),
])
def test_preflight_refuses_without_any_mutation(virtual_sampling, client, message):
    ring = client()
    with pytest.raises(RuntimeError, match=message):
        exercise(ring)
    assert all(p[0] in (0xCD, 0x03) for p in ring.writes)
    assert ring.unsubscriptions == 1


@pytest.mark.parametrize("options, message", [
    ({"frozen": True}, "freshness"),
    ({"active_flag": False}, "did not wake"),
    ({"bad_ce": True}, "STOP reply"),
])
def test_stream_failures_still_stop_and_disable(virtual_sampling, options, message):
    client = Client(**options)
    with pytest.raises(RuntimeError, match=message):
        exercise(client)
    assert all(bytes(p) in client.writes for p in protocol.STOP_RAW_SENSOR_PACKETS)
    assert bytes(motion_control_packet(False)) in client.writes
    assert client.motion == b"\0\1\0"
    assert client.unsubscriptions == 1


def test_cleanup_attempts_second_stop_and_restore_after_first_failure(virtual_sampling):
    client = Client(fail_first_stop=True)
    with pytest.raises(RuntimeError, match="Cleanup failed"):
        exercise(client)
    assert all(bytes(p) in client.writes for p in protocol.STOP_RAW_SENSOR_PACKETS)
    assert bytes(motion_control_packet(False)) in client.writes


def test_partial_start_failure_still_attempts_both_stops(virtual_sampling):
    client = Client(fail_start=True, fail_first_stop=True)
    with pytest.raises(RuntimeError, match="start failed"):
        exercise(client)
    assert all(bytes(p) in client.writes for p in protocol.STOP_RAW_SENSOR_PACKETS)


def test_timeout_poisoning_rejects_late_reply_and_all_further_reads():
    class Silent:
        def __init__(self):
            self.writes = []
        async def write_gatt_char(self, _uuid, packet, **kwargs):
            self.writes.append(packet)

    async def run():
        client = Silent()
        session = check.Session(client, io.StringIO())
        packet = fwidentity.read_packet(fwidentity.read_sites()[0])
        with pytest.raises(TimeoutError):
            await session.exchange(packet, timeout=0.001)
        session.notify(None, protocol.make_packet(0xCD))
        with pytest.raises(RuntimeError, match="correlation"):
            await session.read_ram("motion_control")
        assert len(client.writes) == 1
    asyncio.run(run())


def test_cancellation_attempts_all_cleanup_commands(virtual_sampling, monkeypatch):
    async def cancelled_pause(_self, _duration):
        raise asyncio.CancelledError()
    monkeypatch.setattr(check.Session, "pause", cancelled_pause)
    client = Client()
    with pytest.raises(asyncio.CancelledError):
        exercise(client)
    assert all(bytes(p) in client.writes for p in protocol.STOP_RAW_SENSOR_PACKETS)
    assert bytes(motion_control_packet(False)) in client.writes
    assert client.unsubscriptions == 1


@pytest.mark.parametrize("args", [
    ["--duration", "nan"], ["--duration", "inf"], ["--duration", "0"],
    ["--duration", "10801"], ["--poll-seconds", "nan"], ["--poll-seconds", "0"],
    ["--poll-seconds", "61"], ["--stop-at", "39"], ["--stop-at", "100"],
])
def test_invalid_cli_bounds_never_reach_ble(args):
    with pytest.raises(SystemExit) as error:
        check.main(["--address", "unused", *args])
    assert error.value.code == 2
