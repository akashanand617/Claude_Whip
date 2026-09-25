"""Preflight for a NOT-YET-RUN fixed code read; all transport here is fake."""
import asyncio
import json

import pytest

from probe import rom_read
from tests import test_fwrom_read as rt
from tests.test_fwrom_read import BASE, V2, SYMBOLS, ROMFake, arguments, transport, ROOT
from whip import fwrom_resume as tr, fwcapacity_read as cr, fwrom_read as rr

PRIOR = (ROOT / "firmware/research/2026-09-23/rom-timers/rom-timers.json").read_bytes()


class ResumeFake(ROMFake):
    def __init__(self):
        super().__init__()
        self.reader = tr.ResumeCodeReader(self, self.events.append, timeout=0.01, spacing=0)
        self.code_reads = 0
        self.fault = self.code_change = None
        self.injected_fault = False
        self.config[rr.TIMER_WINDOW[0]] = rr.validate_prior_capture(PRIOR)
        for _, address, length in tr.WINDOWS:
            self.config[address] = bytes((address + i * 19) & 255 for i in range(length))

    def memory(self, address, length):
        raw = super().memory(address, length)
        if self.code_change == "known_stop_repeat" and address == rr.TIMER_WINDOW[0]:
            if sum(a == address for a, _ in self.writes) == 2:
                return bytes([raw[0] ^ 1]) + raw[1:]
        for name, start, size in tr.WINDOWS:
            if start <= address < start + size:
                self.code_reads += 1
                if self.code_change == name and address == start:
                    if sum(a == start for a, _ in self.writes) == 2:
                        return bytes([raw[0] ^ 1]) + raw[1:]
        if self.code_reads and self.code_change == "idle_after" and address == cr.IDLE_WINDOW[0]:
            return b"\x04"
        if self.code_reads and self.code_change == "config_after" and address == cr.CONFIG_WINDOWS[0][0]:
            return bytes([raw[0] ^ 1]) + raw[1:]
        return raw

    async def write_gatt_char(self, uuid, packet, response):
        if self.fault and self.reader._code_phase == self.fault[0]:
            self.bad = self.fault[1]
            self.injected_fault = True
        await super().write_gatt_char(uuid, packet, response)


def collect(fake, *, symbols=SYMBOLS, prior=PRIOR):
    return asyncio.run(tr.collect(fake.reader, BASE, V2, symbols, "fake-only", prior))


