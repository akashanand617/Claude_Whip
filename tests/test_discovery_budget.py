"""Actual bounded 22-object link and refusal guards; no ring or image output."""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

from elftools.elf.elffile import ELFFile
import pytest

from probe import discovery_budget as budget
from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import ProofIntegrityError
from whip.fwthumb import RuntimeThumb

STOCK = budget.STOCK.read_bytes()
DESCRIPTOR = budget.DESCRIPTOR.read_bytes()


def zig():
    path = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    assert path, "explicit reviewed WHIP_ZIG required; never skip"
    return path


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    output = tmp_path_factory.mktemp("discovery-budget") / "full22"
    report = budget.build(output, zig())
    assert report["link_succeeded"]
    return output, report, (output / budget.ELF_NAME).read_bytes(), (output / "discovery.o").read_bytes()


def test_actual_link_preserves_all_objects_and_exact_interval_geometry(built):
    output, report, raw, discovery = built
    manifest, pins = trial.pinned_inputs()
    objects = {n: p.read_bytes() for n, p in pins.items()} | {"discovery": discovery}
    functions, constants, sizes, unwind = trial._inventory(objects)
    assert report["object_count"] == 22 and report["function_count"] == sum(functions.values()) == 132
    assert report["constant_count"] == sum(constants.values()) == 3
    assert report["component_count"] == 16 and report["unlinked_candidate_count"] == 5
    assert report["required_function_inventory"] == [list(k) + [v] for k, v in sorted(functions.items())]
    assert report["required_constant_inventory"] == [list(k) + [v] for k, v in sorted(constants.items())]
    assert report["input_unwind_bytes"] == unwind > report["linked_unwind_bytes"] > 0
    assert report["identical_second_link"] and report["mapped_link_identical"]
    assert report["occupied_append_bytes"] + report["configured_remaining_bytes"] == 9520
    assert report["configured_end"] == 0x84A000 and report["append_end"] <= 0x84A000
    assert (output / "UNOWNED-unchanged-conditional.ld").read_text() == trial.linker_script(sizes)
    assert report["hypothetical_stock_text_bytes"] == 1894
    assert report["stock_bytes_written"] == 0 and not any(report[k] for k in budget.GATES)
    assert report["production_rejection"] == "unexpected/writable allocated section"
    assert report["compiler_flags"] == manifest["flags"]
    assert (output / "actual-link.map").stat().st_size > 0
    assert not list(output.glob("*.bin"))
    for name, path in pins.items():
        assert report["inputs_sha256"]["pinned/" + name] == trial._sha(path.read_bytes())
    for name, digest in report["artifacts_sha256"].items():
        assert trial._sha((output / name).read_bytes()) == digest
    for name, digest in report["inputs_sha256"].items():
        path = pins[name.removeprefix("pinned/")] if name.startswith("pinned/") else trial.ROOT / name
        assert trial._sha(path.read_bytes()) == digest
    with pytest.raises(ValueError, match="unexpected/writable allocated section"):
        budget.inspect_elf(raw, STOCK, DESCRIPTOR)


@pytest.mark.parametrize("bad", ["entry", "machine", "moved_start", "moved_size", "append_bound",
                                 "overlap", "file_overlap", "writable", "relocation", "load_gap",
                                 "load_write", "unwind_header", "missing_old_function", "missing_discovery",
                                 "extra_function", "missing_constant", "service_bytes", "undefined"])
