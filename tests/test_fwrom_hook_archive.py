"""Replay the completed fixed hook read; no hardware or invented replies."""
import asyncio
import hashlib
import json
from pathlib import Path

from whip import fwrom_hook as hr, fwrom_support as sr, fwrom_read as rr
from whip import fwcapacity_read as cr, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/rom-create-hook"
HASHES = {
    "rom-create-hook.json": "3836d4f94d260f5a4d45890d1d8670f47896e2bb03df8c78129ff53992c82b75",
    "transcript.jsonl": "ad0f07ad37de63e988653d5cd6faaab680b8593811e28cc6cf8cc37b84a5f5ce",
}


def test_all_359_recorded_transactions_replay_without_expanding_authority():
    for name, digest in HASHES.items():
        assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest
    saved = json.loads((ARCHIVE / "rom-create-hook.json").read_text())
    rows = [json.loads(s) for s in (ARCHIVE / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == "rom-create-hook-v1"
    assert rows[0]["max_transactions"] == hr.EXPECTED_TRANSACTIONS == 359
    assert not any(rows[0][k] for k in ("flashing", "sensor_commands", "target_execution", "pointer_following"))
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    end = rows[-1]
    assert end["kind"] == "completed" and end["requests"] == 359
    assert (end["rom_bytes"], end["new_rom_bytes"], end["new_ram_code_bytes"],
            end["nonsecret_patch_header_bytes"]) == (1282, 128, 256, 52)
    assert not end["flash_authorized"] and end["capture_sha256"] == HASHES["rom-create-hook.json"]
    assert not any(r["kind"] in ("aborted", "unexpected_notification") for r in rows)
    pairs = [r for r in rows if r["kind"] in ("request", "reply")]
    assert len(pairs) == 718
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
        [c for _, a, n in hr.KNOWN_WINDOWS + hr.NEW_WINDOWS for c in cr.chunks(a, n) * 2] +
        [c for _, a, n in sr.STATE_WINDOWS + (hr.PATCH_HEADER,) for c in cr.chunks(a, n)] +
        [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert not any(a <= x < a + n for x, _ in addresses[:279] for _, a, n in hr.NEW_WINDOWS)
    assert addresses[279:287] == list(cr.chunks(0x803000, 52)) * 2
    assert addresses[287] == (0x205C00, 14)
    new_union = {a + i for a, n in addresses if any(lo <= a < lo + length for _, lo, length in hr.NEW_WINDOWS)
                 for i in range(n)}
    assert len(new_union) == 436
    assert not any(0x803034 <= a < 0x803400 for a in new_union)

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == pairs[self.index]["packet"]
            self.reader.notify(None, bytes.fromhex(pairs[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    client.reader = hr.CreateHookReader(client, lambda _: None, spacing=0)
    actual = asyncio.run(hr.collect(client.reader,
        (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
        (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
        (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes(), saved["session_id"],
        (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes(),
        (ROOT / "firmware/research/2026-09-23/rom-timer-resume/rom-timer-resume-code.json").read_bytes(),
        (ROOT / "firmware/research/2026-09-23/rom-integration/rom-integration.json").read_bytes(),
        (ROOT / "firmware/research/2026-09-23/rom-support/rom-support.json").read_bytes()))
    assert actual == saved and client.index == 718
    assert client.reader.closed and not client.reader.poisoned and not client.reader._allowed_reads()
    assert actual["schema"] == hr.SCHEMA and actual["evidence_kind"] == "device_capture"
    assert all(actual[k] for k in ("repeated_equal", "known_code_state_repeated_equal", "final_state_header_equal"))
    assert not any(actual[k] for k in ("keys_read", "pointer_following", "target_execution", "runtime_copy_verified",
        "state_immutable", "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert set(actual["windows"]) == {name for name, _, _ in hr.NEW_WINDOWS}
    for name, start, length in hr.NEW_WINDOWS:
        w = actual["windows"][name]; data = bytes.fromhex(w["data_hex"])
        assert w["address"] == start and len(data) == length
        assert hashlib.sha256(data).hexdigest() == w["sha256"]
    h = actual["header_fields"]
    assert {k: h[k] for k in ("ic_type", "image_id", "control_flags", "payload_bytes", "declared_ram_start",
                             "declared_load_source", "declared_load_bytes", "declared_image_base")} == {
        "ic_type": 12, "image_id": 0x2792, "control_flags": 0x916, "payload_bytes": 0x9528,
        "declared_ram_start": 0x203800, "declared_load_source": 0x1809404,
        "declared_load_bytes": 0x3510, "declared_image_base": 0x1803000}
    assert h["containment_checked"] and not any(h[k] for k in (
        "authenticity_verified", "ram_ownership_verified", "runtime_copy_verified"))
