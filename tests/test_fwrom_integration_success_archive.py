"""Replay the successful separately coordinated ROM read; no device access."""
import asyncio
import hashlib
import json
from pathlib import Path

from whip import fwrom_integration as ir, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/rom-integration"


def test_success_archive_replays_all_974_transactions_and_preserves_evidence_limits():
    hashes = {
        "rom-integration.json": "d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b",
        "transcript.jsonl": "22d85dc403dda89e6bc6cfea605200d05d8201521d58b0ae83ee597235e39f8f",
    }
    for name, expected in hashes.items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == expected
    saved = json.loads((ARCHIVE / "rom-integration.json").read_text())
    rows = [json.loads(s) for s in (ARCHIVE / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "rom-integration-v1"
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    assert rows[-1]["kind"] == "completed" and rows[-1]["requests"] == 974
    assert rows[-1]["capture_sha256"] == hashes["rom-integration.json"]
    assert not any(r["kind"] in ("aborted", "unexpected_notification") for r in rows)
    pairs = [r for r in rows if r["kind"] in ("request", "reply")]
    assert len(pairs) == 1948
    for request, reply in zip(pairs[::2], pairs[1::2], strict=True):
        assert (request["kind"], reply["kind"]) == ("request", "reply")
        assert (request["address"], request["length"]) == (reply["address"], reply["length"])
        assert request["monotonic"] < reply["monotonic"]
        for row in (request, reply):
            packet = bytes.fromhex(row["packet"])
            assert len(packet) == 16 and packet[-1] == protocol.checksum(packet[:-1])
        packet = bytes.fromhex(request["packet"])
        assert packet[:2] == b"\xcd\x01" and packet[2] == request["length"]
        assert int.from_bytes(packet[3:7], "big") == request["address"]

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == pairs[self.index]["packet"]
            self.reader.notify(None, bytes.fromhex(pairs[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    client.reader = ir.IntegrationReader(client, lambda _: None, spacing=0)
    actual = asyncio.run(ir.collect(client.reader,
        (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
        (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
        (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes(), saved["session_id"]))
    assert actual == saved and client.index == 1948
    assert client.reader.closed and not client.reader.poisoned
    assert actual["repeated_equal"] and not actual["full_image_attestation"]
    assert not actual["recovery_verified"] and not actual["flash_authorized"]
    assert sum(len(bytes.fromhex(w["data_hex"])) for w in actual["windows"].values()) == 6076
    for name, start, length in ir.WINDOWS:
        window = actual["windows"][name]
        data = bytes.fromhex(window["data_hex"])
        assert window["address"] == start and len(data) == length
        assert hashlib.sha256(data).hexdigest() == window["sha256"]
    earlier = ROOT / "firmware/research/2026-09-23/rom-integration-aborted/transcript.jsonl"
    prior = [json.loads(s) for s in earlier.read_text().splitlines()]
    prefix = b"".join(bytes.fromhex(r["packet"])[1:1 + r["length"]] for r in prior
                      if r["kind"] == "reply" and 0x4A78 <= r["address"] < 0x53A4)
    assert len(prefix) == 1302 and bytes.fromhex(actual["windows"]["ram_boot"]["data_hex"]).startswith(prefix)
