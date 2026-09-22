import asyncio
import io
from pathlib import Path

import pytest

from probe import validate_optical_off as validation
from whip import fwidentity, fwoptical, protocol

BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"


def accel(value):
    return bytes(protocol.make_packet(0xA1, bytes([3]) + (value * 16).to_bytes(2, "big") + b"\0" * 4))


def live_records(duration=10):
    return [(i / 25, accel(i)) for i in range(duration * 25)]


def test_fresh_stream_passes_but_frozen_packets_do_not():
    assert validation.stream_report(live_records(), 0, 10)["sample_checks_passed"]
    repeated = [(t, accel(1)) for t, _ in live_records()]
    report = validation.stream_report(repeated, 0, 10)
    assert report["hz"] == 25
    assert not report["sample_checks_passed"]


def test_late_start_and_early_stop_are_not_hidden_by_arrival_only_rate():
    assert not validation.stream_report(live_records()[100:], 0, 10)["sample_checks_passed"]
    assert not validation.stream_report(live_records()[:-100], 0, 10)["sample_checks_passed"]
    assert not validation.stream_report([], 0, 10)["sample_checks_passed"]


def test_corrupt_packets_fail_even_at_correct_rate():
    records = live_records()
    t, packet = records[100]
    records[100] = t, packet[:-1] + bytes([packet[-1] ^ 1])
    assert validation.stream_report(records, 0, 10)["invalid_checksums"] == 1
    assert not validation.stream_report(records, 0, 10)["sample_checks_passed"]


def test_malformed_extra_packet_and_two_value_replay_cannot_pass():
    records = live_records() + [(5.01, b"\xa1\x03\xff")]
    report = validation.stream_report(records, 0, 10)
    assert report["invalid_checksums"] == 1 and not report["sample_checks_passed"]
    replay = [(i / 25, accel(1000 * (i % 2))) for i in range(250)]
    report = validation.stream_report(replay, 0, 10)
    assert report["motion_observed"] and not report["sample_checks_passed"]


class Client:
    def __init__(self, image, fail_start=False, fail_stop=False, inactive_tracking=False,
                 late_stop_notification=False):
        self.image = image
        self.writes = []
        self.active = False
        self.fail_start, self.fail_stop = fail_start, fail_stop
        self.notify_stopped = False
        self.inactive_tracking = inactive_tracking
        self.late_stop_notification = late_stop_notification
        self.ever_started = False

    async def start_notify(self, _uuid, callback):
        self.callback = callback

    async def stop_notify(self, _uuid):
        self.notify_stopped = True

    async def write_gatt_char(self, _uuid, packet, response=False):
        packet = bytes(packet)
        self.writes.append(packet)
        if packet[0] == 0xCD:
            assert packet[1] == 1
            length = packet[2]
            address = int.from_bytes(packet[3:7], "big")
            site = next((s for s in fwidentity.read_sites() if s.address == address), None)
            if site:
                assert length == site.length
                payload = self.image[site.file_offset:site.file_offset + length]
            else:
                states = {0x209CAC: bytes([4 if self.active else 0]),
                          0x20BDC4: bytes([1, int(self.active and not self.inactive_tracking)]) + b"\0" * 10,
                          0x20CC4C: b"\0\0\x7d", 0x209E09: b"\2"}
                payload = states[address]
                assert len(payload) == length
            self.callback(None, protocol.make_packet(0xCD, payload))
            if (self.late_stop_notification and address == 0x209E09
                    and self.ever_started and not self.active):
                self.callback(None, accel(500))
        elif packet[:2] == b"\xa1\x04":
            self.active = True
            self.ever_started = True
            if self.fail_start:
                raise RuntimeError("start failed after reaching device")
        elif packet[:2] in (b"\xa1\x05", b"\xa1\x02"):
            if self.fail_stop and packet[1] == 5:
                raise RuntimeError("first stop failed")
            self.active = False
        else:
            pytest.fail(f"unexpected write: {packet.hex()}")


