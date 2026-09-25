"""Actual 22-object conditional budget; NEVER an image or installation plan.

python -m probe.discovery_budget --output NEW_DIRECTORY --zig /path/to/zig
Keeps the reviewed nine unowned text intervals and the exact APP end. Only
discovery is newly compiled; all other objects are pinned checkpoint inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import APPEND, END, inspect_elf, validate_inputs

ROOT = trial.ROOT
STOCK = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
DESCRIPTOR = ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
ELF_NAME = "UNOWNED-discovery-budget-NOT-INSTALLABLE.elf"
GATES = (*trial.FALSE_GATES, "hardware_access", "production_admission_enabled",
         "discovery_callback_attached", "discovery_storage_owned", "stock_image_constructed")


def inspect_budget(raw, discovery, stock, descriptor):
    """Exact geometry and full inventory, derived from 21 pins plus discovery."""
    validate_inputs(stock, descriptor)
    _, pins = trial.pinned_inputs()
    objects = {n: p.read_bytes() for n, p in pins.items()} | {"discovery": discovery}
    functions, constants, sizes, input_unwind = trial._inventory(objects)
    added, added_constants, _, _ = trial._inventory({"discovery": discovery})
    if {key[0] for key in added} != {"wdi_encode", "wdi_read"} or sum(added.values()) != 2 or added_constants:
        raise ValueError("only the reviewed discovery functions may be added")
    elf = trial._elf(raw)
    if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != (32, True, "EM_ARM", "ET_EXEC"):
        raise ValueError("requires ARM32 executable diagnostic")
    expected = {".trial_" + n: (trial.BIAS + trial.HOLES[h][0], sizes[n])
                for n, h in trial.PLACEMENTS.items()}
    allocated = []
    for section in elf.iter_sections():
        if section["sh_type"] in ("SHT_REL", "SHT_RELA") and section["sh_size"]:
            raise ValueError("unresolved diagnostic relocation")
        if not section["sh_flags"] & 2 or not section["sh_size"]:
            continue
        start, size = section["sh_addr"], section["sh_size"]
        if section.name in expected:
            if (start, size) != expected[section.name]:
                raise ValueError("changed conditional text interval")
        elif section.name in (".text", ".ARM.exidx"):
            if not APPEND <= start < start + size <= END or (section.name == ".text" and start != APPEND):
                raise ValueError("append outside unchanged APP bound")
        else:
            raise ValueError("unexpected allocated section")
        kind = ("SHT_ARM_EXIDX", 130) if section.name == ".ARM.exidx" else ("SHT_PROGBITS", 6)
        if ((section["sh_type"], section["sh_flags"]) != kind or section["sh_addralign"] != 4
                or start % 4 or section["sh_offset"] % 4 or section["sh_offset"] + size > len(raw)):
            raise ValueError("invalid allocated mapping")
        allocated.append(section)
    if Counter(s.name for s in allocated) != Counter([*expected, ".text", ".ARM.exidx"]):
        raise ValueError("missing or duplicated allocated section")
    for field in ("sh_addr", "sh_offset"):
        spans = sorted((s[field], s[field] + s["sh_size"]) for s in allocated)
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError("overlapping diagnostic sections")
    text, unwind = (elf.get_section_by_name(n) for n in (".text", ".ARM.exidx"))
    if (unwind["sh_addr"] != (text["sh_addr"] + text["sh_size"] + 3) & ~3 or unwind["sh_size"] % 8
            or elf.get_section(unwind["sh_link"]).name not in {*expected, ".text"}):
        raise ValueError("invalid unwind geometry")
    loads = [p for p in elf.iter_segments() if p["p_type"] == "PT_LOAD"]
    if len(loads) != len(allocated):
        raise ValueError("requires one narrow LOAD per interval")
    for section in allocated:
        matches = [p for p in loads if (p["p_vaddr"], p["p_memsz"]) == (section["sh_addr"], section["sh_size"])]
        if len(matches) != 1:
            raise ValueError("LOAD covers preserved bytes or padding")
        p = matches[0]
        if (p["p_paddr"] != p["p_vaddr"] or p["p_filesz"] != p["p_memsz"]
                or p["p_offset"] != section["sh_offset"] or p["p_align"] != 4
                or p["p_flags"] != (4 if section.name == ".ARM.exidx" else 5)):
            raise ValueError("invalid LOAD mapping")
    headers = [p for p in elf.iter_segments() if p["p_type"] == "PT_ARM_EXIDX"]
    if len(headers) != 1 or any(headers[0][key] != value for key, value in {
            "p_vaddr": unwind["sh_addr"], "p_paddr": unwind["sh_addr"], "p_offset": unwind["sh_offset"],
            "p_filesz": unwind["sh_size"], "p_memsz": unwind["sh_size"], "p_flags": 4, "p_align": 4}.items()):
        raise ValueError("invalid unwind program header")
    symbols = elf.get_section_by_name(".symtab")
    if symbols is None:
        raise ValueError("full symbols required")
    actual_functions, actual_constants, locations = Counter(), Counter(), []
    for symbol in symbols.iter_symbols():
        if symbol.name and symbol["st_shndx"] == "SHN_UNDEF":
            raise ValueError("unresolved symbol")
        if not symbol["st_size"] or symbol["st_info"]["type"] not in ("STT_FUNC", "STT_OBJECT"):
            continue
        function = symbol["st_info"]["type"] == "STT_FUNC"
        start = symbol["st_value"] & ~1 if function else symbol["st_value"]
        owner = elf.get_section(symbol["st_shndx"]) if isinstance(symbol["st_shndx"], int) else None
        if (owner is None or owner.name not in {*expected, ".text"}
                or not owner["sh_addr"] <= start < start + symbol["st_size"] <= owner["sh_addr"] + owner["sh_size"]
                or (function and not symbol["st_value"] & 1)):
            raise ValueError("symbol outside retained code/constants")
        key = (symbol.name, symbol["st_size"], symbol["st_info"]["bind"])
        (actual_functions if function else actual_constants)[key] += 1
        if function:
            locations.append({"name": symbol.name, "address": symbol["st_value"],
                              "bytes": symbol["st_size"], "section": owner.name})
    if actual_functions != functions or actual_constants != constants:
        raise ValueError("full 22-object function/constant inventory changed")
    if elf["e_entry"] != next(s["address"] for s in locations if s["name"] == "wd_init"):
        raise ValueError("wrong entry")
    # Preserve the original service's sole relocation and all table/UUID bytes.
    service = trial._elf(objects["stock_service"])
    rodata = bytearray(service.get_section_by_name(".rodata").data())
    relocs = [r for section in service.iter_sections() if section["sh_type"] == "SHT_REL"
              for r in section.iter_relocations()]
    if (len(relocs) != 1 or relocs[0]["r_offset"] != 36 or relocs[0]["r_info_type"] != 2
            or service.get_section_by_name(".symtab").get_symbol(relocs[0]["r_info_sym"]).name != "wgd_service_uuid"
            or rodata[36:40] != bytes(4)):
        raise ValueError("unreviewed service relocation")
    rodata[36:40] = next(s["st_value"] for s in symbols.iter_symbols()
                         if s.name == "wgd_service_uuid").to_bytes(4, "little")
    for s in service.get_section_by_name(".symtab").iter_symbols():
        if s["st_info"]["type"] != "STT_OBJECT" or not s["st_size"]:
            continue
        dest = next(t for t in symbols.iter_symbols() if t.name == s.name)
        section = elf.get_section(dest["st_shndx"])
        off = dest["st_value"] - section["sh_addr"]
        if section.data()[off:off + s["st_size"]] != rodata[s["st_value"]:s["st_value"] + s["st_size"]]:
            raise ValueError("service constant bytes changed")
    try:
        inspect_elf(raw, stock, descriptor)
    except ValueError as exc:
        rejection = str(exc)
    else:
        raise ValueError("production accepted unowned layout")
    end = unwind["sh_addr"] + unwind["sh_size"]
    return {"elf_sha256": trial._sha(raw), "function_count": sum(functions.values()),
            "constant_count": sum(constants.values()), "functions": locations,
            "required_function_inventory": [list(k) + [v] for k, v in sorted(functions.items())],
            "required_constant_inventory": [list(k) + [v] for k, v in sorted(constants.items())],
            "sections": [{"name": s.name, "address": s["sh_addr"], "bytes": s["sh_size"]} for s in allocated],
            "input_unwind_bytes": input_unwind, "linked_unwind_bytes": unwind["sh_size"],
            "hypothetical_stock_text_bytes": sum(size for _, size in expected.values()),
            "occupied_append_bytes": end - APPEND, "configured_remaining_bytes": END - end,
            "append_end": end, "configured_end": END, "production_rejection": rejection}


def build(output, zig):
    """Guard inputs before work, then two compiles, two links and one map link."""
    manifest, pins = trial.pinned_inputs()
    paths = {"pinned/" + n: p for n, p in pins.items()}
    for name in trial.UNITS:
        for ext in ("c", "h"):
            relative = f"firmware/unified/{name}.{ext}"
            path = ROOT / relative
            if relative in manifest["inputs_sha256"]:
                if trial._sha(path.read_bytes()) != manifest["inputs_sha256"][relative]:
                    raise ValueError("pinned source changed: " + relative)
                paths[relative] = path
    for path in (STOCK, DESCRIPTOR, trial.CHECKPOINT / "manifest.json", Path(__file__),
                 ROOT / "tests/test_discovery_budget.py", ROOT / "firmware/unified/discovery.c",
                 ROOT / "firmware/unified/discovery.h", ROOT / "requirements-firmware-proof.txt"):
        paths[str(path.relative_to(ROOT))] = path
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            path = Path(filename).absolute()
            if path.suffix == ".py" and path.is_relative_to(ROOT):
                paths[str(path.relative_to(ROOT))] = path
    source = InputSnapshot(paths)
    compiler, linker = shutil.which("clang"), shutil.which(str(zig))
    if not compiler or not linker:
        raise ValueError("Clang and explicit reviewed Zig required")
    tools = InputSnapshot({"clang": Path(compiler), "zig": Path(linker), "python": Path(sys.executable)})
    if tools.hashes != {n: manifest["tool_executables_sha256"][n] for n in tools.hashes}:
        raise ValueError("reviewed tool executable changed")
    if subprocess.check_output([linker, "version"], text=True).strip() != "0.15.2":
        raise ValueError("reviewed Zig 0.15.2 required")
    stock, descriptor = STOCK.read_bytes(), DESCRIPTOR.read_bytes()
    validate_inputs(stock, descriptor)
    source.verify(); tools.verify()
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    artifacts = []

    def snapshot(*files):
        captured = InputSnapshot({str(p.relative_to(output)): p for p in files})
        artifacts.append(captured)

    def verify():
        for captured in (source, tools, *artifacts):
            captured.verify()

    pair = [output / "discovery.o", output / "repeat/discovery.o"]
    pair[1].parent.mkdir()
    for obj in pair:
        subprocess.run([compiler, *manifest["flags"], "-c", str(ROOT / "firmware/unified/discovery.c"),
                        "-o", str(obj)], check=True)
        snapshot(obj, obj.with_suffix(".su"))  # Immediately, before any later process.
    verify()
    if pair[0].read_bytes() != pair[1].read_bytes() or pair[0].with_suffix(".su").read_bytes() != pair[1].with_suffix(".su").read_bytes():
        raise ValueError("discovery compilation did not reproduce")
    objects = {n: p.read_bytes() for n, p in pins.items()} | {"discovery": pair[0].read_bytes()}
    _, _, sizes, _ = trial._inventory(objects)
    script = output / "UNOWNED-unchanged-conditional.ld"
    script.write_text(trial.linker_script(sizes))
    snapshot(script)
    # Original objects are linked directly and remain guarded inputs, not rebuilt.
    linked_objects = [*map(str, pins.values()), str(pair[0])]
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"), ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    targets = [output / ELF_NAME, output / "repeat-NOT-INSTALLABLE.elf", output / "mapped-NOT-INSTALLABLE.elf"]
    map_path = output / "actual-link.map"
    commands = [[linker, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
                 "-Wl,-T," + str(script), "-Wl,-e,wd_init", "-Wl,--build-id=none", "-Wl,--no-undefined",
                 "-Wl,-z,max-page-size=4", "-o", str(target), *linked_objects] for target in targets[:2]]
    commands.append([linker, "ld.lld", "-T", str(script), "-e", "wd_init", "--build-id=none",
                     "--no-undefined", "-z", "max-page-size=4", "-Map=" + str(map_path),
                     "-o", str(targets[2]), *linked_objects])
    results = []
    for i, (command, target) in enumerate(zip(commands, targets)):
        verify()
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        produced = [p for p in (target, *([map_path] if i == 2 else [])) if p.exists()]
        if produced:
            snapshot(*produced)  # Before logging, comparing or interpreting output.
        log = output / f"link-{i + 1}.json"
        log.write_text(json.dumps({"command": command, "exit": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        snapshot(log)
        results.append(result)
    verify()
    if [(r.returncode, r.stdout, r.stderr) for r in results[:1]] != [(results[1].returncode, results[1].stdout, results[1].stderr)]:
        raise ValueError("second link outcome did not reproduce")
    if bool(results[0].returncode) != bool(results[2].returncode) or not map_path.exists():
        raise ValueError("mapped link disagrees or omitted map")
    report = {"schema": "whip.discovery-budget.v1", "object_count": len(objects),
              "component_count": len(trial.SOURCES), "unlinked_candidate_count": len(trial.CANDIDATES) + 1,
              "stock_bytes_written": 0, "tests_run": False, **{key: False for key in GATES}}
    if results[0].returncode:
        if any(p.exists() for p in targets):
            raise ValueError("failed link left ambiguous ELF output")
        report.update(link_succeeded=False, identical_second_refusal=True, map_is_successful_fit_evidence=False,
                      link_exit=results[0].returncode, link_stderr=results[0].stderr,
                      mapped_link_stderr=results[2].stderr)
    else:
        raw = targets[0].read_bytes()
        if any(target.read_bytes() != raw for target in targets[1:]):
            raise ValueError("second or mapped ELF did not reproduce")
        report.update(inspect_budget(raw, pair[0].read_bytes(), stock, descriptor))
        report.update(link_succeeded=True, identical_second_link=True, mapped_link_identical=True,
                      discovery_text_bytes=sizes["discovery"])
    report.update(inputs_sha256=source.hashes, tools_sha256=tools.hashes, compiler_flags=manifest["flags"],
                  input_objects={n: str(p.relative_to(ROOT)) for n, p in pins.items()} | {"discovery": "discovery.o"},
                  artifacts_sha256={k: v for captured in artifacts for k, v in captured.hashes.items()},
                  warning="UNOWNED diagnostic only; entries not retired; no callback/owner; NEVER INSTALL")
    verify()
    with (output / "budget-report.json").open("x") as stream:
        json.dump(report, stream, indent=2); stream.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zig", required=True)
    args = parser.parse_args(argv)
    report = build(args.output, args.zig)
    print(json.dumps({key: report[key] for key in ("link_succeeded", "object_count", "flashable")}
                     | {key: report[key] for key in ("occupied_append_bytes", "configured_remaining_bytes") if key in report}))
    return 0 if report["link_succeeded"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
