"""Batch the two-frame mailbox, wait hook and owner with 22 pinned objects.

This is an expected REFUSAL, not an image builder. wuw_supervise is real code;
owned storage, stock bindings and clock remain absent. No fake provider,
extra hole, unwind discard, or relaxed
undefined-symbol rule may turn this into a purported firmware fit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import APPEND, END, validate_inputs

ROOT = trial.ROOT
PREVIOUS = ROOT / "firmware/unified/research-20260924-discovery-budget-v1"
PREVIOUS_SHA = "54aa06cb7608519ff14c8e865d82867699dd3256b6f1804ee59e624ee55e53e3"
NEW = ("control_mailbox", "stock_supervisor_wait", "control_owner")
MISSING = {"wco_bound_owner", "wco_bound_stock", "wco_monotonic_ms"}
GATES = (*trial.FALSE_GATES, "hardware_access", "production_admission_enabled",
         "owner_implemented", "supervisor_attached", "mailbox_storage_owned",
         "deadline_guaranteed", "stock_image_constructed")


def prior_inputs():
    manifest, pins = trial.pinned_inputs()
    report_path = PREVIOUS / "budget-report.json"
    if trial._sha(report_path.read_bytes()) != PREVIOUS_SHA:
        raise ValueError("reviewed discovery budget changed")
    report = json.loads(report_path.read_text())
    discovery = PREVIOUS / "discovery.o"
    if trial._sha(discovery.read_bytes()) != report["artifacts_sha256"]["discovery.o"]:
        raise ValueError("pinned discovery object changed")
    for name in ("firmware/unified/discovery.c", "firmware/unified/discovery.h"):
        if trial._sha((ROOT / name).read_bytes()) != report["inputs_sha256"][name]:
            raise ValueError("pinned discovery source changed")
    return manifest, pins | {"discovery": discovery}, report_path


def unresolved_symbols(objects):
    symbols = [s for raw in objects.values()
               for s in trial._elf(raw).get_section_by_name(".symtab").iter_symbols() if s.name]
    defined = {s.name for s in symbols if s["st_shndx"] != "SHN_UNDEF"
               and s["st_info"]["bind"] in ("STB_GLOBAL", "STB_WEAK")}
    return {s.name for s in symbols if s["st_shndx"] == "SHN_UNDEF"} - defined


def build(output, zig):
    manifest, pins, report_path = prior_inputs()
    paths = {str(p.relative_to(ROOT)): p for p in pins.values()}
    for name in (*trial.UNITS, "discovery", *NEW):
        for ext in ("c", "h"):
            relative = f"firmware/unified/{name}.{ext}"
            path = ROOT / relative
            if not path.exists():
                if name == "compiler_runtime" and ext == "h" and relative not in manifest["inputs_sha256"]:
                    continue  # This support unit has no header; no other source is optional.
                raise ValueError("required source missing: " + relative)
            if relative in manifest["inputs_sha256"] and trial._sha(path.read_bytes()) != manifest["inputs_sha256"][relative]:
                raise ValueError("pinned source changed: " + relative)
            paths[relative] = path
    stock = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
    descriptor = ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
    for path in (stock, descriptor, trial.CHECKPOINT / "manifest.json", report_path,
                 Path(__file__), ROOT / "tests/test_owner_wait_budget.py",
                 ROOT / "requirements-firmware-proof.txt"):
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
        raise ValueError("reviewed Clang and explicit Zig required")
    tools = InputSnapshot({"clang": Path(compiler), "zig": Path(linker), "python": Path(sys.executable)})
    if tools.hashes != {n: manifest["tool_executables_sha256"][n] for n in tools.hashes}:
        raise ValueError("reviewed tool executable changed")
    if subprocess.check_output([linker, "version"], text=True).strip() != "0.15.2":
        raise ValueError("reviewed Zig 0.15.2 required")
    validate_inputs(stock.read_bytes(), descriptor.read_bytes())
    source.verify(); tools.verify()
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    (output / "repeat").mkdir()
    artifacts = []

    def snapshot(*files):
        artifacts.append(InputSnapshot({str(p.relative_to(output)): p for p in files}))

    def verify():
        for captured in (source, tools, *artifacts):
            captured.verify()

    compiled = {}
    for name in NEW:
        pair = [output / f"{name}.o", output / "repeat" / f"{name}.o"]
        for obj in pair:
            verify()
            subprocess.run([compiler, *manifest["flags"], "-c", str(ROOT / f"firmware/unified/{name}.c"),
                            "-o", str(obj)], check=True)
            snapshot(obj, obj.with_suffix(".su"))
        verify()
        if any(pair[0].with_suffix(ext).read_bytes() != pair[1].with_suffix(ext).read_bytes()
               for ext in (".o", ".su")):
            raise ValueError("new compilation did not reproduce: " + name)
        compiled[name] = pair[0]
    objects = {n: p.read_bytes() for n, p in (pins | compiled).items()}
    functions, constants, sizes, unwind = trial._inventory(objects)
    undefined = unresolved_symbols(objects)
    if undefined != MISSING:
        raise ValueError("expected only the absent strong physical bindings")
    hook_symbols = trial._elf(objects["stock_supervisor_wait"]).get_section_by_name(".symtab")
    provider = next(s for s in hook_symbols.iter_symbols() if s.name == "wuw_supervise")
    if provider["st_info"]["bind"] != "STB_GLOBAL":
        raise ValueError("supervisor provider must be strong, not weak")
    owner_symbols = trial._elf(objects["control_owner"]).get_section_by_name(".symtab")
    provider = next(s for s in owner_symbols.iter_symbols() if s.name == "wuw_supervise")
    if provider["st_shndx"] == "SHN_UNDEF" or provider["st_info"]["bind"] != "STB_GLOBAL":
        raise ValueError("real supervisor definition required")
    for name in MISSING:
        symbol = next(s for s in owner_symbols.iter_symbols() if s.name == name)
        if symbol["st_shndx"] != "SHN_UNDEF" or symbol["st_info"]["bind"] != "STB_GLOBAL":
            raise ValueError("physical binding must be strong and absent: " + name)
    script = output / "UNOWNED-unchanged-conditional.ld"
    script.write_text(trial.linker_script(sizes))
    snapshot(script)
    linked_objects = [str(p) for p in (pins | compiled).values()]
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"), ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    targets = [output / f"REFUSED-full25-{i}.elf" for i in range(1, 4)]
    map_path = output / "failed-link-NOT-FIT.map"
    commands = [[linker, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
                 "-Wl,-T," + str(script), "-Wl,-e,wd_init", "-Wl,--build-id=none", "-Wl,--no-undefined",
                 "-Wl,-z,max-page-size=4", "-o", str(target), *linked_objects] for target in targets[:2]]
    commands.append([linker, "ld.lld", "-T", str(script), "-e", "wd_init", "--build-id=none",
                     "--no-undefined", "-z", "max-page-size=4", "-Map=" + str(map_path),
                     "-o", str(targets[2]), *linked_objects])
    results = []
    for command, target in zip(commands, targets):
        verify()
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        produced = [p for p in (target, map_path) if p.exists()]
        if produced:
            snapshot(*produced)
        log = output / f"link-{len(results) + 1}.json"
        log.write_text(json.dumps({"command": command, "exit": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        snapshot(log)
        results.append(result)
    verify()
    if any(r.returncode == 0 or any("undefined symbol: " + name not in r.stderr for name in MISSING)
           for r in results):
        raise ValueError("whole link must refuse the missing physical bindings")
    if any(p.exists() for p in targets) or not map_path.exists():
        raise ValueError("expected failed map only, never a full ELF")
    if (results[0].returncode, results[0].stdout, results[0].stderr) != (results[1].returncode, results[1].stdout, results[1].stderr):
        raise ValueError("second link refusal did not reproduce")
    # Pure input-size lower bound: deliberately omits alignment, veneers,
    # linked unwind, and all unimplemented bindings. Not a successful map.
    rodata = sum(s["sh_size"] for raw in objects.values() for s in trial._elf(raw).iter_sections()
                 if s.name == ".rodata")
    moved = sum(sizes[n] for n in trial.PLACEMENTS)
    lower_bound = sum(sizes.values()) + rodata - moved
    report = {"schema": "whip.owner-wait-budget.v2", "object_count": len(objects),
              "function_count": sum(functions.values()), "constant_count": sum(constants.values()),
              "link_succeeded": False, "identical_second_refusal": True, "map_is_successful_fit_evidence": False,
              "unresolved_strong_symbols": sorted(undefined), "new_text_bytes": {n: sizes[n] for n in NEW},
              "input_unwind_bytes": unwind, "hypothetical_stock_text_bytes": moved,
              "append_input_lower_bound_bytes": lower_bound, "configured_append_bytes": END - APPEND,
              "append_lower_bound_over_bytes": max(0, lower_bound - (END - APPEND)),
              "mailbox_storage_bytes": 56, "event_scratch_bytes": 32,
              "control_owner_bytes": 880, "real_control_composition_implemented": True,
              "owner_includes_dispatch_coordinator_and_stop_record": True,
              "stock_bytes_written": 0, "tests_run": False, **{k: False for k in GATES},
              "inputs_sha256": source.hashes, "tools_sha256": tools.hashes, "compiler_flags": manifest["flags"],
              "input_objects": {n: str(p.relative_to(ROOT)) for n, p in pins.items()},
              "artifacts_sha256": {k: v for a in artifacts for k, v in a.hashes.items()},
              "warning": "REFUSED, unowned layout, missing physical bindings; map is NOT FIT evidence; NEVER INSTALL"}
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
    print(json.dumps({k: report[k] for k in ("object_count", "link_succeeded", "new_text_bytes",
                                           "append_input_lower_bound_bytes", "append_lower_bound_over_bytes")}))
    return 2  # Expected refusal is never CLI build success.


if __name__ == "__main__":
    raise SystemExit(main())
