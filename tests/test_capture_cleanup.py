import asyncio
from pathlib import Path

import pytest

from whip import capture, protocol


class FakeClient:
    """Model partial BLE writes and setup interruption without a radio."""

    def __init__(self, fail_on=None, pause_on=None, fail_notify=False):
        self.fail_on = fail_on
        self.pause_on = pause_on
        self.fail_notify = fail_notify
        self.paused = asyncio.Event()
        self.writes = []
        self.notify_stopped = False

    async def start_notify(self, _uuid, callback):
        self.callback = callback
        if self.fail_notify:
            raise RuntimeError("notification setup failed")

    async def write_gatt_char(self, _uuid, packet, response=False):
        packet = bytes(packet)
        self.writes.append(packet)
        if packet == protocol.ENABLE_RAW_SENSOR:
            self.callback(None, bytearray([0xA1, 0x03] + [0] * 14))
        if packet[:2] == self.fail_on:
            raise RuntimeError("injected write failure")
        if packet[:2] == self.pause_on:
            self.paused.set()
            await asyncio.Event().wait()

    async def stop_notify(self, _uuid):
        self.notify_stopped = True


@pytest.fixture
def sink(tmp_path, monkeypatch):
    path = tmp_path / "capture.jsonl"
    handles = []
    original_open = Path.open

    def track_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self == path and args == ("w",):
            handles.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", track_open)
    return path, handles


def assert_cleaned_up(client, sink, *, raw_started=True, motion_hold=False,
                      expected_records=1):
    path, handles = sink
    if raw_started:
        tail = [*protocol.STOP_RAW_SENSOR_PACKETS,
                *([protocol.MOTION_HOLD_DISABLE] if motion_hold else [])]
        assert client.writes[-len(tail):] == tail
        _, records = capture.load_capture(path)
        assert len(records) == expected_records
    else:
        assert client.writes == []
    assert client.notify_stopped
    assert len(handles) == 1 and handles[0].closed


def test_normal_stop_flushes_closes_and_joins_flusher(sink, monkeypatch):
    tasks = []
    original_create_task = asyncio.create_task

    def track_task(coro, *args, **kwargs):
        task = original_create_task(coro, *args, **kwargs)
        tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", track_task)
    client = FakeClient()

    async def run():
        records = await capture.stream(client, 0, sink=sink[0])
        assert len(records) == 1
        # Check before asyncio.run itself cancels pending background tasks.
        assert len(tasks) == 1 and tasks[0].done()

    asyncio.run(run())
    # Every connection opens by clearing a stale raw mode, then starts.
    stops = list(protocol.STOP_RAW_SENSOR_PACKETS)
    assert client.writes[: len(stops)] == stops
    assert client.writes[len(stops)] == protocol.ENABLE_RAW_SENSOR
    assert_cleaned_up(client, sink)


def test_rt12_motion_hold_is_bounded_by_raw_start_and_complete_cleanup(sink):
    client = FakeClient()
    asyncio.run(capture.stream(client, 0, sink=sink[0], motion_hold=True))
    writes = client.writes
    start = writes.index(protocol.ENABLE_RAW_SENSOR)
    assert writes[start + 1] == protocol.MOTION_HOLD_ENABLE
    assert writes[:start] == [*protocol.STOP_RAW_SENSOR_PACKETS,
                             protocol.MOTION_HOLD_DISABLE]
    assert_cleaned_up(client, sink, motion_hold=True)


def test_exact_v6_capture_renews_a1_04_before_lease_expiry(sink):
    client = FakeClient()
    rec = capture.Capture(
        device=capture.DeviceInfo("test", "COLMI R02_DE07",
                                  firmware="RT12COL_1.00.06_260927",
                                  hardware="RT12COL_V1.0"),
        started_wall=0.0, param=protocol.RAW_ENABLE_ALL, label="renewal-test",
    )
    asyncio.run(capture.stream(client, 0.025, sink=sink[0], capture=rec,
                               lease_renew_interval_s=0.01))
    assert client.writes.count(protocol.ENABLE_RAW_SENSOR) == 3
    assert rec.notes["gesture_lease_renewal_s"] == 0.01
    assert_cleaned_up(client, sink, expected_records=3)


