"""Replay saved descriptor replies through today's fixed reader, without BLE.

Hashes bind the archived evidence; replay is not independent device attestation.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from whip import fwcapacity_read as r, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/bank0-descriptor"


@pytest.mark.parametrize("name,digest", [
    ("configuration.json", "ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7"),
    ("report.json", "604fe44e0ac19b9e510abfd9d47a4dfa285ac23ca2c46dd169263f113aa51762"),
    ("transcript.jsonl", "9b98a908895249d2987ff675b7ebf340898f67437e3f2f5bc8e6f08a6d666043"),
])
def test_archived_artifact_hash(name, digest):
    assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest


def test_actual_91_transactions_replay_exact_fixed_plan_and_configuration():
    rows = [json.loads(line) for line in (ARCHIVE / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["bank0_descriptor_plan"] is True
    assert rows[-1]["kind"] == "completed" and not rows[-1]["flash_authorized"]
    pairs = [row for row in rows if row["kind"] in ("request", "reply")]
    assert len(pairs) == 182
    for request, reply in zip(pairs[::2], pairs[1::2], strict=True):
        assert (request["kind"], reply["kind"]) == ("request", "reply")
        assert (request["address"], request["length"]) == (reply["address"], reply["length"])
        assert request["monotonic"] < reply["monotonic"]
        for row in (request, reply):
            packet = bytes.fromhex(row["packet"])
            assert len(packet) == 16 and protocol.checksum(packet[:-1]) == packet[-1]
        assert bytes.fromhex(request["packet"])[:2] == b"\xcd\x01"

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == pairs[self.index]["packet"]
            self.reader.notify(None, bytes.fromhex(pairs[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    emitted = []
    client.reader = r.DescriptorReader(client, emitted.append, spacing=0)
    saved = json.loads((ARCHIVE / "configuration.json").read_text())
    observed = asyncio.run(r.collect_bank0_descriptor(
        client.reader, (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
        (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
        saved["session_id"]))
    assert observed == saved and client.index == 182
    assert not client.reader.poisoned and not client.reader._descriptor_phase
    assert sum(row["kind"] == "request" for row in emitted) == 91