def test_geometry_inventory_and_constant_mutants_fail_closed(built, bad):
    raw = bytearray(built[2]); elf = ELFFile(BytesIO(raw))
    if bad == "entry":
        struct.pack_into("<I", raw, 24, 0)
    elif bad == "machine":
        struct.pack_into("<H", raw, 18, 3)
    elif bad in ("load_gap", "load_write", "unwind_header"):
        kind = "PT_ARM_EXIDX" if bad == "unwind_header" else "PT_LOAD"
        index, segment = next((i, p) for i, p in enumerate(elf.iter_segments()) if p["p_type"] == kind)
        offset = elf["e_phoff"] + index * elf["e_phentsize"]
        struct.pack_into("<I", raw, offset + (24 if bad == "load_write" else 20),
                         7 if bad == "load_write" else segment["p_memsz"] + 4)
    elif bad in ("missing_old_function", "missing_discovery", "extra_function", "missing_constant", "undefined"):
        table = elf.get_section_by_name(".symtab")
        name = {"missing_old_function": "wh_job_end", "missing_discovery": "wdi_read",
                "missing_constant": "wgd_database", "undefined": "wdi_encode"}.get(bad)
        index, symbol = next((i, s) for i, s in enumerate(table.iter_symbols())
                             if (s.name == name if name else s.name.startswith("$t")))
        offset = table["sh_offset"] + index * table["sh_entsize"]
        if bad == "extra_function":
            struct.pack_into("<II", raw, offset + 4, symbol["st_value"] | 1, 2)
            raw[offset + 12] = 2
        elif bad == "undefined":
            struct.pack_into("<H", raw, offset + 14, 0)
        else:
            struct.pack_into("<I", raw, offset + 8, 0)
    elif bad == "service_bytes":
        symbol = next(s for s in elf.get_section_by_name(".symtab").iter_symbols() if s.name == "wgd_database")
        owner = elf.get_section(symbol["st_shndx"])
        raw[owner["sh_offset"] + symbol["st_value"] - owner["sh_addr"]] ^= 1
    else:
        name = (".text" if bad in ("append_bound", "writable") else ".ARM.exidx" if bad in ("overlap", "file_overlap")
                else ".ARM.attributes" if bad == "relocation" else ".trial_stock_health_commit")
        index, section = next((i, s) for i, s in enumerate(elf.iter_sections()) if s.name == name)
        offset = elf["e_shoff"] + index * elf["e_shentsize"]
        field, value = {"moved_start": (12, section["sh_addr"] - 4), "moved_size": (20, section["sh_size"] + 4),
                        "append_bound": (12, trial.END), "overlap": (12, trial.APPEND),
                        "file_overlap": (16, elf.get_section_by_name(".text")["sh_offset"]),
                        "writable": (8, 7), "relocation": (4, 9)}[bad]
        struct.pack_into("<I", raw, offset + field, value)
        if bad == "relocation":
            struct.pack_into("<I", raw, offset + 20, 8)
            struct.pack_into("<I", raw, offset + 36, 8)
    with pytest.raises(ValueError):
        budget.inspect_budget(bytes(raw), built[3], STOCK, DESCRIPTOR)


def test_old_object_pin_mutation_is_rejected_before_output(tmp_path, monkeypatch):
    _, pins = trial.pinned_inputs()
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    shutil.copyfile(trial.CHECKPOINT / "manifest.json", checkpoint / "manifest.json")
    for name, path in pins.items():
        destination = checkpoint / path.relative_to(trial.CHECKPOINT)
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(path, destination)
        if name == "mode_controller":
            raw = bytearray(destination.read_bytes()); raw[-1] ^= 1; destination.write_bytes(raw)
    monkeypatch.setattr(trial, "CHECKPOINT", checkpoint)
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="pinned current object changed"):
        budget.build(output, zig())
    assert not output.exists()


@pytest.mark.parametrize("pin", ["source", "tool"])
def test_old_source_and_tool_pins_are_checked_before_output(tmp_path, monkeypatch, pin):
    manifest, paths = trial.pinned_inputs()
    manifest = deepcopy(manifest)
    if pin == "source":
        manifest["inputs_sha256"]["firmware/unified/wire.h"] = "0" * 64
    else:
        manifest["tool_executables_sha256"]["clang"] = "0" * 64
    monkeypatch.setattr(trial, "pinned_inputs", lambda: (manifest, paths))
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="pinned source changed|reviewed tool executable changed"):
        budget.build(output, zig())
    assert not output.exists()


def test_later_compile_cannot_rebaseline_earlier_discovery_opcode(tmp_path, monkeypatch):
    original = subprocess.run
    compiled, links = [], []

    def corrupt(command, *args, **kwargs):
        result = original(command, *args, **kwargs)
        if "-c" in command:
            compiled.append(Path(command[command.index("-o") + 1]))
            if len(compiled) == 2:
                raw = bytearray(compiled[0].read_bytes())
                text = ELFFile(BytesIO(raw)).get_section_by_name(".text")
                raw[text["sh_offset"]] ^= 1
                compiled[0].write_bytes(raw)
        elif "cc" in command or "ld.lld" in command:
            links.append(command)
        return result

    monkeypatch.setattr(budget.subprocess, "run", corrupt)
    output = tmp_path / "changed-discovery"
    with pytest.raises(ProofIntegrityError, match="proof files changed: discovery.o"):
        budget.build(output, zig())
    assert len(compiled) == 2 and not links
    assert not list(output.glob("*.elf")) and not (output / "budget-report.json").exists()


