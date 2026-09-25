"""Prepared create-hook diagnostic, fake transport only; reference != ring."""
import asyncio
import hashlib
import json
import struct

import pytest

from probe import rom_read
from tests import test_fwrom_read as rt
from tests.test_fwrom_read import BASE, V2, ROOT, SYMBOLS, ROMFake, arguments, transport
from tests.test_fwrom_support import STOP, RESUME, INTEGRATION
from tests.test_fwrom_execution import CAPTURE
from whip import fwrom_hook as hr, fwrom_support as sr, fwcapacity_read as cr, fwrom_read as rr, fwcapacity, protocol
from whip.fwrom_execution import ROMHarness
from whip.fwplacement import _bl_destination

SUPPORT = (ROOT / "firmware/research/2026-09-23/rom-support/rom-support.json").read_bytes()
REFERENCE = ROOT / "firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-timer-hook.json"


def reference():
    raw = REFERENCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "a6798b4a0eabe1c3897a0a4f86eaef08e3b496fc9ed5c20198ff1add61a933b9"
    r = json.loads(raw)
    assert r["evidence_kind"] == "external_reference_not_ring_capture"
    for field in ("nonsecret_patch_header", "initializer_and_literals"):
        assert hashlib.sha256(bytes.fromhex(r[field]["data_hex"])).hexdigest() == r[field]["sha256"]
    return r


def install(f):
    known = hr.validate_archives(STOP, RESUME, INTEGRATION, SUPPORT)
    for name, address, _ in hr.KNOWN_WINDOWS:
        f.config[address] = known[name]
    # External header used ONLY as a synthetic admissible-header fixture.
    f.config[hr.PATCH_HEADER[1]] = bytes.fromhex(reference()["nonsecret_patch_header"]["data_hex"])
    for _, address, size in hr.CODE_WINDOWS:
        f.config[address] = bytes((address + i * 19) & 255 for i in range(size))


class HookFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = hr.CreateHookReader(self, self.events.append, timeout=0.01, spacing=0)
        self.mutation = self.fault = None
        self.injected = False
        install(self)

    def memory(self, address, length):
        data = super().memory(address, length)
        if self.mutation:
            target, repeat = self.mutation
            if address == target and sum(a == target for a, _ in self.writes) == repeat:
                self.injected = True
                data = bytes([data[0] ^ 1]) + data[1:]
        return data

    async def write_gatt_char(self, uuid, packet, response):
        if self.fault and self.reader._hook_phase == self.fault[0]:
            self.bad = self.fault[1]; self.injected = True
        await super().write_gatt_char(uuid, packet, response)


def collect(f, **changes):
    args = dict(base=BASE, candidate=V2, symbols=SYMBOLS, session_id="fake-hook-only",
                stop=STOP, resume=RESUME, integration=INTEGRATION, support=SUPPORT)
    args.update(changes)
    return asyncio.run(hr.collect(f.reader, **args))


def code_reads(f):
    return [(a, n) for a, n in f.writes if any(start <= a < start + size for _, start, size in hr.CODE_WINDOWS)]


def test_sdk_initializer_installs_different_create_hook_and_cannot_attest_ring():
    r = reference(); w = r["initializer_and_literals"]
    raw = bytes.fromhex(w["data_hex"])
    assert w["file_offset"] == 0x2912 and w["flash_storage_address"] == 0x803912
    assert w["code_length"] == 20 and len(raw) == 46
    h = ROMHarness(CAPTURE)
    h.uc.mem_map(0x803000, 0x1000, h.u.UC_PROT_READ | h.u.UC_PROT_EXEC)
    h.uc.mem_write(0x803912, raw)
    h.windows[0x803912] = raw; h.readable.append((0x803912, 0x803940))
    h.select(0x803912, 0x803926)
    for slot in (0x2015FC, 0x20173C, 0x201644): h.fixture(slot, bytes(4), writable=True)
    h.call(0x803912)
    assert h.writes == [(0x2015FC, 4, 0x206331), (0x20173C, 4, 0x20638D), (0x201644, 4, 0x206359)]
    observed = bytes.fromhex(json.loads(SUPPORT)["windows"]["create_start_restart_hook_snapshot"]["data_hex"])
    assert h.word(0x201644) != struct.unpack_from("<I", observed)[0] == 0x205C01
    assert not h.calls and not r["live_code_attested"] and not r["matches_live_create_hook"]
    assert not r["keys_retained"] and not r["authentication_fields_retained"] and not r["flash_authorized"]


