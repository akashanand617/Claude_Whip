"""Aborted physical read: preserve its limits, never promote a partial capture."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from whip import fwrom_integration as ir, fwrom_read as rr, fwcapacity_read as cr, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/rom-integration-aborted"


def test_aborted_archive_prefix_is_exact_and_cannot_complete_or_retry():
    raw = (ARCHIVE / "transcript.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "765c09ae673b7b1e2e2839faae61ca722a50ff9ecb7ab53ccd83515c3537e636"
    rows = [json.loads(s) for s in raw.splitlines()]
    assert rows[0]["plan"] == "rom-integration-v1"
    assert rows[-1] == {"kind": "aborted", "error": "non-diagnostic traffic; abort idle read", "retry": False}
    assert not any(r["kind"] in ("completed", "disconnected", "rom_integration") for r in rows)
    assert not (ARCHIVE / "rom-integration.json").exists()
    transactions = [r for r in rows if r["kind"] in ("request", "reply")]
    assert len(transactions) == 377
    assert transactions[-1]["kind"] == "request" and transactions[-1]["address"] == 0x4F8E
    for request, reply in zip(transactions[:-1:2], transactions[1::2], strict=True):
        assert (request["kind"], reply["kind"]) == ("request", "reply")
        assert (request["address"], request["length"]) == (reply["address"], reply["length"])
        assert request["monotonic"] < reply["monotonic"]
        for row in (request, reply):
            packet = bytes.fromhex(row["packet"])
            assert len(packet) == 16 and packet[-1] == protocol.checksum(packet[:-1])
        packet = bytes.fromhex(request["packet"])
        assert packet[:2] == b"\xcd\x01" and packet[2] == request["length"]
        assert int.from_bytes(packet[3:7], "big") == request["address"]
    new = [r for r in transactions if r["kind"] == "reply" and 0x4A78 <= r["address"] < 0x53A4]
    assert sum(r["length"] for r in new) == 1302
    assert [(r["address"], r["length"]) for r in new] == list(cr.chunks(0x4A78, 1302))

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == transactions[self.index]["packet"]
            if self.index == len(transactions) - 1:
                # The original logger saved neither type nor payload. Inject
                # the recorded exception, NOT a made-up packet classification.
                self.reader.poisoned = True
                self.reader.pending.set_exception(RuntimeError(rows[-1]["error"]))
                self.index += 1
                return
            self.reader.notify(None, bytes.fromhex(transactions[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    client.reader = ir.IntegrationReader(client, lambda _: None, spacing=0)
    args = (client.reader, (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
            (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
            (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes(), "aborted-physical-replay")
    with pytest.raises(RuntimeError, match="non-diagnostic traffic"):
        asyncio.run(ir.collect(*args))
    assert client.index == 377 and client.reader.closed and client.reader.poisoned
    assert client.reader._code_phase is None
    with pytest.raises(RuntimeError, match="already used"):
        asyncio.run(ir.collect(*args))
    assert client.index == 377
