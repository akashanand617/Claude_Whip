"""Real-address component link/execution. Synthetic RAM/ROM, never hardware."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from probe.stock_link import build
from whip import fwstock_link as sl
from tests.test_unified_thumb import elf  # noqa: F401 — compiled ARM size witnesses

ROOT = Path(__file__).resolve().parents[1]
STOCK = (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()
DESCRIPTOR = (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes()


@pytest.fixture(scope="module")
def linked(tmp_path_factory):
    supplied = os.environ.get("WHIP_STOCK_LINK_ELF")
    if supplied: return Path(supplied).read_bytes()
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not zig: pytest.skip("reviewed Zig required")
    output = tmp_path_factory.mktemp("stock-link") / "fresh"
    build(output, zig)
    return (output / "stock-append-NOT-INSTALLABLE.elf").read_bytes()


def test_real_address_extent_preserves_entire_stock_and_has_no_test_scaffolding(linked):
    report = sl.inspect_elf(linked, STOCK, DESCRIPTOR)
    assert report["append_address"] == 0x847AD0 and report["end_exclusive"] <= 0x84A000
    assert report["occupied_append_bytes"] + report["configured_remaining_bytes"] == 9520
    assert report["stock_bytes_changed"] == report["static_ram_bytes"] == 0
    assert not any(report[k] for k in ("flashable", "stock_hooks_attached", "ram_ownership_verified", "recovery_verified"))
    assert not any(name.startswith("proof_") for name in report["functions"])
    assert "wf_request" in report["functions"]
    assert "ww_motion_valid" not in report["functions"]  # host-only decoder stays in proof support
    assert {"ww_rx_feed", "ww_body_valid", "ww_crc", "ww_pack_motion"}.issubset(report["functions"])


@pytest.mark.parametrize("payload_bytes", [128, 9520, 9521])
def test_linker_itself_retains_the_fixed_capacity_gate(tmp_path, payload_bytes):
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    compiler = shutil.which("clang")
    if not zig or not compiler: pytest.skip("reviewed Zig and Clang required")
    # Only a size fixture, not component firmware. Include real unwind entries,
    # so a payload filling all 9520 bytes cannot hide its code/metadata overhead.
    source = ("void wd_init(void) {}\n"
              f"const unsigned char size_fixture[{payload_bytes}] = {{1}};\n")
    obj, output = tmp_path / "size.o", tmp_path / "size-NOT-INSTALLABLE.elf"
    subprocess.run([compiler, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
                    "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-x", "c", "-c", "-",
                    "-o", str(obj)], input=source, text=True, check=True)
    result = subprocess.run([zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
                             "-nostdlib", "-Wl,-T," + str(ROOT / "firmware/unified/stock_append.ld"),
                             "-Wl,-e,wd_init", "-Wl,--no-undefined", "-Wl,--build-id=none",
                             "-Wl,-z,max-page-size=4", "-o", str(output), str(obj)],
                            capture_output=True, text=True)
    if payload_bytes >= 9520:
        assert result.returncode != 0
        assert "configured APP bound exceeded" in result.stderr or "will not fit in region" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        from elftools.elf.elffile import ELFFile
        e = ELFFile(BytesIO(output.read_bytes()))
        allocated = [s for s in e.iter_sections() if s["sh_flags"] & 2]
        assert min(s["sh_addr"] for s in allocated) == 0x847AD0
        assert max(s["sh_addr"] + s["sh_size"] for s in allocated) <= 0x84A000


@pytest.fixture(scope="module")
def capacity_link(tmp_path_factory):
    """All current component roots, not a tiny proxy for the EXIDX regression."""
    from probe.unified_build import SOURCES
    from elftools.elf.elffile import ELFFile

    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    compiler = shutil.which("clang")
    if not zig or not compiler: pytest.skip("reviewed Zig and Clang required")
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    directory = tmp_path_factory.mktemp("all-root-capacity")
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    compile_flags = [compiler, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
                     "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra",
                     "-Werror", "-fstack-usage", "-I", str(ROOT / "firmware/unified")]
    objects = []
    for name in (*SOURCES, "compiler_runtime"):
        obj = directory / (name + ".o")
        subprocess.run([*compile_flags, "-c", str(ROOT / f"firmware/unified/{name}.c"),
                        "-o", str(obj)], check=True)
        objects.append(obj)
    command = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
               "-Wl,-T," + str(ROOT / "firmware/unified/stock_append.ld"), "-Wl,-e,wd_init",
               "-Wl,--no-undefined", "-Wl,--build-id=none", "-Wl,-z,max-page-size=4"]
    baseline = directory / "baseline-NOT-INSTALLABLE.elf"
    subprocess.run([*command, "-o", str(baseline), *map(str, objects)], env=env, check=True)
    report = sl.inspect_elf(baseline.read_bytes(), STOCK, DESCRIPTOR)
    exidx_inputs = sum(sum(s["sh_type"] == "SHT_ARM_EXIDX" and bool(s["sh_size"])
                          for s in ELFFile(BytesIO(obj.read_bytes())).iter_sections()) for obj in objects)
    return dict(compile_flags=compile_flags, command=command, objects=objects, env=env,
                report=report, exidx_inputs=exidx_inputs)


@pytest.mark.parametrize("extra", [-4, -1, 0, 1, 4])
def test_all_roots_final_capacity_includes_unwind_and_alignment(capacity_link, tmp_path, extra):
    from elftools.elf.elffile import ELFFile

    c = capacity_link
    padding = c["report"]["configured_remaining_bytes"] + extra
    assert padding > 0  # Fail if the base no longer leaves room for this boundary witness.
    obj, output = tmp_path / "padding.o", tmp_path / "boundary-NOT-INSTALLABLE.elf"
    subprocess.run([*c["compile_flags"], "-x", "c", "-c", "-", "-o", str(obj)],
                   input=f"const unsigned char capacity_padding[{padding}] = {{1}};\n",
                   text=True, check=True)
    result = subprocess.run([*c["command"], "-o", str(output), *map(str, c["objects"]), str(obj)],
                            env=c["env"], capture_output=True, text=True)
    if extra > 0:
        assert result.returncode != 0 and not output.exists()
        assert "will not fit in region 'append'" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    raw = output.read_bytes()
    report = sl.inspect_elf(raw, STOCK, DESCRIPTOR)
    assert report["functions"] == c["report"]["functions"]  # Every actual component root retained.
    expected_end = sl.END - 4 if extra == -4 else sl.END
    assert report["end_exclusive"] == expected_end
    assert report["occupied_append_bytes"] + report["configured_remaining_bytes"] == 9520
    assert not any(report[k] for k in ("flashable", "stock_hooks_attached", "ram_ownership_verified", "recovery_verified"))
    e = ELFFile(BytesIO(raw))
    text, unwind = e.get_section_by_name(".text"), e.get_section_by_name(".ARM.exidx")
    # The last data byte may leave alignment padding; neither padding nor unwind
    # may disappear from the final occupied extent. The old assertion rejected
    # this exact-boundary full-root ELF using its larger provisional EXIDX size.
    assert unwind["sh_addr"] == (text["sh_addr"] + text["sh_size"] + 3) & ~3
    if extra == 0:
        assert text["sh_addr"] + text["sh_size"] + 8 * c["exidx_inputs"] > sl.END
        old_script = tmp_path / "former-transient-assert.ld"
        old_script.write_text((ROOT / "firmware/unified/stock_append.ld").read_text() +
                              '\nASSERT(ADDR(.ARM.exidx) + SIZEOF(.ARM.exidx) <= 0x84a000, '
                              '"configured APP bound exceeded")\n')
        old_command = ["-Wl,-T," + str(old_script) if arg.startswith("-Wl,-T,") else arg
                       for arg in c["command"]]
        old_output = tmp_path / "former-assert-REFUSED.elf"
        old = subprocess.run([*old_command, "-o", str(old_output), *map(str, c["objects"]), str(obj)],
                             env=c["env"], capture_output=True, text=True)
        assert old.returncode != 0 and not old_output.exists()
        assert "configured APP bound exceeded" in old.stderr
    repeat = tmp_path / "repeat.elf"
    subprocess.run([*c["command"], "-o", str(repeat), *map(str, c["objects"]), str(obj)],
                   env=c["env"], check=True)
    assert repeat.read_bytes() == raw


@pytest.mark.parametrize("kind,source", [
    ("initialized", "unsigned forbidden_static = 1;\n"),
    ("bss", "unsigned forbidden_static;\n"),
    ("common", "unsigned forbidden_static __attribute__((common));\n"),
    ("orphan_readonly", 'const unsigned forbidden_orphan __attribute__((section(".unexpected"))) = 1;\n'),
    ("orphan_writable", 'unsigned forbidden_orphan __attribute__((section(".unexpected"))) = 1;\n'),
])
def test_all_roots_cannot_hide_static_ram_or_orphan_sections(capacity_link, tmp_path, kind, source):
    c = capacity_link
    obj, output = tmp_path / "forbidden.o", tmp_path / "forbidden-NOT-INSTALLABLE.elf"
    subprocess.run([*c["compile_flags"], "-x", "c", "-c", "-", "-o", str(obj)],
                   input=source, text=True, check=True)
    result = subprocess.run([*c["command"], "-o", str(output), *map(str, c["objects"]), str(obj)],
                            env=c["env"], capture_output=True, text=True)
    if kind in ("initialized", "bss", "common"):
        assert result.returncode != 0 and not output.exists()
        assert "static" in result.stderr
    else:
        # MEMORY is a capacity guard, not an allow-list of ELF sections. Even an
        # in-bound orphan that the linker admits must fail the mandatory verifier.
        assert result.returncode == 0, result.stderr
        with pytest.raises(ValueError, match="unexpected/writable allocated section"):
            sl.inspect_elf(output.read_bytes(), STOCK, DESCRIPTOR)


def test_actual_arm_context_budget_after_profile_deduplication(elf):
    from whip.fwthumb import RuntimeThumb
    h = RuntimeThumb(elf)
    assert h.call("proof_source_profile_size") == 60
    assert h.call("proof_tap_size") == 212  # 32 full axes, no redundant per-entry sequence.
    assert h.call("proof_runtime_size") == 408
    assert h.call("proof_adapter_size") == 672
    assert h.call("proof_dispatch_context_size") == 764
    assert h.call("proof_dispatch_size") == 784  # Includes caller-owned 20-byte frame.
    assert h.call("proof_timer_fence_size") == 12
    # Nominal arithmetic only: no on-ring RAM ownership or complete binding fit.
    assert 1024 - (h.call("proof_dispatch_size") + h.call("proof_timer_fence_size")) == 228


@pytest.mark.parametrize("what", ["stock", "descriptor", "entry", "machine", "write_segment", "moved_segment",
                                 "outside_section", "section_offset", "no_execute", "function_in_unwind"])
def test_invalid_inputs_or_elf_fail_closed(linked, what):
    raw, stock, descriptor = bytearray(linked), STOCK, DESCRIPTOR
    from elftools.elf.elffile import ELFFile
    elf = ELFFile(BytesIO(linked))
    if what == "stock": stock += b"\0"
    elif what == "descriptor": descriptor += b"\n"
    elif what == "entry": struct.pack_into("<I", raw, 24, 0)
    elif what == "machine": struct.pack_into("<H", raw, 18, 3)
    elif what == "function_in_unwind":
        table = elf.get_section_by_name(".symtab")
        index = next(i for i, s in enumerate(table.iter_symbols()) if s.name == "wf_request")
        exidx = elf.get_section_by_name(".ARM.exidx")
        struct.pack_into("<II", raw, table["sh_offset"] + index * table["sh_entsize"] + 4,
                         exidx["sh_addr"] | 1, 2)
    elif what in ("write_segment", "moved_segment", "no_execute"):
        index = next(i for i, s in enumerate(elf.iter_segments()) if s["p_type"] == "PT_LOAD")
        off = elf["e_phoff"] + index * elf["e_phentsize"]
        field, value = {"write_segment": (24, 7), "moved_segment": (12, 0x826000), "no_execute": (24, 4)}[what]
        struct.pack_into("<I", raw, off + field, value)
    else:
        index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == ".text")
        struct.pack_into("<I", raw, elf["e_shoff"] + index * elf["e_shentsize"] +
                         (16 if what == "section_offset" else 12), 0 if what == "section_offset" else 0x847ACC)
    with pytest.raises(ValueError): sl.inspect_elf(bytes(raw), stock, descriptor)


@pytest.mark.parametrize("what", [
    "unsectioned_load_tail", "sectionless_load", "files_without_memory", "empty_load",
    "missing_load", "duplicate_load", "load_past_end", "load_before_append",
    "memory_larger_than_file", "file_larger_than_memory", "bad_load_alignment",
    "coherent_unwind_past_end", "coherent_unwind_gap", "coherent_section_overlap",
    "unwind_header_address", "unwind_header_offset", "unwind_header_size", "unwind_header_flags",
    "missing_unwind_header", "duplicate_unwind_header", "unwind_link", "unwind_entry_size",
    "section_alignment", "section_file_alias",
])
def test_exact_final_section_and_segment_geometry_fail_closed(linked, what):
    from elftools.elf.elffile import ELFFile

    e, raw = ELFFile(BytesIO(linked)), bytearray(linked)
    sections, segments = list(e.iter_sections()), list(e.iter_segments())
    ti = next(i for i, s in enumerate(sections) if s.name == ".text")
    ui = next(i for i, s in enumerate(sections) if s.name == ".ARM.exidx")
    li = next(i for i, s in enumerate(segments) if s["p_type"] == "PT_LOAD" and s["p_flags"] == 4)
    hi = next(i for i, s in enumerate(segments) if s["p_type"] == "PT_ARM_EXIDX")
    spare = next(i for i, s in enumerate(segments) if s["p_type"] == "PT_GNU_STACK")
    u, load = sections[ui], segments[li]

    def ph(index, field, value):
        fields = ("type", "offset", "vaddr", "paddr", "filesz", "memsz", "flags", "align")
        struct.pack_into("<I", raw, e["e_phoff"] + index * e["e_phentsize"] + 4 * fields.index(field), value)

    def sh(index, field, value):
        fields = ("name", "type", "flags", "addr", "offset", "size", "link", "info", "align", "entsize")
        struct.pack_into("<I", raw, e["e_shoff"] + index * e["e_shentsize"] + 4 * fields.index(field), value)

    def copied_ph(source, target):
        a, b = (e["e_phoff"] + i * e["e_phentsize"] for i in (source, target))
        raw[b:b + e["e_phentsize"]] = raw[a:a + e["e_phentsize"]]

    if what in ("unsectioned_load_tail", "load_past_end"):
        size = load["p_memsz"] + 1 if what == "unsectioned_load_tail" else sl.END - load["p_vaddr"] + 1
        ph(li, "filesz", size); ph(li, "memsz", size)
    elif what in ("sectionless_load", "files_without_memory", "empty_load"):
        address = sl.END if what != "sectionless_load" else u["sh_addr"] + u["sh_size"]
        # All bytes describe the new LOAD, so the negative cannot be attributed
        # to stale GNU_STACK fields. The zero-mem/file-present case was accepted
        # by the old early skip and must not bypass an end-exclusive bound.
        values = (1, 0, address, address, int(what != "empty_load"), int(what == "sectionless_load"), 4, 1)
        struct.pack_into("<8I", raw, e["e_phoff"] + spare * e["e_phentsize"], *values)
    elif what == "missing_load": ph(li, "type", 0)
    elif what == "duplicate_load": copied_ph(li, spare)
    elif what == "load_before_append":
        ph(li, "vaddr", sl.APPEND - 4); ph(li, "paddr", sl.APPEND - 4)
    elif what == "memory_larger_than_file": ph(li, "memsz", load["p_memsz"] + 1)
    elif what == "file_larger_than_memory": ph(li, "filesz", load["p_filesz"] + 1)
    elif what == "bad_load_alignment": ph(li, "align", 8)
    elif what == "coherent_unwind_past_end":
        size = sl.END - u["sh_addr"] + 8
        sh(ui, "size", size)
        for index in (li, hi): ph(index, "filesz", size); ph(index, "memsz", size)
    elif what in ("coherent_unwind_gap", "coherent_section_overlap"):
        address = u["sh_addr"] + (4 if what == "coherent_unwind_gap" else -4)
        sh(ui, "addr", address)
        for index in (li, hi): ph(index, "vaddr", address); ph(index, "paddr", address)
    elif what.startswith("unwind_header_"):
        field, value = {"unwind_header_address": ("vaddr", u["sh_addr"] + 4),
                        "unwind_header_offset": ("offset", u["sh_offset"] + 4),
                        "unwind_header_size": ("memsz", u["sh_size"] + 8),
                        "unwind_header_flags": ("flags", 5)}[what]
        ph(hi, field, value)
    elif what == "missing_unwind_header": ph(hi, "type", 0)
    elif what == "duplicate_unwind_header": copied_ph(hi, spare)
    elif what == "unwind_link": sh(ui, "link", ui)
    elif what == "unwind_entry_size":
        size = u["sh_size"] - 4
        sh(ui, "size", size)
        for index in (li, hi): ph(index, "filesz", size); ph(index, "memsz", size)
    elif what == "section_alignment": sh(ui, "align", 3)
    elif what == "section_file_alias":
        offset = sections[ti]["sh_offset"]
        sh(ui, "offset", offset)
        for index in (li, hi): ph(index, "offset", offset)
    else: raise AssertionError(what)
    with pytest.raises(ValueError): sl.inspect_elf(bytes(raw), STOCK, DESCRIPTOR)


def test_real_address_health_default_and_unavailable_gesture_preserve_state(linked):
    h = sl.StockAppendThumb(linked, STOCK, DESCRIPTOR)
    h.invoke("wd_init", 0, 0, 11, 22)
    assert h.word(0) == 0 and h.invoke("wa_health_allowed", 0) == 1
    assert h.invoke("wd_open", 1, 0, 0)
    before = bytes(h.uc.mem_read(h.CONTEXT, h.context_size))
    assert not h.invoke("wa_request", 1, 0)
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == before
    assert h.invoke("wd_close", 1, 0)
    assert h.word(0) == 0 and h.invoke("wa_health_allowed", 0) == 1


def test_real_address_runtime_full_transition_uses_same_validated_primitives(linked):
    # Synthetic completion receipts: code/relocations only, NOT hardware proof.
    from tests.test_unified_thumb import enter, offer, restore
    h = sl.StockAppendThumb(linked, STOCK, DESCRIPTOR)
    h.invoke("wr_init")
    session = enter(h)
    assert offer(h, session, 1, count=3) == 0
    for sequence in (1, 2, 3):
        assert h.invoke("wr_next", session, h.OUTPUT, 1)
        assert h.output() == (sequence, (123, -8005, 32767))
        assert h.invoke("wr_sent", session, sequence, 1, 1)
    assert h.invoke("wr_request", 0, 2)
    restore(h, 2)
    assert not h.invoke("wr_next", session, h.OUTPUT, 2)


class TimerFenceThumb(sl.StockAppendThumb):
    API = 0x10D5E
    API_RETURN = 0x3FFF0

    def __init__(self, raw):
        self.result, self.early = 1, False
        self.preempt = None
        self.calls, self.return_to = [], None
        super().__init__(raw, STOCK, DESCRIPTOR)
        self.uc.mem_map(0, 0x40000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        self.uc.mem_map(0x201000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_write(0x201478, struct.pack("<I", 0x300800))
        self.invoke("wf_init")

    def _read(self, uc, access, address, size, value, opaque):
        if address == 0x201478 and size == 4: return  # Synthetic queue slot.
        super()._read(uc, access, address, size, value, opaque)

    def _code(self, uc, pc, size, opaque):
        a = self.a
        if pc == self.API:
            callback, context, ticket, wait = [uc.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                                                                      a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)]
            assert callback == self.symbols["timer_passed"] and context == self.CONTEXT and wait == 0
            assert uc.reg_read(a.UC_ARM_REG_PRIMASK) == 0
            self.calls.append((callback, context, ticket, wait))
            if self.preempt is not None:
                self.preempt(self)
            if self.early:
                self.return_to = uc.reg_read(a.UC_ARM_REG_LR)
                uc.reg_write(a.UC_ARM_REG_R0, context)
                uc.reg_write(a.UC_ARM_REG_R1, ticket)
                uc.reg_write(a.UC_ARM_REG_LR, self.API_RETURN | 1)
                uc.reg_write(a.UC_ARM_REG_PC, callback)
            else:
                uc.reg_write(a.UC_ARM_REG_R0, self.result & 0xFFFFFFFF)
                uc.reg_write(a.UC_ARM_REG_PC, uc.reg_read(a.UC_ARM_REG_LR))
            return
        if pc == self.API_RETURN:
            uc.reg_write(a.UC_ARM_REG_R0, self.result & 0xFFFFFFFF)
            uc.reg_write(a.UC_ARM_REG_PC, self.return_to)
            return
        super()._code(uc, pc, size, opaque)


def test_timer_fence_waits_for_real_callback_and_consumes_once(linked):
    h = TimerFenceThumb(linked)
    assert h.invoke("wf_request", 1)
    assert not h.invoke("wf_complete", 1)
    assert not h.invoke("wf_request", 2)
    h.invoke("timer_passed", 1)
    assert h.invoke("wf_complete", 1)
    assert not h.invoke("wf_complete", 1)
    assert not h.invoke("wf_request", 1)
    assert len(h.calls) == 1


def test_timer_fence_absent_queue_permanently_faults_without_rom_call(linked):
    h = TimerFenceThumb(linked)
    h.uc.mem_write(0x201478, bytes(4))
    assert not h.invoke("wf_request", 1)
    assert not h.calls and h.word(0) == 0
    assert bytes(h.uc.mem_read(h.CONTEXT + 10, 1)) == b"\x01"
    h.uc.mem_write(0x201478, struct.pack("<I", 0x300800))
    assert not h.invoke("wf_request", 2) and not h.calls
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


@pytest.mark.parametrize("early", [False, True])
@pytest.mark.parametrize("result", [0, 1, 2, 255, 0xFFFFFFFF])
def test_timer_fence_enqueue_failure_never_becomes_completion_even_with_early_callback(linked, early, result):
    h = TimerFenceThumb(linked)
    h.early, h.result = early, result
    assert bool(h.invoke("wf_request", 5)) == (result == 1)
    assert bool(h.invoke("wf_complete", 5)) == (result == 1 and early)
    if not early:
        h.invoke("timer_passed", 5)
        assert bool(h.invoke("wf_complete", 5)) == (result == 1)
    if result != 1:
        assert not h.invoke("wf_request", 6)
        assert len(h.calls) == 1


def test_timer_fence_abandon_preserves_ticket_and_ignores_old_callback(linked):
    h = TimerFenceThumb(linked)
    assert h.invoke("wf_request", 10)
    assert not h.invoke("wf_abandon", 9)
    assert h.invoke("wf_abandon", 10)
    assert not h.invoke("wf_abandon", 10)
    assert not h.invoke("wf_request", 10)
    assert h.invoke("wf_request", 11)
    h.invoke("timer_passed", 10)
    assert not h.invoke("wf_complete", 11)
    h.invoke("timer_passed", 11)
    assert h.invoke("wf_complete", 11)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


@pytest.mark.parametrize("result", [0, 1])
@pytest.mark.parametrize("early", [False, True])
def test_timer_fence_abandon_during_enqueue_cannot_admit_a_second_request(linked, result, early):
    h = TimerFenceThumb(linked)
    h.result, h.early = result, early
    observations = []

    def interrupt_at_api(owner):
        # Another task executes the same compiled code with a distinct stack.
        # Only shared object bytes cross contexts; no synthetic receipt is set.
        other = TimerFenceThumb(linked)
        other.uc.mem_write(other.CONTEXT, bytes(owner.uc.mem_read(owner.CONTEXT, 12)))
        observations.append((other.invoke("wf_complete", 10),
                             other.invoke("wf_abandon", 10),
                             other.invoke("wf_request", 11), len(other.calls)))
        owner.uc.mem_write(owner.CONTEXT, bytes(other.uc.mem_read(other.CONTEXT, 12)))

    h.preempt = interrupt_at_api
    assert not h.invoke("wf_request", 10)
    assert observations == [(0, 1, 0, 0)]
    assert h.word(0) == 10 and len(h.calls) == 1
    assert not h.invoke("wf_complete", 10)
    h.preempt, h.early = None, False
    assert bool(h.invoke("wf_request", 11)) == (result == 1)
    h.invoke("timer_passed", 10)
    assert not h.invoke("wf_complete", 11)
    h.invoke("timer_passed", 11)
    assert bool(h.invoke("wf_complete", 11)) == (result == 1)


@pytest.mark.parametrize("primask", [0, 1])
def test_timer_fence_preserves_interrupt_mask_and_rejects_masked_enqueue(linked, primask):
    h = TimerFenceThumb(linked)
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, primask)
    assert bool(h.invoke("wf_request", 1)) == (primask == 0)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == primask
    h.invoke("timer_passed", 1)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == primask
    assert bool(h.invoke("wf_complete", 1)) == (primask == 0)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == primask


def test_timer_fence_rejects_interrupt_context_and_ticket_wrap(linked):
    h = TimerFenceThumb(linked)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, 3)
    assert not h.invoke("wf_request", 1) and not h.calls
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, 0)
    assert h.invoke("wf_request", 0xFFFFFFFF)
    h.invoke("timer_passed", 0xFFFFFFFF)
    assert h.invoke("wf_complete", 0xFFFFFFFF)
    assert not h.invoke("wf_request", 0) and not h.invoke("wf_request", 1)


@pytest.mark.parametrize("reset,stop", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_real_append_stop_shim_calls_original_stock_bus_and_preserves_errors(linked, reset, stop):
    from elftools.elf.elffile import ELFFile
    from whip.fwstock_binding import StockBindingHarness
    from tests.test_fwstock_binding import invoke_stop
    sl.inspect_elf(linked, STOCK, DESCRIPTOR)
    h = StockBindingHarness(STOCK)
    before = bytes(h.uc.mem_read(0x825FB0, len(STOCK)))
    elf = ELFFile(BytesIO(linked))
    for segment in elf.iter_segments():
        if segment["p_type"] == "PT_LOAD": h.uc.mem_write(segment["p_vaddr"], segment.data())
    symbol = elf.get_section_by_name(".symtab").get_symbol_by_name("wb_stock_stop_writes")[0]
    start = symbol["st_value"] & ~1
    h.shim_functions["wb_stock_stop_writes"] = symbol["st_value"]
    h.shim_spans.append((start, start + symbol["st_size"]))
    h.transfer_results.extend((reset, stop))
    result, report = invoke_stop(h)
    assert result == int(reset == stop == 0) and report == (1, reset, stop, 1)
    assert h.transfers == [b"\x7b\xa5", b"\x7b\0"]
    assert not h.allocations and bytes(h.uc.mem_read(0x825FB0, len(STOCK))) == before