def test_fixed_three_windows_budget_order_postchecks_and_no_reuse():
    f = ResumeFake()
    result = collect(f)
    assert tr.WINDOWS == (
        ("create_start_restart_wrappers", 0x13634, 136),
        ("adjacent_timer_literals", 0x137EC, 12),
        ("create_start_restart_backends", 0x13F9E, 304),
    )
    assert tr.TOTAL_NEW_BYTES == 452 and tr.EXPECTED_TRANSACTIONS == 180
    assert len(f.writes) == 180
    assert f.writes[91:] == (list(cr.chunks(*rr.UUID_WINDOW)) * 2 +
        list(cr.chunks(*rr.TIMER_WINDOW)) * 2 +
        [chunk for _, a, n in tr.WINDOWS for chunk in cr.chunks(a, n) * 2] +
        [chunk for w in cr.CONFIG_WINDOWS for chunk in cr.chunks(*w)] + [cr.IDLE_WINDOW])
    assert sum(len(bytes.fromhex(w["data_hex"])) for w in result["windows"].values()) == 452
    assert result["schema"] == tr.SCHEMA and result["known_stop_repeated_equal"] and result["repeated_equal"]
    assert result["known_stop_code_sha256"] == rr.TIMER_CODE_SHA256
    assert not any(result[k] for k in ("keys_read", "pointer_following", "target_execution",
                                      "full_image_attestation", "recovery_verified", "flash_authorized"))
    assert f.reader.closed and not f.reader.poisoned
    with pytest.raises(RuntimeError): collect(f)
    with pytest.raises(ValueError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
    assert len(f.writes) == 180


def test_only_explicit_phase_chunks_are_admitted_and_returned_pointers_are_not_followed():
    f = ResumeFake()
    for phase in [None, "identifier", "known_stop", *(name for name, _, _ in tr.WINDOWS)]:
        f.reader._code_phase = phase
        for name, start, length in tr.WINDOWS:
            if phase == name: continue
            for chunk in cr.chunks(start, length):
                with pytest.raises(ValueError): asyncio.run(f.reader.read(*chunk))
        for address, length in ((0, 14), (0x13632, 2), (0x137E8, 4), (0x137F8, 8),
                                (0x13F9C, 2), (0x140CE, 14), (0x201644, 12),
                                (0x200414, 4), (0x40015000, 1), (0x80D034, 14)):
            with pytest.raises(ValueError): asyncio.run(f.reader.read(address, length))
    assert not f.writes
    f.reader._code_phase = None
    f.config[0x137EC] = bytes.fromhex("005001404416200014042000")
    result = collect(f)
    assert result["windows"]["adjacent_timer_literals"]["data_hex"] == "005001404416200014042000"
    assert all(a not in (0x40015000, 0x201644, 0x200414) for a, _ in f.writes)


@pytest.mark.parametrize("bad", ["symbols", "prior", "identity", "diagnostic", "base", "idle",
                                  "config", "descriptor", "uuid", "known_stop"])
def test_any_prerequisite_failure_prevents_all_new_timer_reads(bad):
    f = ResumeFake()
    if bad == "base": f.image = BASE
    if bad in ("identity", "diagnostic"):
        offset = 0x21D6 if bad == "identity" else 0x564A
        f.image = V2[:offset] + bytes([V2[offset] ^ 1]) + V2[offset + 1:]
    if bad == "idle": f.raw = 4
    if bad in ("config", "descriptor", "uuid", "known_stop"):
        address = {"config": cr.CONFIG_WINDOWS[0][0], "descriptor": cr.BANK0_DESCRIPTOR_WINDOW[0],
                   "uuid": rr.UUID_WINDOW[0], "known_stop": rr.TIMER_WINDOW[0]}[bad]
        raw = f.config[address]
        f.config[address] = bytes([raw[0] ^ 1]) + raw[1:]
    with pytest.raises((ValueError, RuntimeError)):
        collect(f, symbols=SYMBOLS + b"\n" if bad == "symbols" else SYMBOLS,
                prior=PRIOR + b"\n" if bad == "prior" else PRIOR)
    assert not f.code_reads and f.reader.closed and f.reader.poisoned
    if bad in ("symbols", "prior"): assert not f.writes


@pytest.mark.parametrize("phase", ["known_stop", *(name for name, _, _ in tr.WINDOWS)])
@pytest.mark.parametrize("fault", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_every_phase_fault_is_terminal_without_retry(phase, fault):
    f = ResumeFake()
    f.fault = phase, fault
    with pytest.raises((RuntimeError, TimeoutError)): collect(f)
    before = len(f.writes)
    assert f.reader.closed and f.reader.poisoned and f.reader._code_phase is None
    assert f.injected_fault  # don't let an unrelated prerequisite abort pass this test
    with pytest.raises(RuntimeError): collect(f)
    assert len(f.writes) == before < 180


@pytest.mark.parametrize("change", [*(name for name, _, _ in tr.WINDOWS), "config_after", "idle_after"])
def test_changed_repeat_or_postcheck_does_not_create_success(change):
    f = ResumeFake()
    f.code_change = change
    with pytest.raises(RuntimeError): collect(f)
    assert f.reader.closed and f.reader.poisoned and len(f.writes) <= 180
    assert f.code_reads > 0


def test_known_stop_must_match_on_its_second_read_before_any_new_window():
    f = ResumeFake()
    f.code_change = "known_stop_repeat"
    with pytest.raises(RuntimeError, match="known timer stop code differs"):
        collect(f)
    assert not f.code_reads and f.reader.closed and f.reader.poisoned


@pytest.mark.parametrize("flag", ["boot_reference", "timer_hook_state", "timer_internals", "integration_code"])
def test_resume_code_conflicts_with_every_other_plan_before_connect(transport, tmp_path, flag):
    args = arguments(tmp_path)
    args.timer_resume_code = True
    setattr(args, flag, True)
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(rom_read.run(args))
    assert not transport.connected and not args.output.exists()


@pytest.mark.parametrize("failure", [None, "confirmation", "conflict", "device", "disconnect", "late_traffic"])
def test_cli_confirmation_budget_capture_and_disconnect(transport, tmp_path, failure):
    args = arguments(tmp_path)
    args.timer_resume_code = True
    transport.config[rr.TIMER_WINDOW[0]] = rr.validate_prior_capture(PRIOR)
    for _, address, length in tr.WINDOWS:
        transport.config[address] = bytes((i * 19) & 255 for i in range(length))
    if failure == "confirmation": args.confirmed_idle_clients = False
    if failure == "conflict": args.integration_code = True
    if failure == "device": transport.info["hardware"] = "other"
    if failure == "disconnect": transport.fail_disconnect = True
    if failure == "late_traffic": transport.late_traffic = True
    target = args.output / "rom-timer-resume-code.json"
    if failure:
        with pytest.raises((ValueError, RuntimeError)): asyncio.run(rom_read.run(args))
        assert not target.exists()
        if failure in ("confirmation", "conflict"): assert not transport.connected
        else:
            assert transport.disconnected
            if failure in ("disconnect", "late_traffic"):
                assert len(transport.writes) == 180
            rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
            assert rows[-1]["kind"] == "aborted" and not rows[-1]["retry"]
            assert rows[-1]["disconnect_confirmed"] is (failure != "disconnect")
    else:
        assert asyncio.run(rom_read.run(args)) == 0
        assert transport.disconnected and not transport.is_connected
        rows = [json.loads(s) for s in (args.output / "transcript.jsonl").read_text().splitlines()]
        assert rows[0]["plan"] == "rom-timer-resume-code-v1"
        assert rows[-2] == {"kind": "disconnected", "confirmed": True}
        assert rows[-1]["requests"] == 180 and rows[-1]["rom_bytes"] == 524
        assert not rows[-1]["flash_authorized"]


@pytest.mark.parametrize("window", tr.WINDOWS)
@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "v2"])
@pytest.mark.parametrize("state", [0, 2, 3])
def test_actual_cd_instructions_only_copy_fixed_low_rom_chunks(window, image, state):
    _, address, length = window
    for start, size in (cr.chunks(address, length)[0], cr.chunks(address, length)[-1]):
        rt.test_actual_cd_instructions_copy_fixed_low_rom_addresses_without_execution(image, state, start, size)
