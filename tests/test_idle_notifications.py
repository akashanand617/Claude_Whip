"""Passive diagnostic, fake radio only; never a real device or UART write."""
import asyncio
import json

import pytest

from probe import idle_notifications as idle
from tests.test_fwrom_read import arguments, transport
from whip import protocol


@pytest.fixture
def passive(transport, monkeypatch):
    transport.packets = []

    async def start_notify(uuid, callback):
        assert uuid == protocol.UART_TX_CHAR_UUID
        transport.notifying = True
        for packet in transport.packets: callback(None, packet)

    async def forbidden_write(*args, **kwargs):
        pytest.fail("passive observation attempted a UART command")

    monkeypatch.setattr(idle, "OBSERVATION_SECONDS", 0.001)
    transport.start_notify = start_notify
    transport.write_gatt_char = forbidden_write
    return transport


@pytest.mark.parametrize("packet", [None, bytes(protocol.make_packet(0x03, b"private")),
                                  bytes(protocol.make_packet(0x16, b"private")),
                                  bytes(protocol.make_packet(0x73, b"\x12private"))])
def test_passive_capture_keeps_only_metadata_and_requires_disconnect(passive, tmp_path, packet):
    if packet is not None: passive.packets = [packet]
    args = arguments(tmp_path)
    assert asyncio.run(idle.run(args)) == 0
    assert passive.disconnected and passive.stopped_notify and not passive.is_connected
    raw = (args.output / "transcript.jsonl").read_text()
    assert "private" not in raw and "70726976617465" not in raw
    rows = [json.loads(s) for s in raw.splitlines()]
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    assert rows[-1]["uart_commands_sent"] == 0 and not rows[-1]["idle_proven"]
    assert rows[-1]["notifications"] == int(packet is not None)
    for row in rows:
        if row["kind"] == "notification_metadata":
            assert set(row) == {"kind", "command", "bytes", "checksum_valid", "status_subtype", "payload_saved", "monotonic"}
            assert row["status_subtype"] == (0x12 if packet[0] == 0x73 else None)


@pytest.mark.parametrize("bad", ["confirmation", "identity", "disconnect", "stream", "diagnostic", "empty",
                                "checksum", "budget"])
def test_passive_fault_closes_without_uart_cleanup_or_retry(passive, tmp_path, bad):
    args = arguments(tmp_path)
    if bad == "confirmation": args.confirmed_idle_clients = False
    elif bad == "identity": passive.info["hardware"] = "unknown"
    elif bad == "disconnect": passive.fail_disconnect = True
    elif bad == "stream": passive.packets = [bytes(protocol.make_packet(0xA1))]
    elif bad == "diagnostic": passive.packets = [bytes(protocol.make_packet(0xCD))]
    elif bad == "empty": passive.packets = [b""]
    elif bad == "checksum": passive.packets = [b"\x03" * 16]
    else: passive.packets = [bytes(protocol.make_packet(0x03))] * (idle.MAX_NOTIFICATIONS + 10)
    with pytest.raises((ValueError, RuntimeError)): asyncio.run(idle.run(args))
    if bad == "confirmation": assert not passive.connected
    else:
        assert passive.disconnected
        rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
        assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]
        assert rows[-1]["disconnect_confirmed"] is (bad != "disconnect")
        assert not any(r["kind"] == "completed" for r in rows)
        if bad == "budget": assert sum(r["kind"] == "notification_metadata" for r in rows) == idle.MAX_NOTIFICATIONS
