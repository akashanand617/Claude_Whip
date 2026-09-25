"""Exercise the hardware entry-point cleanup with a wholly fake BLE module."""
import asyncio
from contextlib import asynccontextmanager
import json
import sys
from types import SimpleNamespace

import pytest

import whip
from probe import capacity_read
from whip import protocol
from tests.test_fwcapacity_read import DescriptorFake


@pytest.fixture
def transport(monkeypatch):
    f = DescriptorFake()
    f.connected = f.disconnected = f.notifying = f.stopped_notify = False
    f.info = {"name": "R02_CC07", "hardware": "RT02CR_V3.1",
              "firmware": "RT02CR_3.12.07_260514", "address": "fake-device"}

    async def find_ring(*, address):
        assert address == "fake-device"
        return SimpleNamespace(name=f.info["name"])

    @asynccontextmanager
    async def connected(device):
        f.connected = True
        try:
            yield f
        finally:
            f.disconnected = True

    async def info(client, device):
        return SimpleNamespace(**f.info, as_dict=lambda: dict(f.info))

    async def start_notify(uuid, callback):
        assert uuid == protocol.UART_TX_CHAR_UUID
        f.reader = callback.__self__
        f.reader.spacing = 0  # Fake transport; detailed timing tests live separately.
        f.reader.timeout = 0.01
        f.notifying = True

    async def stop_notify(uuid):
        assert uuid == protocol.UART_TX_CHAR_UUID
        f.stopped_notify = True

    f.start_notify, f.stop_notify = start_notify, stop_notify
    fake_module = SimpleNamespace(find_ring=find_ring, connected=connected, read_device_info=info)
    monkeypatch.setitem(sys.modules, "whip.capture", fake_module)
    monkeypatch.setattr(whip, "capture", fake_module, raising=False)
    return f


def arguments(tmp_path, *, descriptor=True):
    return SimpleNamespace(address="fake-device", output=tmp_path / "new-capture",
                           bank0_descriptor=descriptor, confirmed_idle_clients=True)


@pytest.mark.parametrize("descriptor", [False, True])
def test_cli_fixed_plans_disconnect_and_preserve_output(transport, tmp_path, descriptor):
    args = arguments(tmp_path, descriptor=descriptor)
    assert asyncio.run(capacity_read.run(args)) == 0
    assert transport.disconnected and transport.stopped_notify
    data = json.loads((args.output / "configuration.json").read_text())
    report = json.loads((args.output / "report.json").read_text())
    assert len(data["windows"]) == (3 if descriptor else 2)
    assert not report["flash_authorized"] and not report["physical_evidence_verified"]
    records = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert records[0]["bank0_descriptor_plan"] is descriptor
    assert records[-1]["kind"] == "completed"
    assert records[-1]["descriptor_bytes"] == (80 if descriptor else 0)


def test_wrong_device_family_sends_no_diagnostic_commands(transport, tmp_path):
    transport.info["hardware"] = "different-hardware"
    with pytest.raises(RuntimeError, match="unexpected device"):
        asyncio.run(capacity_read.run(arguments(tmp_path)))
    assert transport.disconnected and not transport.notifying
    assert transport.writes == []


def test_transport_error_disconnects_without_retry_or_success_file(transport, tmp_path):
    transport.descriptor_fault = "checksum"
    args = arguments(tmp_path)
    with pytest.raises(RuntimeError, match="invalid diagnostic reply"):
        asyncio.run(capacity_read.run(args))
    assert transport.disconnected and transport.stopped_notify
    assert not (args.output / "report.json").exists()
    assert not (args.output / "configuration.json").exists()
    rows = [json.loads(line) for line in (args.output / "transcript.jsonl").read_text().splitlines()]
    assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]


def test_invalid_descriptor_saved_after_disconnect_but_never_approved(transport, tmp_path):
    transport.config[0x802198] = b"\xff" * 80
    args = arguments(tmp_path)
    assert asyncio.run(capacity_read.run(args)) == 2
    assert transport.disconnected and transport.stopped_notify
    data = json.loads((args.output / "configuration.json").read_text())
    assert data["windows"][-1]["data_hex"] == "ff" * 80
    assert not (args.output / "report.json").exists()


def test_existing_evidence_is_never_overwritten_or_connected(transport, tmp_path):
    args = arguments(tmp_path)
    args.output.mkdir()
    with pytest.raises(FileExistsError): asyncio.run(capacity_read.run(args))
    assert not transport.connected and transport.writes == []


def test_direct_entry_also_requires_idle_confirmation(transport, tmp_path):
    args = arguments(tmp_path)
    args.confirmed_idle_clients = False
    with pytest.raises(ValueError, match="confirmation"):
        asyncio.run(capacity_read.run(args))
    assert not transport.connected and transport.writes == []
    assert not args.output.exists()