def test_check_only_sends_nothing_but_fixed_readonly_requests():
    base = BASE.read_bytes()
    client = Client(base)
    result = asyncio.run(validation.exercise(client, io.StringIO(), base, check_only=True))
    assert result["classification"] == "original25Hz"
    assert client.writes == [fwidentity.read_packet(s) for s in fwidentity.read_sites()]
    assert client.notify_stopped


def test_original_image_refuses_start_without_sending_cleanup_writes():
    base = BASE.read_bytes()
    client = Client(base)
    with pytest.raises(RuntimeError, match="no start sent"):
        asyncio.run(validation.exercise(client, io.StringIO(), base))
    assert all(packet[:2] == b"\xcd\x01" for packet in client.writes)
    assert client.notify_stopped


def test_setup_failure_attempts_both_raw_stops():
    base = BASE.read_bytes()
    client = Client(fwoptical.build(base), fail_start=True, fail_stop=True)
    with pytest.raises(RuntimeError, match="start failed"):
        asyncio.run(validation.exercise(client, io.StringIO(), base))
    assert client.writes[-2:] == [bytes(p) for p in protocol.STOP_RAW_SENSOR_PACKETS]
    assert client.notify_stopped
    assert not client.active


@pytest.fixture
def virtual_sampling(monkeypatch):
    monkeypatch.setattr(validation.Session, "now", lambda self: getattr(self, "virtual_time", 0.0))

    async def observe(session, duration):
        start = session.now()
        if session.client.active:
            session.records.extend((start + t, p) for t, p in live_records(int(duration)))
        session.virtual_time = start + duration
        session.flush()

    monkeypatch.setattr(validation.Session, "observe", observe)


def test_candidate_cycle_uses_no_optical_or_keepawake_workaround(virtual_sampling):
    base = BASE.read_bytes()
    client = Client(fwoptical.build(base))
    result = asyncio.run(validation.exercise(client, io.StringIO(), base, duration=10, idle_duration=10))
    assert result["sample_checks_passed"] and result["tracking_state_passed"]
    assert result["producer_stopped"] and result["idle_observed"]
    assert not any(p[0] in (0xCE, 0x3B) for p in client.writes)
    assert client.notify_stopped


def test_cached_fifo_state_cannot_pass_even_when_packet_metrics_pass(virtual_sampling):
    base = BASE.read_bytes()
    client = Client(fwoptical.build(base), inactive_tracking=True)
    result = asyncio.run(validation.exercise(client, io.StringIO(), base, duration=10, idle_duration=10))
    assert result["sample_checks_passed"]
    assert not result["tracking_state_passed"]


def test_packets_arriving_during_stop_state_reads_are_included(virtual_sampling):
    base = BASE.read_bytes()
    client = Client(fwoptical.build(base), late_stop_notification=True)
    result = asyncio.run(validation.exercise(client, io.StringIO(), base, duration=10, idle_duration=10))
    assert not result["producer_stopped"]


def test_diagnostic_timeout_poisoning_prevents_stale_reply_reuse():
    class Silent:
        def __init__(self):
            self.writes = []
        async def write_gatt_char(self, _uuid, packet, **kwargs):
            self.writes.append(packet)

    async def run():
        client = Silent()
        session = validation.Session(client, io.StringIO(), 1)
        packet = fwidentity.read_packet(fwidentity.read_sites()[0])
        with pytest.raises(TimeoutError):
            await session.read(packet, timeout=0.001)
        session.replies.put_nowait(bytes(protocol.make_packet(0xCD)))
        with pytest.raises(RuntimeError, match="correlation"):
            await session.read(packet)
        assert len(client.writes) == 1
    asyncio.run(run())


@pytest.mark.parametrize("args", [["--duration", "nan"], ["--idle-duration", "inf"], ["--cycles", "0"]])
def test_cli_refuses_invalid_durations_before_ble(args):
    with pytest.raises(SystemExit) as error:
        validation.main(["--address", "unused", *args])
    assert error.value.code == 2