def test_non_lease_firmware_does_not_repeat_a1_04(sink):
    client = FakeClient()
    rec = capture.Capture(
        device=capture.DeviceInfo("test", "COLMI R02_CC07",
                                  firmware="RT02CR_3.12.07_260514",
                                  hardware="RT02CR_V3.1"),
        started_wall=0.0, param=protocol.RAW_ENABLE_ALL, label="no-renewal-test",
    )
    asyncio.run(capture.stream(client, 0, sink=sink[0], capture=rec))
    assert client.writes.count(protocol.ENABLE_RAW_SENSOR) == 1
    assert "gesture_lease_renewal_s" not in rec.notes
    assert_cleaned_up(client, sink)


def test_rt12_hold_enable_failure_still_runs_both_stops_and_hold_release(sink):
    client = FakeClient(fail_on=b"\x3b\x02")
    with pytest.raises(RuntimeError, match="injected write failure"):
        asyncio.run(capture.stream(client, 0, sink=sink[0], motion_hold=True))
    assert_cleaned_up(client, sink, motion_hold=True)


@pytest.mark.parametrize("fail_on, options", [
    (b"\xa1\x04", {}),
    (b"\x16\x02", {"disable_logging": True}),
    (b"\x69\x06", {"quiet_optical": True}),
])
def test_setup_write_failure_still_stops_ring_and_saves_data(sink, fail_on, options):
    client = FakeClient(fail_on=fail_on)
    with pytest.raises(RuntimeError, match="injected write failure"):
        asyncio.run(capture.stream(client, 0, sink=sink[0], **options))
    assert_cleaned_up(client, sink)


def test_cancel_during_setup_still_stops_ring_and_saves_data(sink):
    client = FakeClient(pause_on=b"\x16\x02")

    async def run():
        task = asyncio.create_task(capture.stream(client, 60, sink=sink[0], disable_logging=True))
        await asyncio.wait_for(client.paused.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert_cleaned_up(client, sink)


@pytest.mark.parametrize("fail_on", [b"\xa1\x05", b"\xa1\x02"])
def test_one_stop_write_failure_does_not_skip_remaining_cleanup(sink, fail_on):
    client = FakeClient(fail_on=fail_on)
    asyncio.run(capture.stream(client, 0, sink=sink[0]))
    assert_cleaned_up(client, sink)


def test_subscription_failure_closes_notification_and_sink(sink):
    client = FakeClient(fail_notify=True)
    with pytest.raises(RuntimeError, match="notification setup failed"):
        asyncio.run(capture.stream(client, 0, sink=sink[0]))
    assert_cleaned_up(client, sink, raw_started=False)


def test_a_failed_pre_start_stop_does_not_abort_the_session(sink):
    """The ring may not answer the clearing stop; the start must still go out."""
    class FirstStopFails(FakeClient):
        def __init__(self):
            super().__init__()
            self.failed_once = False

        async def write_gatt_char(self, uuid, packet, response=False):
            if bytes(packet) == protocol.STOP_RAW_SENSOR and not self.failed_once:
                self.failed_once = True
                self.writes.append(bytes(packet))
                raise RuntimeError("injected pre-start failure")
            await super().write_gatt_char(uuid, packet, response)

    client = FirstStopFails()
    records = asyncio.run(capture.stream(client, 0, sink=sink[0]))
    assert len(records) == 1
    assert protocol.ENABLE_RAW_SENSOR in client.writes
    assert_cleaned_up(client, sink)


def test_valid_battery_reply_survives_corebluetooth_stop_notify_error():
    class StopNotifyFails(FakeClient):
        async def write_gatt_char(self, uuid, packet, response=False):
            await super().write_gatt_char(uuid, packet, response)
            if bytes(packet) == protocol.BATTERY_PACKET:
                self.callback(None, bytearray([protocol.CMD_BATTERY, 87, 0]))

        async def stop_notify(self, _uuid):
            self.notify_stopped = True
            raise RuntimeError("CBErrorUnknown")

    client = StopNotifyFails()
    assert asyncio.run(capture.read_battery(client)) == (87, False)
    assert client.notify_stopped
