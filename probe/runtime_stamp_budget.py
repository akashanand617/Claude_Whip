"""Offline lossless low16 queue-timestamp experiment, never an image writer.

Copies/changes only generated sources in a fresh evidence directory. The live
runtime, headers, builders and all accepted pins remain untouched. Positive
receipt/queue capacity and every existing cleanup check are preserved. A
successful artificial ARM link is NOT an owned RAM/code layout or firmware.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
import shutil
import subprocess
import sys

from probe.owner_wait_budget import prior_inputs, unresolved_symbols, MISSING
from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import InputSnapshot

ROOT = trial.ROOT
CURRENT = ROOT / "firmware/unified/research-20260925-control-owner-v2"
CURRENT_SHA = "bef0a01786a01e84b4bc998c012375eb70612010013181755d4b423d63e005f0"
EXTRA = ("control_mailbox", "stock_supervisor_wait", "control_owner")
ABI = r'''
#include "control_owner.h"
#include <stddef.h>
unsigned proof_runtime_size(void) { return sizeof(wr_runtime); }
unsigned proof_tap_offset(void) { return offsetof(wr_runtime,tap); }
unsigned proof_layout(unsigned n) {
    switch(n) {
    case 0: return sizeof(wr_runtime);
    case 1: return offsetof(wr_runtime,queued_at);
    case 2: return offsetof(wr_runtime,pending_at);
    case 3: return offsetof(wr_runtime,last_source_at);
    case 4: return offsetof(wr_runtime,have_source);
    case 5: return offsetof(wr_runtime,last_sent);
    case 6: return offsetof(wr_runtime,awaiting_send);
    case 7: return offsetof(wr_runtime,have_sent);
    case 8: return offsetof(wr_runtime,pending);
    case 9: return offsetof(wr_runtime,tap);
    case 10: return sizeof(((wr_runtime *)0)->queued_at[0]);
    case 11: return sizeof(wt_tap);
    case 12: return offsetof(wt_tap,session);
    case 13: return offsetof(wt_tap,head);
    case 14: return offsetof(wt_tap,fault);
    case 15: return sizeof(wco_owner);
    case 16: return sizeof(wd_dispatch);
    case 17: return sizeof(wa_adapter);
    default: return 0;
    }
}
'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("reviewed transformation anchor changed: " + before)
    return text.replace(before, after, 1)


def candidate_sources(bits=16):
    """Exact pinned edits, not a permissive general source-rewriting rule.

    bits=8 is a deliberately UNSAFE negative test mutant. Never production.
    """
    if bits not in (8, 16):
        raise ValueError("only reviewed16 and negative8 experiments")
    header = (ROOT / "firmware/unified/runtime.h").read_text()
    header = replace_once(header,
        "    uint32_t queued_at[WT_CAPACITY], pending_at, last_source_at;",
        f"    uint{bits}_t queued_at[WT_CAPACITY];\n    uint32_t pending_at, last_source_at;")
    if bits == 16:
        header = replace_once(header, "#define WR_MAX_SAMPLE_AGE_MS 250u",
            "#define WR_MAX_SAMPLE_AGE_MS 250u\n"
            "/* A live head has at most31 later successful positive-count offers.\n"
            " * Each advances source by at most249ms; wr_next adds at most249.\n"
            " * Bound:32*249=7968, strictly below the low16 modulus. This\n"
            " * requires runtime-exclusive tap ownership and current cleanup.\n"
            " * Keep pending_at full32: awaiting-send time is not re-encoded. */\n"
            "_Static_assert(WR_MAX_SAMPLE_AGE_MS > 0u, \"positive horizon\");\n"
            "_Static_assert(WT_CAPACITY > 0u && WT_CAPACITY <= UINT8_MAX, \"count fits\");\n"
            "_Static_assert((uint64_t)WT_CAPACITY * (WR_MAX_SAMPLE_AGE_MS - 1u) <= UINT16_MAX,\n"
            "               \"live FIFO ages must fit losslessly in low16\");")
    source = (ROOT / "firmware/unified/runtime.c").read_text()
    source = replace_once(source,
        "r->queued_at[(slot + i) % WT_CAPACITY] = oldest_at;",
        f"r->queued_at[(slot + i) % WT_CAPACITY] = (uint{bits}_t)oldest_at;")
    source = replace_once(source,
        "(uint32_t)(now - r->queued_at[r->tap.head]) >= WR_MAX_SAMPLE_AGE_MS",
        f"(uint{bits}_t)(now - r->queued_at[r->tap.head]) >= WR_MAX_SAMPLE_AGE_MS")
    source = replace_once(source,
        "r->pending_at = r->queued_at[r->tap.head];",
        f"r->pending_at = now - (uint{bits}_t)(now - r->queued_at[r->tap.head]);")
    owner = replace_once((ROOT / "firmware/unified/control_owner.c").read_text(),
        "sizeof(wco_owner) == 880", f"sizeof(wco_owner) == {880 - (4 - bits // 8) * 32}")
    return {"runtime.h": header, "runtime.c": source, "control_owner.c": owner}


def check_stack_pair(pair):
    """Only an actually functionless/nonexecuting object may lack Clang .su."""
    a, b = pair
    if a.read_bytes() != b.read_bytes():
        raise ValueError("object compilation does not repeat")
    reports = [p.with_suffix(".su") for p in pair]
    if reports[0].exists() != reports[1].exists():
        raise ValueError("stack report presence differs")
    if reports[0].exists():
        if reports[0].read_bytes() != reports[1].read_bytes():
            raise ValueError("stack report compilation does not repeat")
        return True
    elf = trial._elf(a.read_bytes())
    executable = any((s["sh_flags"] & 6) == 6 and s["sh_size"] for s in elf.iter_sections())
    functions = any(s["st_info"]["type"] == "STT_FUNC" and s["st_shndx"] != "SHN_UNDEF"
                    for s in elf.get_section_by_name(".symtab").iter_symbols())
    if executable or functions:
        raise ValueError("executable object is missing its stack report")
    return False


def build(output: Path, zig: str):
    manifest, old, previous = prior_inputs()
    current_path = CURRENT / "budget-report.json"
    if trial._sha(current_path.read_bytes()) != CURRENT_SHA:
        raise ValueError("current whole25 reference changed")
    current = json.loads(current_path.read_text())
    pins = old | {name: CURRENT / (name + ".o") for name in EXTRA}
    for name in EXTRA:
        if trial._sha(pins[name].read_bytes()) != current["artifacts_sha256"][name + ".o"]:
            raise ValueError("current object pin changed")
    paths = {str(p.relative_to(ROOT)): p for p in pins.values()}
    for name, expected in current["inputs_sha256"].items():
        p = ROOT / name
        if trial._sha(p.read_bytes()) != expected:
            raise ValueError("current source/reference changed: " + name)
        paths[name] = p
    # This function builds only; its report deliberately does not claim tests.
    # The executing test fixture/guarded launcher snapshots its own test source.
    for p in (current_path, previous, Path(__file__),
              ROOT / "tests/native/arm_proof.ld", ROOT / "whip/fwthumb.py"):
        paths[str(p.relative_to(ROOT))] = p
    inputs = InputSnapshot(paths)
    clang, linker = shutil.which("clang"), shutil.which(str(zig))
    if not clang or not linker:
        raise ValueError("reviewed tools required")
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(linker), "python": Path(sys.executable)})
    if tools.hashes != {k: manifest["tool_executables_sha256"][k] for k in tools.hashes}:
        raise ValueError("reviewed tools changed")
    if subprocess.check_output([linker, "version"], text=True).strip() != "0.15.2":
        raise ValueError("reviewed Zig required")
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    snapshots, commands = [], []

    def verify():
        for item in (inputs, tools, *snapshots):
            item.verify()

    def capture(*files):
        snapshots.append(InputSnapshot({str(p.relative_to(output)): p for p in files}))

    def write(p, value):
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("x") as stream:
            stream.write(value)
        capture(p)

    def run(command, *, env=None, input=None, success=True, outputs=()):
        verify()
        result = subprocess.run(command, env=env, input=input, text=True, capture_output=True)
        # Capture each produced file before logs or another command can touch it.
        produced = [p for p in outputs if p.exists()]
        if produced:
            capture(*produced)
        log = output / f"command-{len(commands):03}.json"
        write(log, json.dumps({"command": command, "exit": result.returncode,
                               "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        commands.append(log)
        if success and result.returncode:
            raise ValueError(result.stderr)
        return result

    raw = {name: path.read_bytes() for name, path in pins.items()}
    baseline_inventory = trial._inventory(raw)
    compiled = {}
    for variant in ("reference", "low16", "negative8"):
        directory = output / variant
        directory.mkdir()
        if variant != "reference":
            for name, value in candidate_sources(16 if variant == "low16" else 8).items():
                write(directory / name, value)
        include = [] if variant == "reference" else ["-include", str(directory / "runtime.h")]
        names = tuple(pins) if variant == "low16" else ("runtime",)
        objects = {}
        for name in names:
            source = directory / (name + ".c")
            if not source.exists():
                source = ROOT / f"firmware/unified/{name}.c"
            pair = [directory / (name + suffix) for suffix in (".o", "-repeat.o")]
            for obj in pair:
                run([clang, *manifest["flags"], *include, "-c", str(source), "-o", str(obj)],
                    outputs=(obj, obj.with_suffix(".su")))
            check_stack_pair(pair)
            objects[name] = pair[0]
        if variant == "reference" and objects["runtime"].read_bytes() != raw["runtime"]:
            raise ValueError("fresh reference compile differs from pin")
        abi_pair = [directory / ("proof_abi" + suffix) for suffix in (".o", "-repeat.o")]
        for obj in abi_pair:
            run([clang, *manifest["flags"], *include, "-x", "c", "-", "-c", "-o", str(obj)], input=ABI,
                outputs=(obj, obj.with_suffix(".su")))
        if any(abi_pair[0].with_suffix(ext).read_bytes() != abi_pair[1].with_suffix(ext).read_bytes()
               for ext in (".o", ".su")):
            raise ValueError("ABI repeat differs")
        dependencies = [pins[name] for name in ("mode_controller", "sample_tap", "compiler_runtime")]
        env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
                   ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
        elfs = [directory / name for name in ("ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
        for elf in elfs:
            run([linker, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
                 "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,-e,wr_init",
                 "-Wl,--build-id=none", "-Wl,--no-undefined", "-o", str(elf),
                 str(objects["runtime"]), *map(str, dependencies), str(abi_pair[0])], env=env, outputs=(elf,))
        if elfs[0].read_bytes() != elfs[1].read_bytes():
            raise ValueError("artificial link repeat differs")
        compiled[variant] = {"objects": objects, "elf": elfs[0]}
    candidate = {name: path.read_bytes() for name, path in compiled["low16"]["objects"].items()}
    funcs, constants, sizes, unwind = trial._inventory(candidate)
    names = lambda inv: Counter((name, binding) for (name, size, binding), count in inv.items()
                                for _ in range(count))
    if names(funcs) != names(baseline_inventory[0]):
        raise ValueError("public or local function inventory changed")
    if constants != baseline_inventory[1] or unresolved_symbols(candidate) != MISSING:
        raise ValueError("constants or required physical bindings changed")
    script = output / "UNCHANGED-UNOWNED-geometry.ld"
    write(script, trial.linker_script(sizes))
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "link-cache"),
               ZIG_LOCAL_CACHE_DIR=str(output / "link-local"))
    refusals = []
    for i in range(2):
        target = output / f"REFUSED-whole25-{i}.elf"
        result = run([linker, "ld.lld", "-T", str(script), "-e", "wd_init", "--build-id=none",
                      "--no-undefined", "-z", "max-page-size=4", "-o", str(target),
                      *map(str, compiled["low16"]["objects"].values())], env=env, success=False)
        if not result.returncode or target.exists() or any(
                "undefined symbol: " + name not in result.stderr for name in MISSING):
            raise ValueError("whole candidate must refuse missing bindings, not link")
        refusals.append(result.stderr)
    if refusals[0] != refusals[1]:
        raise ValueError("strict link refusal differs")
    rodata = sum(s["sh_size"] for obj in candidate.values() for s in trial._elf(obj).iter_sections()
                 if s.name == ".rodata")
    lower = sum(sizes.values()) + rodata - sum(sizes[n] for n in trial.PLACEMENTS)
    report = {
        "schema": "whip.runtime-stamp16-budget.v1", "warning": "EXPERIMENT ONLY; NEVER INSTALL",
        "reference_elf": str(compiled["reference"]["elf"]),
        "candidate_elf": str(compiled["low16"]["elf"]),
        "negative_elf": str(compiled["negative8"]["elf"]),
        "mutant_elf": str(compiled["negative8"]["elf"]),
        "inputs_sha256": inputs.hashes, "tools_sha256": tools.hashes,
        "artifacts_sha256": {k: v for item in snapshots for k, v in item.hashes.items()},
        "compiler_flags": manifest["flags"], "object_count": len(candidate),
        "function_count": sum(funcs.values()), "constant_count": sum(constants.values()),
        "runtime_text_before": baseline_inventory[2]["runtime"], "runtime_text_after": sizes["runtime"],
        "text_sizes": sizes, "input_unwind_bytes": unwind,
        "changed_objects": [n for n in candidate if candidate[n] != raw[n]],
        "append_input_lower_bound_bytes": lower, "append_lower_bound_over_bytes": max(0, lower - 9520),
        "hypothetical_stock_text_bytes": sum(sizes[n] for n in trial.PLACEMENTS),
        "persistent_ram_saving_bytes": 64, "persistent_planning_bytes": 1244 - 64,
        "unchanged_queue_capacity": 32, "live_head_maximum_age_ms": 32 * 249,
        "strict_missing_binding_refusal": True, "original_core_changed": False,
        "hardware_access": False, "flashable": False, "whole_code_fit_proven": False,
        "ram_ownership_proven": False, "tests_run": False,
        "limits": "Fresh generated variant only; runtime-exclusive initialized state and existing cleanup required. Pending timestamp stays32. Arithmetic7968 bound is not physical clock/cadence qualification. Proof ELFs are artificial, production pointers/clock absent. All safety/recovery/continuity gates remain open."
    }
    verify()
    with (output / "budget-report.json").open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    return report
