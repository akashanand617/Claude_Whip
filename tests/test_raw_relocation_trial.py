"""Diagnostic layout + selected actual ARM; no source qualification or OTA."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import shutil
import struct

from elftools.elf.elffile import ELFFile
import pytest

from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import ProofIntegrityError
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb, ThumbProofError

STOCK_PATH = trial.ROOT / "firmware/rt02cr-stock-3.12.02.bin"
STOCK = STOCK_PATH.read_bytes()
DESCRIPTOR = (trial.ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes()
BASELINE_PATH = trial.CHECKPOINT / "stock-address/stock-append-NOT-INSTALLABLE.elf"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not zig:
        pytest.fail("reviewed explicit WHIP_ZIG required; never skip placement proof")
    output = tmp_path_factory.mktemp("raw-relocation") / "diagnostic"
    report = trial.build_trial(output, zig)
    assert report["link_succeeded"], report
    return output, report, (output / "UNOWNED-raw-relocation-NOT-INSTALLABLE.elf").read_bytes()


class TrialThumb(RuntimeThumb):
    """ELF overlay only; original gate executes, dispatch/TX/ROM are fixtures.

    No raw/diagnostic/indicator stub is installed here. Old entries/interiors
    cannot execute unless they now hold a declared ELF function. Therefore this
    tests relocation, NOT safe retirement or reachability of the original image.
    """
    CODE, RETURN = 0x820000, 0x84FFF0

    def __init__(self, raw, *, baseline=False):
        import unicorn as u
        from unicorn import arm_const as a
        if baseline:
            manifest, _ = trial.pinned_inputs()
            assert hashlib.sha256(raw).hexdigest() == manifest["artifacts_sha256"][str(BASELINE_PATH.relative_to(trial.CHECKPOINT))]
            inspect_elf(raw, STOCK, DESCRIPTOR)
        else:
            trial.inspect_trial(raw, STOCK, DESCRIPTOR)
        elf = ELFFile(BytesIO(raw))
        functions = [s for s in elf.get_section_by_name(".symtab").iter_symbols()
                     if s["st_info"]["type"] == "STT_FUNC" and s["st_size"]]
        self.symbols = {s.name: s["st_value"] for s in functions}
        self.executable = [(s["st_value"] & ~1, (s["st_value"] & ~1) + s["st_size"]) for s in functions]
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(self.CODE, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(self.RAM, 0x10000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x208000, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_write(trial.BIAS, STOCK)
        self.loaded_spans = []
        for s in elf.iter_segments():
            if s["p_type"] == "PT_LOAD":
                self.uc.mem_write(s["p_vaddr"], s.data())
                self.loaded_spans.append((s["p_vaddr"], s["p_vaddr"] + s["p_memsz"]))
        self.context_size = 1024  # synthetic fixture; NOT ring RAM allocation
        self.batch_length = self.instruction_count = 0
        self.returned, self.stack_low = False, self.STACK
        self.uc.mem_write(self.CONTEXT - 16, b"\xa5" * (self.context_size + 32))
        self.uc.mem_write(0x208C98, struct.pack("<I", 0x12345678))
        self.take, self.give, self.bus_results = 1, 1, [0, 0]
        self.calls, self.executed, self.packet_reads = [], set(), []
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)

    def _code(self, uc, address, size, opaque):
        self.executed.add(address)
        regs = [uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2)]
        if address in (0x133F4, 0x1341C, 0x833AF2, trial.BIAS + 0x5882):
            assert uc.reg_read(self.a.UC_ARM_REG_SP) % 8 == 0
            if address == 0x133F4:
                assert regs[:2] == [0x12345678, 100]
                self.calls.append(("take",)); result = self.take
            elif address == 0x1341C:
                assert regs[0] == 0x12345678
                self.calls.append(("give",)); result = self.give
            elif address == 0x833AF2:
                assert regs[0] == 0x33 and regs[2] == 2
                assert self.STACK - 0x1000 <= regs[1] <= self.STACK - 2
                self.calls.append(("tx", bytes(uc.mem_read(regs[1], 2))))
                result = self.bus_results.pop(0)
            else:
                self.calls.append(("dispatch", *regs[:2])); result = 0x12345678
            uc.reg_write(self.a.UC_ARM_REG_R0, result)
            uc.reg_write(self.a.UC_ARM_REG_PC, uc.reg_read(self.a.UC_ARM_REG_LR))
            return
        if trial.BIAS + 0x5C22 <= address < address + size <= trial.BIAS + 0x5C32:
            return  # actual original stock mode/length gate; no prelude execution
        super()._code(uc, address, size, opaque)

    def _read(self, uc, access, address, size, value, opaque):
        if (address, size) in ((0x208C98, 4), (0x208C44, 1)):
            return
        if (address, size) == (trial.BIAS + 0x601C, 4):
            assert STOCK[0x601C:0x6020] == bytes.fromhex("448c2000")
            assert uc.reg_read(self.a.UC_ARM_REG_PC) == trial.BIAS + 0x5C22
            return  # original gate LDR's single mode-pointer literal
        if self.BATCH <= address < self.BATCH + self.batch_length:
            self.packet_reads.append((address, size))
        super()._read(uc, access, address, size, value, opaque)


def test_whole_current_candidate_actually_links_with_all_gates_false(built):
    out, report, raw = built
    assert report["object_count"] == 21 and report["component_count"] == 16
    assert report["unlinked_candidate_count"] == 4
    assert report["identical_second_link"] and report["mapped_link_identical"]
    assert report["occupied_append_bytes"] + report["configured_remaining_bytes"] == 9520
    assert report["append_end"] <= trial.END
    assert report["stock_bytes_written"] == 0
    assert not any(report[k] for k in trial.FALSE_GATES)
    assert report["production_rejection"] == "unexpected/writable allocated section"
    assert report["input_unwind_bytes"] > report["linked_unwind_bytes"] > 0
    assert (out / "actual-link.map").stat().st_size > 0
    with pytest.raises(ValueError, match="unexpected/writable allocated section"):
        inspect_elf(raw, STOCK, DESCRIPTOR)


def test_all_object_functions_constants_and_current_compile_pins_retained(built):
    out, report, raw = built
    manifest, paths = trial.pinned_inputs()
    for name, path in paths.items():
        assert (out / (name + ".o")).read_bytes() == path.read_bytes()
    functions, constants, _, unwind = trial._inventory({n: p.read_bytes() for n, p in paths.items()})
    assert report["function_count"] == sum(functions.values())
    assert report["required_function_inventory"] == [list(k) + [v] for k, v in sorted(functions.items())]
    assert report["input_unwind_bytes"] == unwind
    assert report["compiler_flags"] == manifest["flags"]
    names = {s["name"] for s in report["functions"]}
    assert {"wc_pump", "wlg_receive", "wsc_commit_health", "__aeabi_uidiv", "__aeabi_memmove4"} <= names
    assert not any(n.startswith("proof_") for n in names)
    assert {n for n, size, bind in constants} >= {"wgd_database", "wgd_service_uuid"}


def test_no_stock_file_or_entry_pool_neighbor_modified_by_elf_overlay(built):
    h = TrialThumb(built[2])
    sections = [s for s in built[1]["sections"] if s["address"] < trial.APPEND]
    allowed = {i for s in sections for i in range(s["address"] - trial.BIAS,
                                                 s["address"] - trial.BIAS + s["bytes"])}
    actual = bytes(h.uc.mem_read(trial.BIAS, len(STOCK)))
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(STOCK, actual, strict=True)))
    for lo, hi in ((0x1E4A, 0x1E50), (0x1F40, 0x1F70), (0x2104, 0x2108),
                   (0x2348, 0x23A4), (0x48C6, 0x4924), (0x4B02, 0x4B08),
                   (0x4C34, 0x4C3C), (0x4CBC, 0x4CE0), (0x3CA8, 0x3CAC),
                   (0x3DE8, 0x3E48), (0x80F8, 0x80FC), (0x21A58, 0x21B20)):
        assert actual[lo:hi] == STOCK[lo:hi]
    assert STOCK_PATH.read_bytes() == STOCK


@pytest.mark.parametrize("bad", ["entry", "machine", "raw_stub", "raw_pool", "bf_pool", "diag_stub",
                                  "shared_tail", "append_end", "overlap", "load_gap", "load_write",
                                  "missing_function", "extra_function", "service_bytes", "unwind_header"])
def test_malformed_layouts_and_incomplete_inventory_rejected(built, bad):
    raw = bytearray(built[2]); e = ELFFile(BytesIO(raw))
    if bad == "entry": struct.pack_into("<I", raw, 24, 0)
    elif bad == "machine": struct.pack_into("<H", raw, 18, 3)
    elif bad == "missing_function":
        table = e.get_section_by_name(".symtab")
        index = next(i for i, s in enumerate(table.iter_symbols()) if s.name == "wh_job_end")
        struct.pack_into("<I", raw, table["sh_offset"] + index * table["sh_entsize"] + 8, 0)
    elif bad == "extra_function":
        table = e.get_section_by_name(".symtab")
        index, s = next((i, s) for i, s in enumerate(table.iter_symbols()) if s.name.startswith("$t"))
        offset = table["sh_offset"] + index * table["sh_entsize"]
        struct.pack_into("<II", raw, offset + 4, s["st_value"] | 1, 2)
        raw[offset + 12] = 2  # STB_LOCAL/STT_FUNC; all original functions remain
    elif bad == "service_bytes":
        s = next(s for s in e.get_section_by_name(".symtab").iter_symbols() if s.name == "wgd_database")
        owner = e.get_section(s["st_shndx"])
        raw[owner["sh_offset"] + s["st_value"] - owner["sh_addr"]] ^= 1
    elif bad in ("load_gap", "load_write", "unwind_header"):
        kind = "PT_ARM_EXIDX" if bad == "unwind_header" else "PT_LOAD"
        idx, p = next((i, p) for i, p in enumerate(e.iter_segments()) if p["p_type"] == kind)
        off = e["e_phoff"] + idx * e["e_phentsize"]
        struct.pack_into("<I", raw, off + (24 if bad == "load_write" else 20),
                         7 if bad == "load_write" else p["p_memsz"] + 4)
    else:
        name = ".text" if bad == "append_end" else ".ARM.exidx" if bad == "overlap" else ".trial_stock_health_commit"
        idx = next(i for i, s in enumerate(e.iter_sections()) if s.name == name)
        addr = {"raw_stub": trial.BIAS + 0x1E4C, "raw_pool": trial.BIAS + 0x1F44,
                "bf_pool": trial.BIAS + 0x48E8, "diag_stub": trial.BIAS + 0x4C38,
                "shared_tail": trial.BIAS + 0x3CA8, "append_end": trial.END, "overlap": trial.APPEND}[bad]
        struct.pack_into("<I", raw, e["e_shoff"] + idx * e["e_shentsize"] + 12, addr)
    with pytest.raises(ValueError): trial.inspect_trial(bytes(raw), STOCK, DESCRIPTOR)


def test_object_too_large_is_rejected_before_link_script():
    _, paths = trial.pinned_inputs()
    sizes = trial._inventory({n: p.read_bytes() for n, p in paths.items()})[2]
    sizes["mode_controller"] = 580
    with pytest.raises(ValueError, match="whole object text does not fit"):
        trial.linker_script(sizes)


def test_earlier_object_opcode_drift_during_later_compile_is_rejected(tmp_path, monkeypatch):
    """Same ELF geometry and names, changed code: later snapshots must not bless it."""
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not zig:
        pytest.fail("reviewed explicit WHIP_ZIG required")
    original_run = trial.subprocess.run
    compiled, links = [], []

    def corrupt_after_second_compile(command, *args, **kwargs):
        result = original_run(command, *args, **kwargs)
        if "-c" in command:
            compiled.append(Path(command[command.index("-o") + 1]))
            if len(compiled) == 2:
                path = compiled[0]
                raw = bytearray(path.read_bytes())
                text = ELFFile(BytesIO(raw)).get_section_by_name(".text")
                raw[text["sh_offset"]] ^= 1  # opcode only; identical symbols/section sizes
                path.write_bytes(raw)
        elif "cc" in command or "ld.lld" in command:
            links.append(command)
        return result

    monkeypatch.setattr(trial.subprocess, "run", corrupt_after_second_compile)
    output = tmp_path / "mutated-object-diagnostic"
    with pytest.raises(ProofIntegrityError, match="proof files changed: mode_controller.o"):
        trial.build_trial(output, zig)
    assert len(compiled) == 21 and links == []
    assert not list(output.glob("*.elf")) and not (output / "trial-report.json").exists()


@pytest.mark.parametrize("start", [0, 0xFFFFFF00])
@pytest.mark.parametrize("event", ["complete", "disconnect", "timeout"])
def test_relocated_controller_matches_pinned_actual_arm_across_regions(built, start, event):
    relocated = TrialThumb(built[2])
    baseline = TrialThumb(BASELINE_PATH.read_bytes(), baseline=True)
    for h in (relocated, baseline):
        h.invoke("wm_init")
        h.invoke("wm_link", 1, 0, start)
        assert h.invoke("wm_request", 1, start)
        if event == "complete":
            for _ in range(3):
                assert h.invoke("wm_complete", h.word(12), 1, start)
            h.invoke("wm_tick", (start + 30000) & 0xFFFFFFFF)
        elif event == "disconnect": h.invoke("wm_link", 0, 0, start)
        else: h.invoke("wm_tick", (start + 3000) & 0xFFFFFFFF)
    assert bytes(relocated.uc.mem_read(relocated.CONTEXT, 36)) == bytes(baseline.uc.mem_read(baseline.CONTEXT, 36))
    assert trial.BIAS + 0x2108 <= (relocated.symbols["wm_init"] & ~1) < trial.BIAS + 0x2348


@pytest.mark.parametrize("take,give,results", [(1, 1, [0, 0]), (0, 1, [0, 0]), (1, 0, [0, 0]), (1, 1, [7, 9])])
def test_relocated_stop_matches_baseline_with_explicit_bus_and_rom_fixtures(built, take, give, results):
    states = []
    for h in (TrialThumb(built[2]), TrialThumb(BASELINE_PATH.read_bytes(), baseline=True)):
        h.take, h.give, h.bus_results = take, give, results.copy()
        result = h.invoke("wb_stock_stop_writes")
        states.append((result, bytes(h.uc.mem_read(h.CONTEXT, 16)), h.calls))
    assert states[0] == states[1]


@pytest.mark.parametrize("n,d", [(0, 0), (0xFFFFFFFF, 40), (0x80000000, 3), (1234567, 1)])
def test_relocated_compiler_helper_matches_baseline_actual_arm(built, n, d):
    expected = n // d if d else 0
    for h in (TrialThumb(built[2]), TrialThumb(BASELINE_PATH.read_bytes(), baseline=True)):
        assert h.call("__aeabi_uidiv", n, d) == expected


@pytest.mark.parametrize("opcode,length,mode,forward", [(0xBF, 16, 0, False), (0xCE, 16, 0, False),
    (0xCD, 16, 0, False), (0xA1, 16, 0, False), (0x51, 16, 0, True), (0xA1, 16, 1, False),
    (0xCD, 0x10010, 0, False)])
def test_relocated_legacy_gate_keeps_stock_gate_and_denies_four_retired_opcodes(built, opcode, length, mode, forward):
    h = TrialThumb(built[2]); h.raw_input(bytes([opcode]) + bytes(15))
    h.uc.mem_write(0x208C44, bytes([mode]))
    h.call("wlg_receive", h.BATCH, length)
    assert h.calls == ([("dispatch", h.BATCH, length)] if forward else [])
    if mode == 1 or length != 16: assert h.packet_reads == []
    # Ingress denial alone does not retire already-queued work or stored raw
    # callbacks. This ELF still lacks entry stubs and must never be installed.
    if forward: assert trial.BIAS + 0x5C22 in h.executed


def test_no_default_profile_or_source_is_implicitly_admitted_after_cross_region_init(built):
    h = TrialThumb(built[2])
    h.invoke("wd_init", 0, 0, 11, 22)
    assert h.invoke("wa_health_allowed", 0)
    before = bytes(h.uc.mem_read(h.CONTEXT, h.context_size))
    assert not h.invoke("wa_request", 1, 0)
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == before
    with pytest.raises(ThumbProofError): h._code(h.uc, trial.BIAS + 0x1E4A, 2, None)
