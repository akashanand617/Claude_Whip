"""Unowned scattered-link experiment: exact ARM code, synthetic RAM/ROM only."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct

import pytest
from elftools.elf.elffile import ELFFile

from whip import fwrelocation_trial as trial
from whip.fwindicator import ENTRIES, RETURN_ZERO
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb, ThumbProofError

ROOT = Path(__file__).resolve().parents[1]
STOCK_PATH = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
STOCK = STOCK_PATH.read_bytes()
DESCRIPTOR = (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not zig:
        pytest.fail("explicit reviewed WHIP_ZIG required; no skipped relocation proof")
    output = tmp_path_factory.mktemp("indicator-trial") / "diagnostic"
    report = trial.build_trial(output, zig)
    return output, report, (output / "unowned-relocation-NOT-INSTALLABLE.elf").read_bytes()


@pytest.fixture(scope="module")
def combined(tmp_path_factory):
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not zig:
        pytest.fail("explicit reviewed WHIP_ZIG required")
    output = tmp_path_factory.mktemp("indicator-service-trial") / "diagnostic"
    report = trial.build_trial(output, zig, include_service=True)
    return output, report


class RelocatedThumb(RuntimeThumb):
    """Do not use production verifier acceptance to load this rejected ELF."""
    CODE, RETURN = 0x820000, 0x84FFF0
    SETTINGS = (0x208AAC, 0x208AAD, 0x208C44, 0x208C46)
    CACHE = ((0x20C020, 1), (0x20C01E, 1), (0x20C028, 1), (0x20C022, 2))

    def __init__(self, raw):
        import unicorn as u
        from unicorn import arm_const as a
        report = trial.inspect_trial(raw, STOCK, DESCRIPTOR)
        self.u, self.a = u, a
        self.symbols = {f["name"]: f["address"] for f in report["functions"]}
        self.executable = [(f["address"] & ~1, (f["address"] & ~1) + f["bytes"])
                           for f in report["functions"]]
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(self.CODE, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(self.RAM, 0x10000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x208000, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x20C000, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        # Emulator-only entry retirement, identical to the earlier experiment.
        # The on-disk stock remains untouched; all non-hole bytes are compared.
        self.uc.mem_write(trial.BIAS, STOCK)
        for offset, _, _ in ENTRIES:
            self.uc.mem_write(trial.BIAS + offset, RETURN_ZERO)
        self.loaded_spans = []
        for s in ELFFile(BytesIO(raw)).iter_segments():
            if s["p_type"] == "PT_LOAD" and s["p_memsz"]:
                self.uc.mem_write(s["p_vaddr"], s.data())
                self.loaded_spans.append((s["p_vaddr"], s["p_vaddr"] + s["p_memsz"]))
        self.context_size = 1024  # guarded synthetic fixture, not ring ownership
        self.batch_length = self.instruction_count = 0
        self.returned = False
        self.stack_low = self.STACK
        self.uc.mem_write(self.CONTEXT - 16, b"\xa5" * (self.context_size + 32))
        self.uc.mem_write(0x20C000, b"\xa5" * 0x1000)
        self.uc.mem_write(0x208C98, struct.pack("<I", 0x12345678))
        self.take, self.give, self.bus_results = 1, 1, [0, 0]
        self.calls, self.executed, self.cache_writes, self.settings_reads = [], set(), [], []
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)

    def _code(self, uc, address, size, opaque):
        self.executed.add(address)
        regs = [uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1,
                                        self.a.UC_ARM_REG_R2)]
        if address in (0x133F4, 0x1341C, 0x833AF2):
            assert uc.reg_read(self.a.UC_ARM_REG_SP) % 8 == 0
            if address == 0x133F4:
                assert regs[:2] == [0x12345678, 100]
                self.calls.append(("take",)); result = self.take
            elif address == 0x1341C:
                assert regs[0] == 0x12345678
                self.calls.append(("give",)); result = self.give
            else:
                assert regs[0] == 0x33 and regs[2] == 2
                assert self.STACK - 0x1000 <= regs[1] <= self.STACK - 2
                self.calls.append(("write", bytes(uc.mem_read(regs[1], 2))))
                result = self.bus_results.pop(0)
            uc.reg_write(self.a.UC_ARM_REG_R0, result)
            uc.reg_write(self.a.UC_ARM_REG_PC, uc.reg_read(self.a.UC_ARM_REG_LR))
            return
        super()._code(uc, address, size, opaque)

    def _read(self, uc, access, address, size, value, opaque):
        if address == 0x208C98 and size == 4:
            return
        if address in self.SETTINGS and size == 1:
            assert uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == 1
            self.settings_reads.append(address)
            return
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        if (address, size) in self.CACHE:
            assert uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == 1
            self.cache_writes.append((address, size, value))
            return
        super()._write(uc, access, address, size, value, opaque)


def test_layout_is_deterministic_unowned_and_rejected_by_production(built):
    _, report, raw = built
    assert report["component_count"] == 16 and report["health_commit_text_bytes"] == 196
    assert report["identical_second_link"] and report["hypothetical_stock_text_bytes"] == 408
    assert report["append_end"] <= trial.END
    assert report["occupied_append_bytes"] + report["configured_remaining_bytes"] == 9520
    assert not any(report[k] for k in ("flashable", "holes_owned", "whole_integration_complete",
                                     "hardware_hooks_attached", "ram_ownership_verified"))
    assert "wsc_commit_health" in {f["name"] for f in report["functions"]}
    assert set(report["required_baseline_functions"]) == trial.baseline_functions() | {
        "wsc_commit_health", "wh_retirement_allowed"}
    assert not report["additional_functions"]
    with pytest.raises(ValueError): inspect_elf(raw, STOCK, DESCRIPTOR)


def test_combined_service_refusal_is_preserved_not_called_a_fit(built, combined):
    output, report = combined
    assert report["service_database_included"] and report["health_commit_text_bytes"] == 196
    assert not report["link_succeeded"] and report["expected_bound_refusal"]
    assert report["identical_second_refusal"] and report["link_exit"] != 0
    assert not (output / "unowned-relocation-NOT-INSTALLABLE.elf").exists()
    assert not report["whole_integration_complete"] and not report["flashable"]
    assert not report["map_is_successful_fit_evidence"]
    # Source-backed LLD phase explanation, not a successful layout or permission
    # to remove its failed assertion: the provisional table has not coalesced.
    assert report["failed_map_append_end"] < trial.END
    assert report["failed_map_append_end"] - trial.APPEND == built[1]["occupied_append_bytes"] + 240
    assert report["input_exidx_sections"] == 18
    assert report["lld_provisional_unwind_bytes"] == 144
    text = next(s for s in report["failed_map_sections"] if s["name"] == ".text")
    assert report["lld_provisional_append_end"] == text["address"] + text["bytes"] + 144
    assert report["lld_provisional_append_end"] > trial.END
    assert set(("link-failure.txt", "failed-link.map", "map-link-failure.txt")) <= report["artifacts_sha256"].keys()


def test_all_stock_bytes_outside_exact_holes_and_stubs_remain_identical(built):
    h = RelocatedThumb(built[2])
    allowed = {i for offset, size, _ in trial.PLACEMENTS.values() for i in range(offset, offset + size)}
    allowed.update(i for offset, _, _ in ENTRIES for i in range(offset, offset + 4))
    observed = bytes(h.uc.mem_read(trial.BIAS, len(STOCK)))
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(STOCK, observed, strict=True)))
    assert observed[0x3CA8:0x3CAC] == STOCK[0x3CA8:0x3CAC]
    assert observed[0x3DE8:0x3E48] == STOCK[0x3DE8:0x3E48]
    for offset, _, _ in ENTRIES: assert observed[offset:offset + 4] == RETURN_ZERO
    assert STOCK_PATH.read_bytes() == STOCK


@pytest.mark.parametrize("violation", ["entry", "machine", "stub", "shared_tail", "pool",
                                     "append_end", "section_overlap", "unwind_overlap", "segment_gap",
                                     "writable", "function", "missing_root"])
def test_malformed_trial_layouts_fail_closed(built, violation):
    raw = bytearray(built[2]); e = ELFFile(BytesIO(raw))
    if violation == "entry": struct.pack_into("<I", raw, 24, 0)
    elif violation == "machine": struct.pack_into("<H", raw, 18, 3)
    elif violation == "missing_root":
        table = e.get_section_by_name(".symtab")
        sym = next(s for s in table.iter_symbols() if s.name == "wh_job_end")
        strings = e.get_section(table["sh_link"])
        raw[strings["sh_offset"] + sym["st_name"]] = ord("q")
    elif violation == "function":
        table = e.get_section_by_name(".symtab")
        idx = next(i for i, s in enumerate(table.iter_symbols()) if s.name == "wrc_commit_hr")
        struct.pack_into("<I", raw, table["sh_offset"] + idx * table["sh_entsize"] + 4, trial.BIAS + 0x3CA9)
    elif violation in ("segment_gap", "writable"):
        idx, seg = next((i, p) for i, p in enumerate(e.iter_segments()) if p["p_type"] == "PT_LOAD")
        off = e["e_phoff"] + idx * e["e_phentsize"]
        struct.pack_into("<I", raw, off + (20 if violation == "segment_gap" else 24),
                         seg["p_memsz"] + 4 if violation == "segment_gap" else 7)
    else:
        name = ".text" if violation == "append_end" else ".ARM.exidx" if violation == "unwind_overlap" else ".trial_stock_result_commit"
        idx = next(i for i, s in enumerate(e.iter_sections()) if s.name == name)
        address = {"stub": trial.BIAS + 0x3AC4, "shared_tail": trial.BIAS + 0x3CA8,
                   "pool": trial.BIAS + 0x3DE8, "append_end": trial.END,
                   "section_overlap": trial.BIAS + 0x3B20, "unwind_overlap": trial.APPEND}[violation]
        struct.pack_into("<I", raw, e["e_shoff"] + idx * e["e_shentsize"] + 12, address)
    with pytest.raises(ValueError): trial.inspect_trial(bytes(raw), STOCK, DESCRIPTOR)


@pytest.mark.parametrize("numerator,denominator", [(0, 0), (1, 0), (0, 1), (1, 1), (0xFFFFFFFF, 1),
                                                 (0xFFFFFFFF, 0xFFFFFFFF), (0xFFFFFFFF, 40), (0x80000000, 3)])
def test_relocated_compiler_division_executes_not_mocked(built, numerator, denominator):
    h = RelocatedThumb(built[2])
    assert h.call("__aeabi_uidiv", numerator, denominator) == (numerator // denominator if denominator else 0)
    assert trial.BIAS + 0x3B80 <= (h.symbols["__aeabi_uidiv"] & ~1) < trial.BIAS + 0x3C18


@pytest.mark.parametrize("source,destination", [(0, 4), (4, 0), (0, 0), (0, 32)])
def test_relocated_memmove_overlap_and_memcpy_clear(built, source, destination):
    h = RelocatedThumb(built[2]); original = bytes(range(64))
    h.uc.mem_write(h.CONTEXT, original)
    expected = bytearray(original); expected[destination:destination + 24] = original[source:source + 24]
    h.call("__aeabi_memmove4", h.CONTEXT + destination, h.CONTEXT + source, 24)
    assert bytes(h.uc.mem_read(h.CONTEXT, 64)) == expected
    h.call("__aeabi_memcpy4", h.CONTEXT + 80, h.CONTEXT, 64)
    assert bytes(h.uc.mem_read(h.CONTEXT + 80, 64)) == expected
    h.call("__aeabi_memclr4", h.CONTEXT + 80, 64)
    assert bytes(h.uc.mem_read(h.CONTEXT + 80, 64)) == bytes(64)


@pytest.mark.parametrize("take,give,results", [(1, 1, [0, 0]), (0, 1, [0, 0]), (1, 0, [0, 0]),
                                            (1, 1, [7, 0]), (1, 1, [0, 9]), (1, 1, [0xFFFFFFFF, 0xFFFFFFFF])])
def test_relocated_stop_preserves_abi_and_both_raw_results(built, take, give, results):
    h = RelocatedThumb(built[2]); h.take, h.give, h.bus_results = take, give, results.copy()
    assert h.invoke("wb_stock_stop_writes") == int(bool(take and give and not any(results)))
    report = struct.unpack("<4I", h.uc.mem_read(h.CONTEXT, 16))
    assert report == ((take, *results, give) if take else (0, 0xFFFFFFFF, 0xFFFFFFFF, 0))
    assert h.calls == ([('take',), ('write', b'\x7b\xa5'), ('write', b'\x7b\0'), ('give',)] if take else [('take',)])


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("values", [(0, 0, 0, 0), (60, 31, 3, 1), (255, 255, 255, 255)])
def test_relocated_settings_reads_exact_addresses_and_restores_mask(built, mask, values):
    h = RelocatedThumb(built[2])
    for address, value in zip(h.SETTINGS, values, strict=True): h.uc.mem_write(address, bytes([value]))
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
    before = bytes(h.uc.mem_read(0x208000, 0x1000))
    assert h.call("wss_read_controls") == int.from_bytes(bytes(values), "little")
    assert h.settings_reads == list(h.SETTINGS)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == mask
    assert bytes(h.uc.mem_read(0x208000, 0x1000)) == before


@pytest.mark.parametrize("stale,measured", [(False, True), (True, True), (False, False)])
def test_relocated_hr_commit_calls_current_nonrelocated_ticket_guard(built, stale, measured):
    h = RelocatedThumb(built[2]); h.invoke("wh_init", 1, 1)
    assert h.invoke("wh_job_begin", 0, h.OUTPUT)
    ticket = struct.unpack("<IIB3x", h.uc.mem_read(h.OUTPUT, 12))
    if stale: assert h.invoke("wh_begin_quiesce", 1)
    before = bytes(h.uc.mem_read(h.CONTEXT, 168))
    result = h.call("wrc_commit_hr", h.CONTEXT, *ticket, int(measured), 72, 0x1234)
    assert bool(result) == (measured and not stale)
    assert len(h.cache_writes) == (4 if result else 0)
    assert bytes(h.uc.mem_read(h.CONTEXT, 168)) == before
    assert h.symbols["wh_result_allowed"] & ~1 in h.executed
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


def test_cross_region_boot_clear_and_unlinked_candidate_are_actual_arm(built):
    h = RelocatedThumb(built[2]); h.invoke("wd_init", 0, 0, 11, 22)
    assert h.word(0) == 0 and h.invoke("wa_health_allowed", 0)
    assert h.symbols["__aeabi_memclr4"] & ~1 in h.executed
    before = bytes(h.uc.mem_read(h.CONTEXT, h.context_size))
    assert not h.invoke("wa_request", 1, 0)
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == before
    assert not h.call("wsc_commit_health", 0, 0, 0, 0)
    with pytest.raises(ThumbProofError):
        h._code(h.uc, trial.BIAS + 0x3CA8, 2, None)
