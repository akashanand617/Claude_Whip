"""Exact replay of the completed support read; never connects to hardware."""
import asyncio
import hashlib
import json
from pathlib import Path
import struct

from whip import fwrom_support as sr, fwcapacity_read as cr, fwrom_read as rr, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/rom-support"
HASHES = {
    "rom-support.json": "bcbffd1362964a186797e815fe15a17d4b66e0b1a8a54918cc09fd20d5cb874a",
    "transcript.jsonl": "05d72362a60f12dfab3958d9b3184d49523ba55d2ed9748b59e63b6b13111a05",
}


def test_all_284_recorded_requests_replay_exactly_without_expanding_authority():
    for name, digest in HASHES.items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest
    saved = json.loads((ARCHIVE / "rom-support.json").read_text())
    rows = [json.loads(s) for s in (ARCHIVE / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "rom-support-v1"
    assert rows[0]["max_transactions"] == sr.EXPECTED_TRANSACTIONS == 284
    assert not any(rows[0][k] for k in ("flashing", "sensor_commands", "target_execution", "pointer_following"))
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    assert rows[-1]["kind"] == "completed" and rows[-1]["requests"] == 284
    assert (rows[-1]["rom_bytes"], rows[-1]["new_rom_bytes"], rows[-1]["timer_state_snapshot_bytes"]) == (1150, 616, 17)
    assert not rows[-1]["flash_authorized"] and rows[-1]["capture_sha256"] == HASHES["rom-support.json"]
    assert not any(r["kind"] in ("aborted", "unexpected_notification") for r in rows)
    pairs = [r for r in rows if r["kind"] in ("request", "reply")]
    assert len(pairs) == 568
    addresses = []
    for request, reply in zip(pairs[::2], pairs[1::2], strict=True):
        assert (request["kind"], reply["kind"]) == ("request", "reply")
        assert (request["address"], request["length"]) == (reply["address"], reply["length"])
        assert request["monotonic"] < reply["monotonic"]
        for row in (request, reply):
            raw = bytes.fromhex(row["packet"])
            assert len(raw) == 16 and raw[-1] == protocol.checksum(raw[:-1])
        raw = bytes.fromhex(request["packet"])
        assert raw[:2] == b"\xcd\x01" and raw[2] == request["length"]
        assert int.from_bytes(raw[3:7], "big") == request["address"]
        addresses.append((request["address"], request["length"]))
    assert addresses[91:] == (list(cr.chunks(*rr.UUID_WINDOW)) * 2 +
        [c for _, a, n in sr.KNOWN_WINDOWS + sr.WINDOWS for c in cr.chunks(a, n) * 2] +
        [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert not any(a <= x < a + n for x, _ in addresses[:181] for _, a, n in sr.WINDOWS)
    # Snapshot points here, but there must be NO physical read of its target.
    assert not any(0x205C00 <= a < 0x205D00 for a, _ in addresses)

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == pairs[self.index]["packet"]
            self.reader.notify(None, bytes.fromhex(pairs[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    client.reader = sr.SupportReader(client, lambda _: None, spacing=0)
    actual = asyncio.run(sr.collect(client.reader,
        (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
        (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
        (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes(), saved["session_id"],
        (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes(),
        (ROOT / "firmware/research/2026-09-23/rom-timer-resume/rom-timer-resume-code.json").read_bytes(),
        (ROOT / "firmware/research/2026-09-23/rom-integration/rom-integration.json").read_bytes()))
    assert actual == saved and client.index == 568
    assert client.reader.closed and not client.reader.poisoned and not client.reader._allowed_reads()
    assert actual["schema"] == sr.SCHEMA and actual["evidence_kind"] == "device_capture"
    assert actual["repeated_equal"] and actual["known_code_repeated_equal"]
    assert not any(actual[k] for k in ("keys_read", "pointer_following", "target_execution",
        "timer_state_immutable", "physical_timing_verified", "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert set(actual["windows"]) == {name for name, _, _ in sr.WINDOWS}
    for name, start, length in sr.WINDOWS:
        w = actual["windows"][name]; data = bytes.fromhex(w["data_hex"])
        assert w["address"] == start and len(data) == length
        assert hashlib.sha256(data).hexdigest() == w["sha256"]
    values = {name: bytes.fromhex(w["data_hex"]) for name, w in actual["windows"].items()}
    assert values["timer_inhibit_snapshot"] == b"\0"
    assert struct.unpack("<I", values["timer_rate_config_snapshot"]) == (100,)
    assert struct.unpack("<III", values["create_start_restart_hook_snapshot"]) == (0x205C01, 0, 0)
