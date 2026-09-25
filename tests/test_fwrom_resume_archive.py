"""Replay the completed fixed timer-resume code read; never access a device."""
import asyncio
import hashlib
import json
from pathlib import Path
import struct

from whip import fwrom_resume as tr, fwrom_read as rr, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/rom-timer-resume"


def test_captured_resume_code_replays_all_180_transactions_without_widening_authority():
    hashes = {
        "rom-timer-resume-code.json": "b09002f65a8b1ff4dbe1ba0aea54c79e2043a4f0ebd0683921229a731ae74064",
        "transcript.jsonl": "7c09280e5ae252dbe3fdeee392268bc3fb6865b8f0e4a1964b993c0b8d1e5ddb",
    }
    for name, digest in hashes.items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest
    saved = json.loads((ARCHIVE / "rom-timer-resume-code.json").read_text())
    rows = [json.loads(s) for s in (ARCHIVE / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "rom-timer-resume-code-v1"
    assert rows[0]["max_transactions"] == tr.EXPECTED_TRANSACTIONS == 180
    assert not any(rows[0][k] for k in ("flashing", "sensor_commands", "target_execution", "pointer_following"))
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    assert rows[-1]["kind"] == "completed" and rows[-1]["requests"] == 180
    assert rows[-1]["rom_bytes"] == 524 and not rows[-1]["flash_authorized"]
    assert rows[-1]["capture_sha256"] == hashes["rom-timer-resume-code.json"]
    assert not any(r["kind"] in ("aborted", "unexpected_notification") for r in rows)
    pairs = [r for r in rows if r["kind"] in ("request", "reply")]
    assert len(pairs) == 360
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
    client.reader = tr.ResumeCodeReader(client, lambda _: None, spacing=0)
    actual = asyncio.run(tr.collect(client.reader,
        (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
        (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
        (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes(),
        saved["session_id"],
        (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes()))
    assert actual == saved and client.index == 360
    assert client.reader.closed and not client.reader.poisoned
    assert not client.reader._allowed_reads()
    assert actual["schema"] == tr.SCHEMA and actual["evidence_kind"] == "device_capture"
    assert actual["repeated_equal"] and actual["known_stop_repeated_equal"]
    assert actual["known_stop_code_sha256"] == rr.TIMER_CODE_SHA256
    assert not any(actual[k] for k in ("keys_read", "pointer_following", "target_execution",
                                       "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert set(actual["windows"]) == {name for name, _, _ in tr.WINDOWS}
    assert sum(len(bytes.fromhex(w["data_hex"])) for w in actual["windows"].values()) == 452
    for name, start, length in tr.WINDOWS:
        window = actual["windows"][name]
        raw = bytes.fromhex(window["data_hex"])
        assert window["address"] == start and len(raw) == length
        assert hashlib.sha256(raw).hexdigest() == window["sha256"]
    # These are captured ROM literals, not readings of the referenced hook slots.
    literals = bytes.fromhex(actual["windows"]["adjacent_timer_literals"]["data_hex"])
    assert struct.unpack("<III", literals) == (0x201644, 0x201648, 0x20164C)
    assert not any(0x201644 <= r["address"] < 0x201650 for r in pairs[::2])