def test_failed_link_retains_logs_map_and_no_elf_or_margin(tmp_path, monkeypatch):
    """Synthetic linker failure only; successful-fit test above uses real links."""
    original = subprocess.run

    def refuse(command, *args, **kwargs):
        if "cc" in command or "ld.lld" in command:
            for part in command:
                if part.startswith("-Map="):
                    Path(part[5:]).write_text("synthetic failure map; not fit evidence\n")
            return subprocess.CompletedProcess(command, 1, "", "synthetic APP capacity refusal\n")
        return original(command, *args, **kwargs)

    monkeypatch.setattr(budget.subprocess, "run", refuse)
    output = tmp_path / "refused"
    report = budget.build(output, zig())
    assert not report["link_succeeded"] and report["identical_second_refusal"]
    assert not report["map_is_successful_fit_evidence"] and not any(report[k] for k in budget.GATES)
    assert "configured_remaining_bytes" not in report
    assert not list(output.glob("*.elf")) and (output / "actual-link.map").exists()
    assert len(list(output.glob("link-*.json"))) == 3
    assert json.loads((output / "budget-report.json").read_text()) == report


class DiscoveryThumb(RuntimeThumb):
    """Real append code, three executable functions, artificial caller RAM/stack.

    The full 132-function budget inspector runs first. This harness tests only
    the discovery BL relocation and API behavior, not old functions or lifetime.
    """
    CODE, RETURN = 0x840000, 0x84FFF0

    def __init__(self, raw, discovery):
        import unicorn as u
        from unicorn import arm_const as a

        report = budget.inspect_budget(raw, discovery, STOCK, DESCRIPTOR)
        selected = [f for f in report["functions"] if f["name"] in {"wdi_encode", "wdi_read", "ww_put32"}]
        assert len(selected) == 3 and all(f["section"] == ".text" for f in selected)
        self.symbols = {f["name"]: f["address"] for f in selected}
        self.executable = [(f["address"] & ~1, (f["address"] & ~1) + f["bytes"]) for f in selected]
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(self.CODE, 0x10000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(self.RAM, 0x10000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        text = ELFFile(BytesIO(raw)).get_section_by_name(".text")
        self.uc.mem_write(text["sh_addr"], text.data())
        self.loaded_spans = list(self.executable)
        self.context_size, self.batch_length = 64, 0
        self.returned, self.instruction_count, self.stack_low = False, 0, self.STACK
        self.executed = set()
        self.uc.mem_write(self.CONTEXT - 16, b"\xa5" * (64 + 32))
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)

    def _code(self, uc, address, size, opaque):
        super()._code(uc, address, size, opaque)
        self.executed.add(address)


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("boot,build,alignment", [(0x1234567800000000, 0xFEDCBA9800000000, 1),
                                                 (0xFFFFFFFFFFFFFFFF, 0x8000000000000001, 3)])
def test_real_append_discovery_calls_preserve_bytes_and_mask(built, mask, boot, build, alignment):
    h = DiscoveryThumb(built[2], built[3])
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
    pointer, view = h.CONTEXT + 4 + alignment, h.CONTEXT + 32
    args = (boot & 0xFFFFFFFF, boot >> 32, build & 0xFFFFFFFF, build >> 32)
    assert h.call("wdi_encode", pointer, *args)
    expected = b"WI\1\0" + struct.pack("<QQ", boot, build)
    assert bytes(h.uc.mem_read(h.CONTEXT, 64)) == b"\xa5" * (4 + alignment) + expected + b"\xa5" * (40 - alignment)
    assert (h.symbols["ww_put32"] & ~1) in h.executed
    assert h.call("wdi_read", pointer, 0, view)
    assert struct.unpack("<IH", h.uc.mem_read(view, 6)) == (pointer, 20)
    for offset in (1, 20, 0x10000, 0xFFFFFFFF):
        assert not h.call("wdi_read", pointer, offset, view)
        assert bytes(h.uc.mem_read(view, 6)) == bytes(6)
    assert not h.call("wdi_read", 0, 0, view)
    assert not h.call("wdi_read", 0xDEAD0000, 0, 0)
    assert not h.call("wdi_encode", 0, *args)
    assert not h.call("wdi_encode", pointer, 0, 0, 1, 0)
    assert bytes(h.uc.mem_read(pointer, 20)) == expected
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == mask