def test_patch_header_and_declared_extent_do_not_become_code_or_ownership_proof():
    raw = bytes.fromhex(reference()["nonsecret_patch_header"]["data_hex"])
    result = hr.validate_patch_header(raw)
    assert result["declared_ram_start"] == 0x203800
    assert result["declared_load_source"] == 0x18099C4
    assert result["declared_load_bytes"] == 0x30B0
    assert result["image_id"] == 0x2792 and result["containment_checked"]
    assert not any(result[k] for k in ("authenticity_verified", "ram_ownership_verified", "runtime_copy_verified"))
    # Known caller pins the comparator entry; this is not guessed by proximity.
    call = hr.validate_archives(STOP, RESUME, INTEGRATION, SUPPORT)["header_compare_call"]
    assert _bl_destination(call, 0) + 0x8AC8 == 0x8E24


def test_fixed_order_all_known_reads_and_repeated_header_precede_new_code():
    f = HookFake(); result = collect(f)
    assert hr.NEW_WINDOWS == (("nonsecret_patch_header", 0x803000, 52),
        ("create_hook_ram_cap", 0x205C00, 256), ("header_compare_rom_cap", 0x8E24, 128))
    assert len(f.writes) == hr.EXPECTED_TRANSACTIONS == 359
    # Include the extra four-byte comparator BL witness, not just the prior
    # support plan's 1150-byte total. Check the byte union independently.
    rom_addresses = {a + i for _, a, n in hr.KNOWN_WINDOWS + hr.CODE_WINDOWS
                     if a < 0x200000 for i in range(n)}
    assert len(rom_addresses) == hr.TOTAL_ROM_BYTES == 1282
    assert f.writes[91:] == (list(cr.chunks(*rr.UUID_WINDOW)) * 2 +
        [c for _, a, n in hr.KNOWN_WINDOWS + hr.NEW_WINDOWS for c in cr.chunks(a, n) * 2] +
        [c for _, a, n in sr.STATE_WINDOWS + (hr.PATCH_HEADER,) for c in cr.chunks(a, n)] +
        [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert not any(a <= x < a + n for x, _ in f.writes[:279] for _, a, n in hr.NEW_WINDOWS)
    assert f.writes[279:287] == list(cr.chunks(0x803000, 52)) * 2
    assert f.writes[287] == (0x205C00, 14)
    assert result["schema"] == hr.SCHEMA and result["repeated_equal"] and result["final_state_header_equal"]
    assert result["known_code_state_repeated_equal"]
    assert not any(result[k] for k in ("keys_read", "pointer_following", "target_execution", "state_immutable",
        "runtime_copy_verified", "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert f.reader.closed and not f.reader.poisoned and not f.reader._allowed_reads()
    with pytest.raises(RuntimeError, match="already used"): collect(f)
    assert len(f.writes) == 359


@pytest.mark.parametrize("name,address,size", hr.KNOWN_WINDOWS)
@pytest.mark.parametrize("repeat", [1, 2])
def test_every_changed_known_code_or_state_aborts_before_new_header_or_code(name, address, size, repeat):
    f = HookFake(); f.mutation = address, repeat
    with pytest.raises(RuntimeError, match="prerequisite differs"): collect(f)
    assert f.injected and not code_reads(f) and not any(a == 0x803000 for a, _ in f.writes)
    assert f.reader.closed and f.reader.poisoned


@pytest.mark.parametrize("offset,fmt,value", [
    (0, "B", 5), (4, "H", 0x2793), (12, "I", 0),
    (2, "H", 0x0996), (2, "H", 0x0912), (2, "H", 0x2916),
    (8, "I", 0), (8, "I", 0x9C01), (8, "I", 0x30B0),
    (28, "I", 0x203804), (28, "I", 0xFFFFFFFF),
    (32, "I", 0x40015000), (32, "I", 0x200414), (32, "I", 0x803001),
    (32, "I", 0xFFFFFFFF), (32, "I", 0x180D000),
    (36, "I", 0), (36, "I", 0x24FC), (36, "I", 0x30B1), (36, "I", 0x4404),
    (40, "I", 0x80D000),
])
def test_unreviewed_header_refuses_both_fixed_code_caps(offset, fmt, value):
    f = HookFake(); raw = bytearray(f.config[0x803000]); struct.pack_into("<" + fmt, raw, offset, value)
    f.config[0x803000] = bytes(raw)
    with pytest.raises(RuntimeError): collect(f)
    assert not code_reads(f) and sum(a == 0x803000 for a, _ in f.writes) == 2
    assert f.reader.closed and f.reader.poisoned


@pytest.mark.parametrize("length", [0, 51, 53, 68])
def test_header_api_never_accepts_adjacent_key_bytes(length):
    with pytest.raises(ValueError): hr.validate_patch_header(bytes(length))


@pytest.mark.parametrize("name,address,size", hr.NEW_WINDOWS)
def test_new_code_or_header_repeat_mismatch_aborts(name, address, size):
    f = HookFake(); f.mutation = address, 2
    with pytest.raises(RuntimeError, match="changed across repeats"): collect(f)
    assert f.injected and f.reader.closed and f.reader.poisoned
    if address == 0x803000: assert not code_reads(f)


@pytest.mark.parametrize("phase", [n for n, _, _ in hr.NEW_WINDOWS])
@pytest.mark.parametrize("fault", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_new_phase_transport_failure_is_terminal(phase, fault):
    f = HookFake(); f.fault = phase, fault
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    assert f.injected and f.reader.closed and f.reader.poisoned and not f.reader._allowed_reads()
    before = len(f.writes)
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == before < 359


@pytest.mark.parametrize("name,address,size", sr.STATE_WINDOWS + (hr.PATCH_HEADER,))
def test_each_final_hook_config_header_recheck_can_abort_after_code(name, address, size):
    f = HookFake(); f.mutation = address, 3
    with pytest.raises(RuntimeError, match="postcheck changed"): collect(f)
    assert f.injected and code_reads(f) and f.reader.closed and f.reader.poisoned


@pytest.mark.parametrize("address", [cr.CONFIG_WINDOWS[0][0], cr.CONFIG_WINDOWS[1][0], cr.IDLE_WINDOW[0]])
def test_final_original_config_and_idle_checks_remain_required(address):
    f = HookFake(); f.mutation = address, 4
    with pytest.raises(RuntimeError): collect(f)
    assert f.injected and code_reads(f) and f.reader.closed and f.reader.poisoned


def test_phase_allowlists_reject_keys_adjacent_source_and_arbitrary_new_hook_targets():
    f = HookFake()
    for phase in [None, "identifier", *(n for n, _, _ in hr.KNOWN_WINDOWS + hr.NEW_WINDOWS)]:
        f.reader._hook_phase = phase
        for name, address, length in hr.NEW_WINDOWS:
            if phase != name:
                for chunk in cr.chunks(address, length):
                    with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
        for chunk in ((0x803034, 1), (0x803032, 4), (0x205BFE, 2), (0x205D00, 2),
                      (0x8E22, 2), (0x8EA4, 2), (0x8099C4, 14), (0x18099C4, 14),
                      (0x40015000, 1), (0x200414, 4), (0x206358, 14)):
            with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
    assert not f.writes
    f.reader._hook_phase = None
    f.config[0x201644] = struct.pack("<III", 0x40015001, 0, 0)
    with pytest.raises(RuntimeError, match="prerequisite differs"): collect(f)
    assert not code_reads(f) and not any(a == 0x40015000 for a, _ in f.writes)


@pytest.mark.parametrize("bad", ["base", "candidate", "symbols", "stop", "resume", "integration", "support"])
def test_local_reference_failure_prevents_any_transaction(bad):
    f = HookFake()
    raw = dict(base=BASE, candidate=V2, symbols=SYMBOLS, stop=STOP, resume=RESUME,
               integration=INTEGRATION, support=SUPPORT)[bad]
    with pytest.raises(ValueError): collect(f, **{bad: raw + b"\n"})
    assert not f.writes and f.reader.closed and f.reader.poisoned


@pytest.mark.parametrize("bad", ["identity", "diagnostic", "idle", "config", "descriptor", "uuid"])
def test_live_prerequisite_failure_stops_before_new_header(bad):
    f = HookFake()
    if bad in ("identity", "diagnostic"):
        offset = 0x21D6 if bad == "identity" else 0x564A
        f.image = V2[:offset] + bytes([V2[offset] ^ 1]) + V2[offset + 1:]
    if bad == "idle": f.raw = 4
    if bad in ("config", "descriptor", "uuid"):
        a = {"config": cr.CONFIG_WINDOWS[0][0], "descriptor": cr.BANK0_DESCRIPTOR_WINDOW[0], "uuid": rr.UUID_WINDOW[0]}[bad]
        f.config[a] = bytes([f.config[a][0] ^ 1]) + f.config[a][1:]
    with pytest.raises((ValueError, RuntimeError)): collect(f)
    assert not code_reads(f) and not any(a == 0x803000 for a, _ in f.writes)
    assert f.reader.closed and f.reader.poisoned


def test_cancellation_closes_all_phases_without_retry():
    class Cancelled(HookFake):
        async def write_gatt_char(self, uuid, packet, response):
            if self.reader._hook_phase == "create_hook_ram_cap":
                self.injected = True
                raise asyncio.CancelledError()
            await super().write_gatt_char(uuid, packet, response)
    f = Cancelled()
    with pytest.raises(asyncio.CancelledError): collect(f)
    assert f.injected and f.reader.closed and f.reader.poisoned
    assert f.reader._hook_phase is None and not f.reader._descriptor_phase and not f.reader._allowed_reads()


def check_header_copy(image, state, address, length):
    # Explicit synthetic read-only flash page: the earlier low-ROM fixture did
    # not map 0x803000. Do not mistake a fixture mapping for device accessibility.
    class FixedCopy(fwcapacity.CDReadHarness):
        def _code(self, uc, pc, size, user):
            if pc == 0x3F848:
                r0, r1, r2 = [uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0,
                    self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2)]
                assert (r0, r1, r2) == (self.STACK - 31, address, length)
                uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
                self._return(r0); return
            super()._code(uc, pc, size, user)
    h = FixedCopy(image)
    h.uc.mem_map(0x803000, 0x1000, h.u.UC_PROT_READ)
    expected = bytes((address + 17 * i) & 255 for i in range(length))
    h.uc.mem_write(address, expected)
    packet = bytes(protocol.make_packet(0xCD, bytes([1, length]) + address.to_bytes(4, "big")))
    h.uc.mem_write(h.PACKET, packet)
    h.uc.mem_write(0x20BBF0, bytes([state])); h.uc.mem_write(0x20A664, b"\0")
    h.uc.mem_write(h.STACK - 128, b"\xa5" * 128)
    h.uc.reg_write(h.a.UC_ARM_REG_R0, h.PACKET)
    h.uc.reg_write(h.a.UC_ARM_REG_SP, h.STACK)
    h.uc.reg_write(h.a.UC_ARM_REG_LR, h.STOP | 1)
    h.uc.emu_start((fwcapacity.BIAS + 0x564A) | 1, 0, count=1000)
    assert h.returned and h.reply == bytes(protocol.make_packet(0xCD, expected))
    assert h.uc.reg_read(h.a.UC_ARM_REG_SP) == h.STACK
    assert bytes(h.uc.mem_read(address, length)) == expected
    assert h.writes == [(0x20A664, 1)]
    assert h.calls == ([0x7ECA, 0x9276] if state in (2, 3) else [])


@pytest.mark.parametrize("flag", ["boot_reference", "timer_hook_state", "timer_internals", "integration_code", "timer_resume_code", "support_code"])
def test_cli_plan_conflicts_fail_before_connection(transport, tmp_path, flag):
    args = arguments(tmp_path); args.timer_create_hook = True; setattr(args, flag, True)
    with pytest.raises(ValueError, match="exactly one"): asyncio.run(rom_read.run(args))
    assert not transport.connected and not args.output.exists()


@pytest.mark.parametrize("bad", [None, "confirmation", "device", "disconnect", "late_traffic"])
def test_cli_new_capture_needs_exact_confirmation_identity_budget_disconnect(transport, tmp_path, bad):
    args = arguments(tmp_path); args.timer_create_hook = True; install(transport)
    if bad == "confirmation": args.confirmed_idle_clients = False
    if bad == "device": transport.info["hardware"] = "other"
    if bad == "disconnect": transport.fail_disconnect = True
    if bad == "late_traffic": transport.late_traffic = True
    target = args.output / "rom-create-hook.json"
    if bad:
        with pytest.raises((ValueError, RuntimeError)): asyncio.run(rom_read.run(args))
        assert not target.exists()
        if bad == "confirmation": assert not transport.connected and not args.output.exists()
        else:
            rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
            assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]
            assert rows[-1]["disconnect_confirmed"] is (bad != "disconnect")
    else:
        assert asyncio.run(rom_read.run(args)) == 0 and target.exists()
        rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
        assert rows[0]["plan"] == "rom-create-hook-v1" and rows[-1]["requests"] == 359
        assert rows[-2] == {"kind": "disconnected", "confirmed": True}
        assert (rows[-1]["new_rom_bytes"], rows[-1]["new_ram_code_bytes"], rows[-1]["nonsecret_patch_header_bytes"]) == (128, 256, 52)
        assert rows[-1]["rom_bytes"] == 1282 and not rows[-1]["flash_authorized"]


@pytest.mark.parametrize("window", hr.NEW_WINDOWS)
@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "v2"])
@pytest.mark.parametrize("state", [0, 2, 3])
def test_original_and_v2_cd_copy_only_fixed_new_window_edges(window, image, state):
    _, address, length = window
    for start, size in set((cr.chunks(address, length)[0], cr.chunks(address, length)[-1])):
        if address == 0x803000:
            check_header_copy(image, state, start, size)
        else:
            rt.test_actual_cd_instructions_copy_fixed_low_rom_addresses_without_execution(image, state, start, size)
