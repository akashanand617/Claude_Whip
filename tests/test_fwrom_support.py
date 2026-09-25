"""Prepared support-code/config diagnostic: fake transport, NO ring access."""
import asyncio
import json
import struct

import pytest

from probe import rom_read
from tests import test_fwrom_read as rt
from tests.test_fwrom_read import BASE, V2, ROOT, SYMBOLS, ROMFake, arguments, transport
from whip import fwcapacity_read as cr, fwrom_read as rr, fwrom_support as sr
from whip.fwplacement import _bl_destination

STOP = (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes()
RESUME = (ROOT / "firmware/research/2026-09-23/rom-timer-resume/rom-timer-resume-code.json").read_bytes()
INTEGRATION = (ROOT / "firmware/research/2026-09-23/rom-integration/rom-integration.json").read_bytes()


def install(f):
    known = sr.validate_archives(STOP, RESUME, INTEGRATION)
    for name, address, _ in sr.KNOWN_WINDOWS:
        f.config[address] = known[name]
    for _, address, length in sr.WINDOWS:
        f.config[address] = bytes((address + i * 23) & 255 for i in range(length))


class SupportFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = sr.SupportReader(self, self.events.append, timeout=0.01, spacing=0)
        self.new_reads = 0
        self.mutation = self.fault = None
        self.injected = False
        install(self)

    def memory(self, address, length):
        raw = super().memory(address, length)
        if any(a <= address < a + n for _, a, n in sr.WINDOWS):
            self.new_reads += 1
        if self.mutation is not None:
            target, repeat = self.mutation
            if address == target and sum(a == target for a, _ in self.writes) == repeat:
                self.injected = True
                raw = bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    async def write_gatt_char(self, uuid, packet, response):
        if self.fault and self.reader._support_phase == self.fault[0]:
            self.bad = self.fault[1]
            self.injected = True
        await super().write_gatt_char(uuid, packet, response)


def collect(f, *, base=BASE, symbols=SYMBOLS, stop=STOP, resume=RESUME, integration=INTEGRATION):
    return asyncio.run(sr.collect(f.reader, base, V2, symbols, "fake-support-only", stop, resume, integration))


def test_fixed_windows_exact_order_and_budget_known_code_first_one_use_only():
    f = SupportFake()
    result = collect(f)
    assert sr.ROM_WINDOWS == (("arithmetic_helper_cap", 0x3F97A, 512),
        ("timer_context_and_literals", 0x14238, 28),
        ("flash_layout_literals", 0x8420, 40), ("ota_header_literals", 0x8CBC, 36))
    assert sr.STATE_WINDOWS == (("timer_inhibit_snapshot", 0x20037D, 1),
        ("timer_rate_config_snapshot", 0x200484, 4),
        ("create_start_restart_hook_snapshot", 0x201644, 12))
    assert (sr.TOTAL_ROM_BYTES, sr.TOTAL_STATE_BYTES, sr.TOTAL_KNOWN_BYTES) == (616, 17, 534)
    assert len(f.writes) == sr.EXPECTED_TRANSACTIONS == 284
    assert f.writes[91:] == (list(cr.chunks(*rr.UUID_WINDOW)) * 2 +
        [c for _, a, n in sr.KNOWN_WINDOWS + sr.WINDOWS for c in cr.chunks(a, n) * 2] +
        [c for w in cr.CONFIG_WINDOWS for c in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert len(f.writes[:181]) == 181
    assert not any((a, n) in {c for _, x, size in sr.WINDOWS for c in cr.chunks(x, size)}
                   for a, n in f.writes[:181])
    assert result["schema"] == sr.SCHEMA and result["known_code_repeated_equal"] and result["repeated_equal"]
    assert not any(result[k] for k in ("keys_read", "pointer_following", "target_execution",
        "timer_state_immutable", "physical_timing_verified", "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert sum(len(bytes.fromhex(w["data_hex"])) for w in result["windows"].values()) == 633
    assert f.reader.closed and not f.reader.poisoned and not f.reader._allowed_reads()
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == 284


def test_new_bounds_derive_from_fixed_previously_captured_callers_and_literals():
    saved = json.loads(RESUME)
    w = saved["windows"]["create_start_restart_backends"]
    raw, base = bytes.fromhex(w["data_hex"]), w["address"]
    assert _bl_destination(raw, 0x13FC4 - base) + base == 0x3F97A
    assert _bl_destination(raw, 0x1400A - base) + base == 0x14238
    def ldr_target(data, address):
        ins = struct.unpack_from("<H", data)[0]
        assert ins & 0xF800 == 0x4800
        return ((address + 4) & ~3) + (ins & 255) * 4
    for address, target in ((0x14050, 0x14248), (0x1406C, 0x1424C), (0x14074, 0x14250)):
        assert ldr_target(raw[address-base:], address) == target
    assert struct.unpack_from("<I", raw, 0x1402C-base)[0] + 0x19 == 0x20037D
    assert struct.unpack_from("<I", raw, 0x14030-base)[0] + 0x20 == 0x200484
    hooks = bytes.fromhex(saved["windows"]["adjacent_timer_literals"]["data_hex"])
    assert struct.unpack("<III", hooks) == (0x201644, 0x201648, 0x20164C)
    known = sr.validate_archives(STOP, RESUME, INTEGRATION)
    for name, address, _ in sr.CALLER_WITNESSES:
        assert ldr_target(known[name], address) == {
            "flash_first_ldr": 0x8420, "flash_last_ldr": 0x8444,
            "ota_first_ldr": 0x8CBC, "ota_last_ldr": 0x8CDC}[name]


def test_every_phase_excludes_other_phases_adjacent_bytes_keys_mmio_and_returned_addresses():
    f = SupportFake()
    for phase in [None, "identifier", *(n for n, _, _ in sr.KNOWN_WINDOWS + sr.WINDOWS)]:
        f.reader._support_phase = phase
        for name, address, length in sr.KNOWN_WINDOWS + sr.WINDOWS:
            if name != phase:
                for chunk in cr.chunks(address, length):
                    with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
        for address, length in ((0x3F978, 2), (0x3FB7A, 2), (0x14236, 2), (0x14254, 4),
            (0x20037C, 1), (0x20037E, 1), (0x200484, 8), (0x201644, 14), (0x201650, 4),
            (0x200414, 4), (0x80D034, 14), (0x40015000, 1), (0x1000198, 14), (True, 1)):
            with pytest.raises(ValueError): asyncio.run(f.reader.read(address, length))
    assert not f.writes
    f.reader._support_phase = None
    f.config[0x201644] = bytes.fromhex("005001401404200034d08000")
    result = collect(f)
    assert result["windows"]["create_start_restart_hook_snapshot"]["data_hex"] == f.config[0x201644].hex()
    assert not any(a in (0x40015000, 0x200414, 0x80D034) for a, _ in f.writes)


@pytest.mark.parametrize("name,address,length", sr.KNOWN_WINDOWS)
@pytest.mark.parametrize("repeat", [1, 2])
def test_every_known_witness_must_match_both_times_before_any_new_read(name, address, length, repeat):
    f = SupportFake(); f.mutation = address, repeat
    with pytest.raises(RuntimeError, match="known support prerequisite differs"):
        collect(f)
    assert f.injected and not f.new_reads and f.reader.poisoned and f.reader.closed


@pytest.mark.parametrize("name,address,length", sr.WINDOWS)
def test_every_new_code_or_state_repeat_change_aborts(name, address, length):
    f = SupportFake(); f.mutation = address, 2
    with pytest.raises(RuntimeError, match="changed across repeats"): collect(f)
    assert f.injected and f.new_reads and f.reader.closed and f.reader.poisoned
    assert f.reader._support_phase is None and not f.reader._descriptor_phase


@pytest.mark.parametrize("phase", [name for name, _, _ in sr.WINDOWS])
@pytest.mark.parametrize("fault", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_each_new_phase_transport_failure_terminates_without_retry(phase, fault):
    f = SupportFake(); f.fault = phase, fault
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    assert f.injected and f.reader.closed and f.reader.poisoned
    before = len(f.writes)
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == before < 284


@pytest.mark.parametrize("bad", ["base", "symbols", "stop", "resume", "integration",
    "identity", "diagnostic", "idle", "config", "descriptor", "uuid"])
def test_prerequisite_failure_prevents_new_support_windows(bad):
    f = SupportFake(); args = {}
    if bad in ("base", "symbols", "stop", "resume", "integration"):
        args[bad] = {"base": BASE, "symbols": SYMBOLS, "stop": STOP, "resume": RESUME, "integration": INTEGRATION}[bad] + b"\n"
    if bad in ("identity", "diagnostic"):
        offset = 0x21D6 if bad == "identity" else 0x564A
        f.image = V2[:offset] + bytes([V2[offset] ^ 1]) + V2[offset + 1:]
    if bad == "idle": f.raw = 4
    if bad in ("config", "descriptor", "uuid"):
        address = {"config": cr.CONFIG_WINDOWS[0][0], "descriptor": cr.BANK0_DESCRIPTOR_WINDOW[0], "uuid": rr.UUID_WINDOW[0]}[bad]
        f.config[address] = bytes([f.config[address][0] ^ 1]) + f.config[address][1:]
    with pytest.raises((ValueError, RuntimeError)): collect(f, **args)
    assert not f.new_reads and f.reader.closed and f.reader.poisoned
    if args: assert not f.writes


@pytest.mark.parametrize("address,repeat", [(cr.CONFIG_WINDOWS[0][0], 4), (cr.CONFIG_WINDOWS[1][0], 4), (cr.IDLE_WINDOW[0], 4)])
def test_changed_final_postcheck_cannot_create_success(address, repeat):
    f = SupportFake(); f.mutation = address, repeat
    with pytest.raises(RuntimeError): collect(f)
    assert f.injected and f.new_reads and f.reader.closed and f.reader.poisoned


@pytest.mark.parametrize("flag", ["boot_reference", "timer_hook_state", "timer_internals", "integration_code", "timer_resume_code"])
def test_cli_conflict_with_every_existing_plan_before_connection(transport, tmp_path, flag):
    args = arguments(tmp_path); args.support_code = True; setattr(args, flag, True)
    with pytest.raises(ValueError, match="exactly one"): asyncio.run(rom_read.run(args))
    assert not transport.connected and not args.output.exists()


@pytest.mark.parametrize("bad", [None, "confirmation", "device", "disconnect", "late_traffic"])
def test_cli_support_capture_requires_confirmation_exact_budget_and_disconnect(transport, tmp_path, bad):
    args = arguments(tmp_path); args.support_code = True
    install(transport)
    if bad == "confirmation": args.confirmed_idle_clients = False
    if bad == "device": transport.info["hardware"] = "other"
    if bad == "disconnect": transport.fail_disconnect = True
    if bad == "late_traffic": transport.late_traffic = True
    target = args.output / "rom-support.json"
    if bad:
        with pytest.raises((ValueError, RuntimeError)): asyncio.run(rom_read.run(args))
        assert not target.exists()
        if bad == "confirmation": assert not transport.connected and not args.output.exists()
        else:
            rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
            assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]
            assert rows[-1]["disconnect_confirmed"] is (bad != "disconnect")
            assert transport.disconnected
    else:
        assert asyncio.run(rom_read.run(args)) == 0 and target.exists()
        rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
        assert rows[0]["plan"] == "rom-support-v1" and rows[-1]["requests"] == 284
        assert rows[-2] == {"kind": "disconnected", "confirmed": True}
        assert (rows[-1]["new_rom_bytes"], rows[-1]["timer_state_snapshot_bytes"], rows[-1]["rom_bytes"]) == (616, 17, 1150)
        assert not rows[-1]["flash_authorized"] and transport.disconnected and not transport.is_connected


@pytest.mark.parametrize("window", sr.WINDOWS)
@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "v2"])
@pytest.mark.parametrize("state", [0, 2, 3])
def test_actual_cd_dispatch_only_copies_new_fixed_window_edges(window, image, state):
    _, address, length = window
    for start, size in set((cr.chunks(address, length)[0], cr.chunks(address, length)[-1])):
        rt.test_actual_cd_instructions_copy_fixed_low_rom_addresses_without_execution(image, state, start, size)
