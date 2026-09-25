"""Hypothetical indicator-body relocation experiment, NEVER an OTA builder.

The stock holes are NOT owned or reference-closed. This module produces only a
diagnostic ELF which the unchanged production placement verifier must reject.
No stock/container bytes are written and no production linker is modified.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import APPEND, END, inspect_elf, validate_inputs

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "firmware/unified/build-20260924-parallel-integration-v1/stock-address"
BASELINE_ELF = CHECKPOINT / "stock-append-NOT-INSTALLABLE.elf"
BASELINE_SHA256 = "f21fa753bf1e604a882183affe641219b67f989253d2dafbe3d02ede16e11ec2"
BIAS = 0x825FB0
# Whole object .text sizes; no function splitting, GC, or discarded unwind.
PLACEMENTS = {
    "compiler_runtime": (0x3B80, 152, "14beafe8aebd3fa687aa9ca50d2727c122d04643cf6a268eae0786dc9671235d"),
    "stock_binding": (0x3C1C, 128, "e12c8c700f768b16f41a26c5d5234fe0c65d6e34e59ca41e8d708530b7839c96"),
    "stock_result_commit": (0x3AC8, 80, "d2ada34a2b7fb846be8c984ecb71de29b247c7d17099a59c2f76a5e254aeea7e"),
    "stock_schedule_settings": (0x3B20, 48, "15a2677a0105b05123bb499e669f5bfafb6b27d8f3559b85d99dbf65848f7faa"),
}


def _elf(raw):
    from elftools.elf.elffile import ELFFile
    return ELFFile(BytesIO(raw))


def baseline_functions():
    raw = BASELINE_ELF.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("baseline function inventory changed")
    return {s.name for s in _elf(raw).get_section_by_name(".symtab").iter_symbols()
            if s["st_info"]["type"] == "STT_FUNC" and s["st_size"]}


def linker_script():
    """Diagnostic linker text. Exact narrow regions, not a widened stock bound."""
    regions = sorted(PLACEMENTS.items(), key=lambda item: item[1][0])
    phdrs = " ".join(f"h{i} PT_LOAD FLAGS(5);" for i in range(4))
    sections = []
    for i, (name, (offset, size, _)) in enumerate(regions):
        sections.append(f".trial_{name} {BIAS + offset:#x} : {{ *{name}.o(.text) }} :h{i}")
        sections.append(f'ASSERT(SIZEOF(.trial_{name}) == {size}, "pinned whole text changed")')
    return "\n".join([
        "/* HYPOTHETICAL UNOWNED HOLES. REJECTED BY PRODUCTION VERIFIER. */",
        "ENTRY(wd_init)",
        f"PHDRS {{ {phdrs} app PT_LOAD FLAGS(5); unwind PT_LOAD FLAGS(4); }}",
        "SECTIONS {", *sections,
        f".text {APPEND:#x} : {{ *(.text*) *(.rodata*) }} :app",
        ".ARM.exidx : { *(.ARM.exidx*) } :unwind",
        ".data : { *(.data*) } :app",
        ".bss (NOLOAD) : { *(.bss*) *(COMMON) } :app",
        "/DISCARD/ : { *(.comment) *(.note*) }", "}",
        'ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "no static RAM approved")',
        f'ASSERT(ADDR(.ARM.exidx) + SIZEOF(.ARM.exidx) <= {END:#x}, "configured APP bound exceeded")',
    ])


def inspect_trial(raw, stock, descriptor):
    """Validate ONLY trial geometry/ABI; never approve the proposed holes."""
    validate_inputs(stock, descriptor)
    e = _elf(raw)
    if (e.elfclass, e.little_endian, e["e_machine"], e["e_type"]) != (32, True, "EM_ARM", "ET_EXEC"):
        raise ValueError("requires ARM32 executable trial")
    expected = {".trial_" + name: (BIAS + off, size)
                for name, (off, size, _) in PLACEMENTS.items()}
    allocated = []
    for s in e.iter_sections():
        if s["sh_type"] in ("SHT_REL", "SHT_RELA") and s["sh_size"]:
            raise ValueError("unresolved trial relocations")
        if not s["sh_flags"] & 2 or not s["sh_size"]:
            continue
        start, size = s["sh_addr"], s["sh_size"]
        if s.name in expected:
            if (start, size) != expected[s.name]:
                raise ValueError("trial text outside exact hypothetical interval")
        elif s.name == ".text":
            if start != APPEND or start + size > END:
                raise ValueError("append text outside configured bound")
        elif s.name == ".ARM.exidx":
            if not APPEND <= start < start + size <= END:
                raise ValueError("unwind outside configured bound")
        else:
            raise ValueError("unexpected allocated section")
        kind = ("SHT_ARM_EXIDX", 130) if s.name == ".ARM.exidx" else ("SHT_PROGBITS", 6)
        if (s["sh_type"], s["sh_flags"]) != kind or start % 4 or s["sh_offset"] + size > len(raw):
            raise ValueError("invalid trial section mapping/permissions")
        allocated.append(s)
    names = [s.name for s in allocated]
    if len(names) != 6 or set(names) != {*expected, ".text", ".ARM.exidx"}:
        raise ValueError("missing or duplicated trial sections")
    spans = sorted((s["sh_addr"], s["sh_addr"] + s["sh_size"]) for s in allocated)
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError("overlapping trial sections")
    loads = [s for s in e.iter_segments() if s["p_type"] == "PT_LOAD" and s["p_memsz"]]
    if len(loads) != len(allocated):
        raise ValueError("each exact interval needs its own load segment")
    for s in allocated:
        matches = [p for p in loads if (p["p_vaddr"], p["p_memsz"]) == (s["sh_addr"], s["sh_size"])]
        if len(matches) != 1:
            raise ValueError("load segment spans preserved stock or unallocated padding")
        p = matches[0]
        if (p["p_paddr"] != p["p_vaddr"] or p["p_filesz"] != p["p_memsz"] or
                p["p_offset"] != s["sh_offset"] or
                p["p_flags"] != (4 if s.name == ".ARM.exidx" else 5)):
            raise ValueError("invalid trial load mapping/permissions")
    symbols = e.get_section_by_name(".symtab")
    if symbols is None:
        raise ValueError("trial symbols required")
    functions = []
    for s in symbols.iter_symbols():
        if s.name and s["st_shndx"] == "SHN_UNDEF":
            raise ValueError("unresolved symbol")
        if s["st_info"]["type"] != "STT_FUNC" or not s["st_size"]:
            continue
        start, size = s["st_value"] & ~1, s["st_size"]
        owner = e.get_section(s["st_shndx"]) if isinstance(s["st_shndx"], int) else None
        if (not s["st_value"] & 1 or owner is None or owner.name == ".ARM.exidx" or
                owner.name not in names or not owner["sh_addr"] <= start < start + size <= owner["sh_addr"] + owner["sh_size"] or
                s.name.startswith("proof_") or s.name == "ww_motion_valid"):
            raise ValueError("function outside exact trial code")
        functions.append({"name": s.name, "address": s["st_value"], "bytes": size})
    f = {s["name"]: s for s in functions}
    required = baseline_functions() | {"wsc_commit_health", "wh_retirement_allowed"}
    if not required <= f.keys() or e["e_entry"] != f["wd_init"]["address"]:
        raise ValueError("missing baseline function/integrated candidate or wrong entry")
    objects = {s.name: s for s in symbols.iter_symbols() if s["st_info"]["type"] == "STT_OBJECT"}
    service = "wgd_database" in objects or "wgd_service_uuid" in objects
    if service:
        for name, size in (("wgd_database", 224), ("wgd_service_uuid", 16)):
            if name not in objects or objects[name]["st_size"] != size:
                raise ValueError("incomplete service data candidate")
            s = objects[name]
            owner = e.get_section(s["st_shndx"])
            if owner.name != ".text" or not APPEND <= s["st_value"] < s["st_value"] + size <= owner["sh_addr"] + owner["sh_size"]:
                raise ValueError("service data outside append text/constants")
    try:
        inspect_elf(raw, stock, descriptor)
    except ValueError as exc:
        rejection = str(exc)
    else:
        raise ValueError("production verifier unexpectedly accepted hypothetical holes")
    sections = [{"name": s.name, "address": s["sh_addr"], "bytes": s["sh_size"]} for s in allocated]
    append_end = max(s["sh_addr"] + s["sh_size"] for s in allocated if s.name in (".text", ".ARM.exidx"))
    return {"schema": "whip.unowned-relocation-trial.v1", "elf_sha256": hashlib.sha256(raw).hexdigest(),
            "sections": sections, "functions": functions,
            "hypothetical_stock_text_bytes": sum(size for _, size in expected.values()),
            "occupied_append_bytes": append_end - APPEND, "append_end": append_end,
            "configured_remaining_bytes": END - append_end,
            "total_allocated_bytes": sum(s["bytes"] for s in sections),
            "production_rejection": rejection, "stock_bytes_written": 0,
            "holes_owned": False, "reference_closure_verified": False, "flashable": False,
            "whole_integration_complete": False, "service_database_included": service,
            "required_baseline_functions": sorted(required),
            "additional_functions": sorted(f.keys() - required),
            "hardware_hooks_attached": False, "ram_ownership_verified": False}


def build_trial(output, zig, *, include_service=False):
    """Snapshot, compile current components, link twice, retain diagnostic only."""
    from probe.unified_build import SOURCES
    if len(SOURCES) != 16:
        raise ValueError("review changed component inventory first")
    compiler, zig = shutil.which("clang"), shutil.which(str(zig))
    if not compiler or not zig:
        raise ValueError("Clang and explicit Zig required")
    units = (*SOURCES, "stock_health_commit", "compiler_runtime", *(("stock_service",) if include_service else ()))
    stock_path = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
    descriptor_path = ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
    paths = {str(p.relative_to(ROOT)): p for n in units for p in
             (ROOT / f"firmware/unified/{n}.c", ROOT / f"firmware/unified/{n}.h") if p.exists()}
    for p in (stock_path, descriptor_path, Path(__file__), ROOT / "probe/unified_build.py",
              ROOT / "whip/fwproof_guard.py", ROOT / "whip/fwstock_link.py", BASELINE_ELF,
              ROOT / "requirements-firmware-proof.txt"):
        paths[str(p.relative_to(ROOT))] = p
    # Include already imported local transitive validators, not merely this
    # module and its immediate caller. Root's guarded run additionally pins the
    # explicit test suite, imported harnesses and environment dependencies.
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            p = Path(filename).absolute()
            if p.suffix == ".py" and p.is_relative_to(ROOT):
                paths[str(p.relative_to(ROOT))] = p
    for name in PLACEMENTS:
        paths[f"pinned/{name}.o"] = CHECKPOINT / f"{name}.o"
    source_snapshot = InputSnapshot(paths)
    tools_snapshot = InputSnapshot({"clang": Path(compiler), "zig": Path(zig), "python": Path(sys.executable)})
    if subprocess.check_output([zig, "version"], text=True).strip() != "0.15.2":
        raise ValueError("requires reviewed Zig 0.15.2")
    stock, descriptor = stock_path.read_bytes(), descriptor_path.read_bytes()
    validate_inputs(stock, descriptor)
    for name, (_, size, digest) in PLACEMENTS.items():
        data = (CHECKPOINT / f"{name}.o").read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or _elf(data).get_section_by_name(".text")["sh_size"] != size:
            raise ValueError("pinned whole object changed")
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    script = output / "hypothetical-unowned.ld"
    script.write_text(linker_script())
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding",
             "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fstack-usage",
             "-I", str(ROOT / "firmware/unified")]
    objects = []
    for name in units:
        target = output / f"{name}.o"
        # Compile every current unit, including the four to be relocated. Exact
        # equality with pinned objects establishes unchanged source/header ABI.
        subprocess.run([compiler, *flags, "-c", str(ROOT / f"firmware/unified/{name}.c"), "-o", str(target)], check=True)
        if name in PLACEMENTS:
            if target.read_bytes() != (CHECKPOINT / f"{name}.o").read_bytes():
                raise ValueError("current source/header/tool differs from pinned relocation object: " + name)
        objects.append(target)
    source_snapshot.verify(); tools_snapshot.verify()
    # A data-only C unit has no .su. Allow that only after inspecting its actual
    # allocated object contents and proving that it defines no functions.
    stacks = []
    for obj in objects:
        stack = obj.with_suffix(".su")
        if stack.exists():
            stacks.append(stack)
        elif obj.stem == "stock_service":
            e = _elf(obj.read_bytes())
            if (any(s["st_info"]["type"] == "STT_FUNC" for s in e.get_section_by_name(".symtab").iter_symbols()) or
                    [(s.name, s["sh_size"], s["sh_flags"]) for s in e.iter_sections() if s["sh_flags"] & 2 and s["sh_size"]] != [(".rodata", 240, 2)]):
                raise ValueError("missing stack report for non-data-only candidate")
        else:
            raise ValueError("missing stack report: " + obj.stem)
    artifacts = InputSnapshot({p.name: p for p in [script, *objects, *stacks]})
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"), ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    command = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
               "-Wl,-T," + str(script), "-Wl,-e,wd_init", "-Wl,--build-id=none", "-Wl,--no-undefined",
               "-Wl,-z,max-page-size=4"]
    target = output / "unowned-relocation-NOT-INSTALLABLE.elf"
    invocation = [*command, "-o", str(target), *map(str, objects)]
    result = subprocess.run(invocation, env=env, capture_output=True, text=True)
    if result.returncode:
        # Preserve the actual combined refusal, never change the assertion to
        # manufacture a fitting image. A final linker map is not a successful
        # ELF and does not override a failed link. Unexpected failures still fail.
        expected = "ld.lld: error: configured APP bound exceeded"
        if not include_service or result.stderr.strip() != expected or target.exists():
            raise subprocess.CalledProcessError(result.returncode, invocation,
                                                result.stdout, result.stderr)
        repeat = subprocess.run(invocation, env=env, capture_output=True, text=True)
        if repeat.returncode != result.returncode or repeat.stderr != result.stderr or target.exists():
            raise ValueError("combined link refusal did not reproduce without an ELF")
        failure = output / "link-failure.txt"
        failure.write_text(result.stderr)
        # zig cc's argument bridge does not forward -Map; the same executable
        # exposes its embedded LLD directly. This is a SECOND, also-failed
        # diagnostic invocation, not a replacement successful toolchain/link.
        map_path = output / "failed-link.map"
        mapped = subprocess.run([zig, "ld.lld", "-T", str(script), "-e", "wd_init",
                                 "--build-id=none", "--no-undefined", "-z", "max-page-size=4",
                                 "-Map=" + str(map_path), "-o", str(target), *map(str, objects)],
                                env=env, capture_output=True, text=True)
        if mapped.returncode != result.returncode or mapped.stderr.strip() != expected or target.exists():
            raise ValueError("map diagnostic no longer reproduces the same refusal")
        map_failure = output / "map-link-failure.txt"
        map_failure.write_text(mapped.stderr)
        map_sections = [{"name": m[3], "address": int(m[0], 16), "bytes": int(m[2], 16)}
                        for m in re.findall(r"^\s*([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+\d+\s+(\.text|\.ARM\.exidx)\s*$",
                                            map_path.read_text(), re.MULTILINE)]
        if sorted(s["name"] for s in map_sections) != [".ARM.exidx", ".text"]:
            raise ValueError("unrecognized diagnostic map sections")
        # LLD 20.1.2 estimates eight bytes per input EXIDX section before its
        # first assignAddresses/ASSERT pass; coalescing happens afterward.
        # This matches the refusal but is source-based analysis, not a trace
        # from an instrumented linker. Never use the final map to bypass it.
        exidx_count = sum(sum(s["sh_type"] == "SHT_ARM_EXIDX" and bool(s["sh_size"])
                              for s in _elf(obj.read_bytes()).iter_sections()) for obj in objects)
        text_end = next(s["address"] + s["bytes"] for s in map_sections if s["name"] == ".text")
        failed_files = InputSnapshot({p.name: p for p in (failure, map_path, map_failure)})
        report = {"schema": "whip.unowned-relocation-refusal.v1",
                  "link_succeeded": False, "expected_bound_refusal": True,
                  "link_exit": result.returncode, "identical_second_refusal": True,
                  "service_database_included": True, "component_count": len(SOURCES),
                  "health_commit_text_bytes": _elf((output / "stock_health_commit.o").read_bytes()).get_section_by_name(".text")["sh_size"],
                  "failed_map_sections": map_sections,
                  "failed_map_append_end": max(s["address"] + s["bytes"] for s in map_sections),
                  "input_exidx_sections": exidx_count,
                  "lld_provisional_unwind_bytes": 8 * exidx_count,
                  "lld_provisional_append_end": text_end + 8 * exidx_count,
                  "refusal_explanation": "matches LLD 20.1.2 initial EXIDX estimate before coalescing; source analysis, not linker instrumentation",
                  "map_is_successful_fit_evidence": False,
                  "inputs_sha256": source_snapshot.hashes, "tools_sha256": tools_snapshot.hashes,
                  "artifacts_sha256": artifacts.hashes | failed_files.hashes,
                  "flashable": False, "holes_owned": False, "reference_closure_verified": False,
                  "whole_integration_complete": False, "hardware_hooks_attached": False,
                  "ram_ownership_verified": False, "stock_bytes_written": 0, "tests_run": False,
                  "warning": "actual bounded link REFUSED despite final-map arithmetic; no ELF or fit approval"}
        for snapshot in (source_snapshot, tools_snapshot, artifacts, failed_files): snapshot.verify()
        with (output / "trial-report.json").open("x") as stream:
            json.dump(report, stream, indent=2)
        return report
    binary = InputSnapshot({target.name: target})
    with tempfile.TemporaryDirectory(prefix="whip-relocation-repeat-") as tmp:
        second = Path(tmp) / target.name
        subprocess.run([*command, "-o", str(second), *map(str, objects)], env=env, check=True)
        if target.read_bytes() != second.read_bytes():
            raise ValueError("nondeterministic diagnostic link")
    for snapshot in (source_snapshot, tools_snapshot, artifacts, binary): snapshot.verify()
    report = inspect_trial(target.read_bytes(), stock, descriptor)
    if report["service_database_included"] != include_service:
        raise ValueError("service inclusion differs from requested trial")
    commit = _elf((output / "stock_health_commit.o").read_bytes()).get_section_by_name(".text")["sh_size"]
    report.update(inputs_sha256=source_snapshot.hashes, tools_sha256=tools_snapshot.hashes,
                  artifacts_sha256=artifacts.hashes | binary.hashes, identical_second_link=True,
                  link_succeeded=True,
                  component_count=len(SOURCES), health_commit_text_bytes=commit,
                  tests_run=False, warning="UNOWNED scattered holes; not production placement or whole integration")
    for snapshot in (source_snapshot, tools_snapshot, artifacts, binary): snapshot.verify()
    with (output / "trial-report.json").open("x") as stream:
        json.dump(report, stream, indent=2)
    return report
