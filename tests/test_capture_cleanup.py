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


def assert_cleaned_up(client, sink, *, raw_started=True):
    path, handles = sink
    if raw_started:
        assert client.writes[-2:] == list(protocol.STOP_RAW_SENSOR_PACKETS)
        _, records = capture.load_capture(path)
        assert len(records) == 1
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
    assert client.writes[0] == protocol.ENABLE_RAW_SENSOR
    assert_cleaned_up(client, sink)


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
