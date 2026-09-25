"""Whole-candidate link in conditional, UNOWNED raw/diagnostic/indicator space.

Research ELF only: no stock image edits, OTA/container output, entry retirement,
hook attachment or production-verifier changes. A fit is NOT an ownership or
release result. Every original object/function, constant and unwind input stays.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import APPEND, END, inspect_elf, validate_inputs

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "firmware/unified/build-20260924-raw-ingress-v1"
MANIFEST_SHA256 = "4ab65e86daeab7fee1d186c4fd873fe95fec7dd1dbb3040ba3ba5ee9d37d1cee"
BIAS = 0x825FB0
SOURCES = ("mode_controller", "sample_tap", "runtime", "health_adapter", "fresh_source", "adapter",
           "stock_binding", "wire", "dispatch", "stock_transport", "stock_timer_fence", "stock_health_timers",
           "stock_schedule_settings", "stock_result_commit", "stock_optical_work", "stock_optical_io")
CANDIDATES = ("stock_health_commit", "stock_service", "stock_coordinator", "stock_legacy_gate")
UNITS = (*SOURCES, *CANDIDATES, "compiler_runtime")
# Exclusive file-offset bounds. Unused parts remain unallocated, not padding.
# These are planning allowances, NOT approved entry stubs or reference closure.
HOLES = {
    "raw_prefix": (0x1E50, 0x1F40), "raw_tail": (0x1F70, 0x2104),
    "raw_handler": (0x2108, 0x2348),
    "bf_prefix": (0x48CC, 0x48E8), "bf_tail": (0x4910, 0x4924),
    "ce": (0x4B08, 0x4C34), "cd": (0x4C3C, 0x4CBC),
    "indicator_result": (0x3AC8, 0x3B18), "indicator_settings": (0x3B20, 0x3B50),
    "indicator_runtime": (0x3B80, 0x3C18), "indicator_binding": (0x3C1C, 0x3C9C),
}
PLACEMENTS = {
    "stock_health_commit": "raw_prefix", "stock_timer_fence": "raw_tail",
    "mode_controller": "raw_handler", "stock_health_timers": "ce", "stock_legacy_gate": "cd",
    "stock_result_commit": "indicator_result", "stock_schedule_settings": "indicator_settings",
    "compiler_runtime": "indicator_runtime", "stock_binding": "indicator_binding",
}
FALSE_GATES = ("flashable", "holes_owned", "reference_closure_verified", "whole_integration_complete",
               "hardware_hooks_attached", "ram_ownership_verified", "recovery_verified",
               "entry_retirement_implemented", "physical_health_continuity_verified")


def _elf(raw):
    from elftools.elf.elffile import ELFFile
    return ELFFile(BytesIO(raw))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned_inputs():
    """Require the reviewed checkpoint, including all 21 exact objects."""
    manifest_path = CHECKPOINT / "manifest.json"
    raw = manifest_path.read_bytes()
    if _sha(raw) != MANIFEST_SHA256:
        raise ValueError("reviewed checkpoint manifest changed")
    manifest = json.loads(raw)
    paths = {name: CHECKPOINT / ("stock-address/compiler_runtime.o" if name == "compiler_runtime"
                                else name + ".o") for name in UNITS}
    for path in paths.values():
        if _sha(path.read_bytes()) != manifest["artifacts_sha256"][str(path.relative_to(CHECKPOINT))]:
            raise ValueError("pinned current object changed: " + path.name)
    return manifest, paths


def _inventory(objects):
    functions, constants, text_sizes, unwind_bytes = Counter(), Counter(), {}, 0
    for name, raw in objects.items():
        e = _elf(raw)
        if (e.elfclass, e.little_endian, e["e_machine"], e["e_type"]) != (32, True, "EM_ARM", "ET_REL"):
            raise ValueError("requires ARM32 relocatable objects")
        for section in e.iter_sections():
            if not section["sh_flags"] & 2 or not section["sh_size"]:
                continue
            if section.name not in (".text", ".rodata", ".ARM.exidx") or section["sh_flags"] & 1:
                raise ValueError("unreviewed allocated input section")
            if section.name == ".ARM.exidx":
                unwind_bytes += section["sh_size"]
        text_sizes[name] = e.get_section_by_name(".text")["sh_size"]
        for s in e.get_section_by_name(".symtab").iter_symbols():
            if s["st_shndx"] == "SHN_UNDEF" or not s["st_size"]:
                continue
            key = (s.name, s["st_size"], s["st_info"]["bind"])
            if s["st_info"]["type"] == "STT_FUNC":
                if s.name.startswith("proof_") or s.name == "ww_motion_valid":
                    raise ValueError("proof support is not a production candidate")
                functions[key] += 1
            elif s["st_info"]["type"] == "STT_OBJECT":
                constants[key] += 1
    return functions, constants, text_sizes, unwind_bytes


def linker_script(text_sizes):
    """Exact unchanged APP bound, distinct narrow LOAD per moved whole text."""
    regions = sorted(PLACEMENTS, key=lambda n: HOLES[PLACEMENTS[n]][0])
    memories = [f"app (rx) : ORIGIN = {APPEND:#x}, LENGTH = {END - APPEND:#x}"]
    sections, phdrs = [], []
    for i, name in enumerate(regions):
        lo, hi = HOLES[PLACEMENTS[name]]
        if not 0 < text_sizes[name] <= hi - lo or lo % 4 or hi % 4:
            raise ValueError("whole object text does not fit exact conditional hole")
        memories.append(f"h{i} (rx) : ORIGIN = {BIAS + lo:#x}, LENGTH = {hi - lo:#x}")
        phdrs.append(f"p{i} PT_LOAD FLAGS(5);")
        sections += [f".trial_{name} : {{ *{name}.o(.text) }} >h{i} :p{i}",
                     f'ASSERT(SIZEOF(.trial_{name}) == {text_sizes[name]}, "whole text changed")']
    return "\n".join([
        "/* UNOWNED CONDITIONAL HOLES; NO ENTRY RETIREMENT; NEVER INSTALL. */",
        "ENTRY(wd_init)", "MEMORY {", *memories, "}",
        "PHDRS {", *phdrs, "app PT_LOAD FLAGS(5); unwind PT_LOAD FLAGS(4); }",
        "SECTIONS {", *sections,
        ".text : { *(.text*) *(.rodata*) } >app :app",
        ".ARM.exidx : { *(.ARM.exidx*) } >app :unwind",
        ".data : { *(.data*) } >app :app", ".bss (NOLOAD) : { *(.bss*) *(COMMON) } >app :app",
        "/DISCARD/ : { *(.comment) *(.note*) }", "}",
        'ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "no static RAM approved")',
        # Final MEMORY enforcement, exactly as the current production script;
        # no premature ASSERT using LLD's pre-coalescing EXIDX size estimate.
    ])


def inspect_trial(raw, stock, descriptor):
    """Validate diagnostic geometry + full pinned inventory; require rejection."""
    validate_inputs(stock, descriptor)
    _, paths = pinned_inputs()
    original = {n: p.read_bytes() for n, p in paths.items()}
    funcs, consts, sizes, input_unwind = _inventory(original)
    e = _elf(raw)
    if (e.elfclass, e.little_endian, e["e_machine"], e["e_type"]) != (32, True, "EM_ARM", "ET_EXEC"):
        raise ValueError("requires ARM32 executable diagnostic")
    expected = {".trial_" + n: (BIAS + HOLES[h][0], sizes[n]) for n, h in PLACEMENTS.items()}
    allocated = []
    for s in e.iter_sections():
        if s["sh_type"] in ("SHT_REL", "SHT_RELA") and s["sh_size"]:
            raise ValueError("unresolved diagnostic relocation")
        if not s["sh_flags"] & 2 or not s["sh_size"]:
            continue
        start, size = s["sh_addr"], s["sh_size"]
        if s.name in expected:
            if (start, size) != expected[s.name]:
                raise ValueError("outside exact conditional object text interval")
        elif s.name == ".text":
            if start != APPEND or start + size > END:
                raise ValueError("append text outside unchanged APP bound")
        elif s.name == ".ARM.exidx":
            if not APPEND <= start < start + size <= END or size % 8:
                raise ValueError("unwind outside unchanged APP bound")
        else:
            raise ValueError("unexpected allocated section")
        kind = ("SHT_ARM_EXIDX", 130) if s.name == ".ARM.exidx" else ("SHT_PROGBITS", 6)
        if ((s["sh_type"], s["sh_flags"]) != kind or s["sh_addralign"] != 4 or start % 4 or
                s["sh_offset"] % 4 or s["sh_offset"] + size > len(raw)):
            raise ValueError("invalid allocated section mapping")
        allocated.append(s)
    if len(allocated) != len(expected) + 2 or {s.name for s in allocated} != {*expected, ".text", ".ARM.exidx"}:
        raise ValueError("missing or duplicated allocated section")
    for field in ("sh_addr", "sh_offset"):
        spans = sorted((s[field], s[field] + s["sh_size"]) for s in allocated)
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError("overlapping trial sections")
    text, unwind = (e.get_section_by_name(n) for n in (".text", ".ARM.exidx"))
    if unwind["sh_addr"] != ((text["sh_addr"] + text["sh_size"] + 3) & ~3):
        raise ValueError("unwind not immediately after append text")
    if e.get_section(unwind["sh_link"]).name not in expected | {".text": ()}:
        raise ValueError("unwind link is not a retained code section")
    loads = [p for p in e.iter_segments() if p["p_type"] == "PT_LOAD"]
    if len(loads) != len(allocated):
        raise ValueError("requires one narrow LOAD per allocated interval")
    for s in allocated:
        matches = [p for p in loads if (p["p_vaddr"], p["p_memsz"]) == (s["sh_addr"], s["sh_size"])]
        if len(matches) != 1:
            raise ValueError("LOAD spans preserved stock/padding")
        p = matches[0]
        if (p["p_paddr"] != p["p_vaddr"] or p["p_filesz"] != p["p_memsz"] or
                p["p_offset"] != s["sh_offset"] or p["p_align"] != 4 or
                p["p_flags"] != (4 if s.name == ".ARM.exidx" else 5)):
            raise ValueError("invalid LOAD mapping")
    headers = [p for p in e.iter_segments() if p["p_type"] == "PT_ARM_EXIDX"]
    if len(headers) != 1 or any(headers[0][k] != v for k, v in {
            "p_vaddr": unwind["sh_addr"], "p_paddr": unwind["sh_addr"], "p_offset": unwind["sh_offset"],
            "p_filesz": unwind["sh_size"], "p_memsz": unwind["sh_size"], "p_flags": 4, "p_align": 4}.items()):
        raise ValueError("unwind header mapping changed")
    symbols = e.get_section_by_name(".symtab")
    if symbols is None:
        raise ValueError("complete symbols required")
    actual_funcs, actual_consts, functions = Counter(), Counter(), []
    for s in symbols.iter_symbols():
        if s.name and s["st_shndx"] == "SHN_UNDEF":
            raise ValueError("unresolved symbol")
        if not s["st_size"] or s["st_info"]["type"] not in ("STT_FUNC", "STT_OBJECT"):
            continue
        is_func = s["st_info"]["type"] == "STT_FUNC"
        start = s["st_value"] & ~1 if is_func else s["st_value"]
        owner = e.get_section(s["st_shndx"]) if isinstance(s["st_shndx"], int) else None
        if (owner is None or owner.name not in {*expected, ".text"} or
                not owner["sh_addr"] <= start < start + s["st_size"] <= owner["sh_addr"] + owner["sh_size"] or
                (is_func and not s["st_value"] & 1)):
            raise ValueError("symbol outside retained code/constants")
        key = (s.name, s["st_size"], s["st_info"]["bind"])
        (actual_funcs if is_func else actual_consts)[key] += 1
        if is_func:
            functions.append({"name": s.name, "address": s["st_value"], "bytes": s["st_size"], "section": owner.name})
    if actual_funcs != funcs or actual_consts != consts:
        raise ValueError("all-21-object function/constant inventory changed")
    if e["e_entry"] != next(s["address"] for s in functions if s["name"] == "wd_init"):
        raise ValueError("wrong entry")
    # Pin the sole service relocation (R_ARM_ABS32 at rodata+36 -> UUID).
    # All other UUID/table bytes must match the input, not just names/sizes.
    service = _elf(original["stock_service"])
    rodata = bytearray(service.get_section_by_name(".rodata").data())
    relocs = [r for section in service.iter_sections() if section["sh_type"] == "SHT_REL"
              for r in section.iter_relocations()]
    if (len(relocs) != 1 or relocs[0]["r_offset"] != 36 or relocs[0]["r_info_type"] != 2 or
            service.get_section_by_name(".symtab").get_symbol(relocs[0]["r_info_sym"]).name != "wgd_service_uuid" or
            rodata[36:40] != bytes(4)):
        raise ValueError("unreviewed service relocation")
    uuid = next(s for s in symbols.iter_symbols() if s.name == "wgd_service_uuid")
    rodata[36:40] = uuid["st_value"].to_bytes(4, "little")
    for s in service.get_section_by_name(".symtab").iter_symbols():
        if s["st_info"]["type"] != "STT_OBJECT" or not s["st_size"]:
            continue
        dest = next(t for t in symbols.iter_symbols() if t.name == s.name)
        section = e.get_section(dest["st_shndx"])
        offset = dest["st_value"] - section["sh_addr"]
        data = rodata[s["st_value"]:s["st_value"] + s["st_size"]]
        if section.data()[offset:offset + s["st_size"]] != data:
            raise ValueError("service constant bytes changed")
    try:
        inspect_elf(raw, stock, descriptor)
    except ValueError as exc:
        rejection = str(exc)
    else:
        raise ValueError("production unexpectedly accepted unowned scattered layout")
    end = unwind["sh_addr"] + unwind["sh_size"]
    return {"schema": "whip.raw-relocation-trial.v1", "elf_sha256": _sha(raw),
            "sections": [{"name": s.name, "address": s["sh_addr"], "bytes": s["sh_size"]} for s in allocated],
            "functions": functions, "function_count": sum(funcs.values()),
            "required_function_inventory": [list(k) + [v] for k, v in sorted(funcs.items())],
            "input_unwind_bytes": input_unwind, "linked_unwind_bytes": unwind["sh_size"],
            "hypothetical_stock_text_bytes": sum(size for _, size in expected.values()),
            "occupied_append_bytes": end - APPEND, "configured_remaining_bytes": END - end,
            "configured_end": END, "append_end": end,
            "total_allocated_bytes": sum(s["sh_size"] for s in allocated),
            "component_count": 16, "unlinked_candidate_count": 4, "object_count": 21,
            "stock_bytes_written": 0, "production_rejection": rejection,
            **{k: False for k in FALSE_GATES}}


def build_trial(output, zig):
    """Recompile all pinned units, deterministic link + actual map; never OTA."""
    from probe.unified_build import SOURCES as current, UNLINKED_CANDIDATES
    if current != SOURCES or UNLINKED_CANDIDATES != CANDIDATES:
        raise ValueError("current component inventory changed")
    manifest, pins = pinned_inputs()
    compiler, zig = shutil.which("clang"), shutil.which(str(zig))
    if not compiler or not zig:
        raise ValueError("Clang and explicit reviewed Zig required")
    stock_path = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
    descriptor_path = ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
    paths = {"pinned/" + n: p for n, p in pins.items()}
    for p in [stock_path, descriptor_path, CHECKPOINT / "manifest.json", Path(__file__),
              ROOT / "tests/test_raw_relocation_trial.py", ROOT / "requirements-firmware-proof.txt",
              *(ROOT / "docs" / n for n in ("UNIFIED_RAW_RETIREMENT.md", "UNIFIED_DIAGNOSTIC_RETIREMENT.md",
                                            "UNIFIED_INDICATOR_RETIREMENT.md"))]:
        paths[str(p.relative_to(ROOT))] = p
    for n in UNITS:
        for ext in ("c", "h"):
            p = ROOT / f"firmware/unified/{n}.{ext}"
            if p.exists():
                paths[str(p.relative_to(ROOT))] = p
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            p = Path(filename).absolute()
            if p.suffix == ".py" and p.is_relative_to(ROOT):
                paths[str(p.relative_to(ROOT))] = p
    source = InputSnapshot(paths)
    tools = InputSnapshot({"clang": Path(compiler), "zig": Path(zig), "python": Path(sys.executable)})
    if subprocess.check_output([zig, "version"], text=True).strip() != "0.15.2":
        raise ValueError("requires reviewed Zig 0.15.2")
    if tools.hashes["zig"] != manifest["test_elf"]["linker_executable_sha256"]:
        raise ValueError("reviewed Zig executable changed")
    stock, descriptor = stock_path.read_bytes(), descriptor_path.read_bytes()
    validate_inputs(stock, descriptor)
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    objects, object_snapshots = [], []
    flags = manifest["flags"]
    for n in UNITS:
        target = output / (n + ".o")
        subprocess.run([compiler, *flags, "-c", str(ROOT / f"firmware/unified/{n}.c"), "-o", str(target)], check=True)
        stack = target.with_suffix(".su")
        # Capture each compiled artifact immediately, BEFORE comparing its pin;
        # a later compiler process must not redefine an earlier object's baseline.
        produced = [target, *([stack] if stack.exists() else [])]
        object_snapshots.append(InputSnapshot({p.name: p for p in produced}))
        if target.read_bytes() != pins[n].read_bytes():
            raise ValueError("current source/tool differs from pinned object: " + n)
        objects.append(target)
        if not stack.exists() and n != "stock_service":
            raise ValueError("missing executable stack report")
    for snapshot in (source, tools, *object_snapshots):
        snapshot.verify()
    _, _, sizes, _ = _inventory({p.stem: p.read_bytes() for p in objects})
    script = output / "UNOWNED-raw-diagnostic-indicator.ld"
    script.write_text(linker_script(sizes))
    script_snapshot = InputSnapshot({script.name: script})
    artifacts = [*object_snapshots, script_snapshot]
    for snapshot in (source, tools, *artifacts):
        snapshot.verify()
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"), ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    target = output / "UNOWNED-raw-relocation-NOT-INSTALLABLE.elf"
    command = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
               "-Wl,-T," + str(script), "-Wl,-e,wd_init", "-Wl,--build-id=none", "-Wl,--no-undefined",
               "-Wl,-z,max-page-size=4"]
    results, output_snapshots = [], []
    targets = [target, output / "repeat-NOT-INSTALLABLE.elf"]
    for destination in targets:
        result = subprocess.run([*command, "-o", str(destination), *map(str, objects)], env=env, capture_output=True, text=True)
        if not result.returncode:
            # Capture before any equality comparison or ELF interpretation.
            output_snapshots.append(InputSnapshot({destination.name: destination}))
        results.append(result)
    if [(r.returncode, r.stdout, r.stderr) for r in results[:1]] != [(results[1].returncode, results[1].stdout, results[1].stderr)]:
        raise ValueError("diagnostic link result did not reproduce")
    map_path, mapped_target = output / "actual-link.map", output / "mapped-NOT-INSTALLABLE.elf"
    mapped = subprocess.run([zig, "ld.lld", "-T", str(script), "-e", "wd_init", "--build-id=none",
                             "--no-undefined", "-z", "max-page-size=4", "-Map=" + str(map_path),
                             "-o", str(mapped_target), *map(str, objects)], env=env, capture_output=True, text=True)
    output_snapshots.append(InputSnapshot({p.name: p for p in (map_path, mapped_target) if p.exists()}))
    if bool(mapped.returncode) != bool(results[0].returncode):
        raise ValueError("mapped diagnostic disagrees with actual link outcome")
    if results[0].returncode:
        if any(p.exists() for p in [*targets, mapped_target]):
            raise ValueError("failed link left ambiguous ELF output")
        report = {"schema": "whip.raw-relocation-refusal.v1", "link_succeeded": False,
                  "link_stderr": results[0].stderr, "mapped_link_stderr": mapped.stderr,
                  "link_exit": results[0].returncode, "identical_second_refusal": True,
                  "map_is_successful_fit_evidence": False, "object_count": len(UNITS),
                  "stock_bytes_written": 0, **{k: False for k in FALSE_GATES}}
    else:
        if target.read_bytes() != targets[1].read_bytes() or target.read_bytes() != mapped_target.read_bytes():
            raise ValueError("repeated/mapped linked ELF differs")
        report = inspect_trial(target.read_bytes(), stock, descriptor)
        report.update(link_succeeded=True, identical_second_link=True, mapped_link_identical=True)
    output_hashes = {k: v for snapshot in output_snapshots for k, v in snapshot.hashes.items()}
    artifact_hashes = {k: v for snapshot in artifacts for k, v in snapshot.hashes.items()}
    report.update(inputs_sha256=source.hashes, tools_sha256=tools.hashes,
                  artifacts_sha256=artifact_hashes | output_hashes, compiler_flags=flags,
                  tests_run=False, warning="UNOWNED layout only; raw/diagnostic/indicator roots NOT retired; NEVER INSTALL")
    for snapshot in (source, tools, *artifacts, *output_snapshots):
        snapshot.verify()
    with (output / "trial-report.json").open("x") as stream:
        json.dump(report, stream, indent=2)
    return report
