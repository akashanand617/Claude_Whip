"""Build/test OFFLINE Cortex-M0+ objects and a TEST ELF; never emit an OTA image.

python -m probe.unified_build --output /tmp/whip-unified-offline-new-directory
Requires requirements-firmware-proof.txt, Clang, Swift and Zig's linker.
Output must not exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from whip.fwlayout import audit_layout
from whip.fwindicator import audit_indicators
from whip.fwfifo_trace import audit_capture
from whip.fwplacement import assess_placement
from whip.fwproof_guard import InputSnapshot, load_proof_report, sanitized_pytest_env
from whip.fwunified import audit_stock

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("mode_controller", "sample_tap", "runtime", "health_adapter", "fresh_source", "adapter",
           "stock_binding", "wire", "dispatch", "stock_transport", "stock_timer_fence", "stock_health_timers",
           "stock_schedule_settings", "stock_result_commit", "stock_optical_work", "stock_optical_io")
# Reproducible objects only: these do NOT enter either main ELF. Their focused
# tests retain separate incomplete layouts and the unchanged whole-link gate.
# Archiving a candidate must never disguise it inside the fitting subtotal.
UNLINKED_CANDIDATES = ("stock_health_commit", "stock_service", "stock_coordinator", "stock_legacy_gate")
SUPPORT_SOURCES = ("tests/native/arm_proof_runtime.c", "tests/native/adapter_proof.c",
                   "tests/native/wire_proof.c", "tests/native/dispatch_proof.c",
                   "tests/native/sample_tap_reference.c")
TESTS = ("tests/test_fwcontinuity.py", "tests/test_sample_tap.py", "tests/test_fwunified.py",
         "tests/test_unified_thumb.py", "tests/test_fwcommands.py",
         "tests/test_fwhealth_lifecycle.py", "tests/test_fwlayout.py", "tests/test_fwproof_guard.py",
         "tests/test_fwcapacity.py", "tests/test_health_adapter.py", "tests/test_fresh_source.py",
         "tests/test_unified_adapter.py", "tests/test_fwcapacity_read.py", "tests/test_fwcapacity_cli.py",
         "tests/test_fwcapacity_archive.py",
         "tests/test_unified_wire.py", "tests/test_unified_dispatch.py",
         "tests/test_fwplacement.py", "tests/test_fwfifo_trace.py", "tests/test_fwstock_binding.py",
         "tests/test_fwtransport.py", "tests/test_fwrom_read.py", "tests/test_fwrom_archive.py",
         "tests/test_fwrom_timer_stop.py", "tests/test_fwboot_read.py", "tests/test_fwboot_archive.py",
         "tests/test_fwrom_integration.py", "tests/test_fwrom_integration_archive.py", "tests/test_fwstock_link.py",
         "tests/test_fwrom_integration_success_archive.py", "tests/test_fwrom_execution.py", "tests/test_fwrom_fence.py",
         "tests/test_stock_health_timers.py",
         "tests/test_tap_storage.py",
         "tests/test_fwindicator.py",
         "tests/test_stock_schedule_settings.py",
         "tests/test_stock_result_commit.py",
         "tests/test_stock_optical_work.py",
         "tests/test_stock_optical_io.py",
         "tests/test_stock_switch.py",
         "tests/test_source_storage.py",
         "tests/test_stock_health_commit.py",
         "tests/test_stock_service.py",
         "tests/test_stock_coordinator.py",
         "tests/test_stock_legacy_gate.py",
         "tests/test_raw_retirement.py",
         "tests/test_indicator_relocation.py",
         "tests/test_fwrom_resume.py",
         "tests/test_fwrom_rearm.py",
         "tests/test_fwrom_resume_archive.py",
         "tests/test_fwrom_resume_execution.py",
         "tests/test_fwrom_support.py",
         "tests/test_fwrom_support_archive.py",
         "tests/test_fwrom_support_execution.py",
         "tests/test_fwrom_hook.py",
         "tests/test_fwrom_hook_archive.py",
         "tests/test_fwrom_hook_execution.py",
         "tests/test_fwoptical_dispatch.py",
         "tests/test_fwoptical_acquisition.py",
         "tests/test_fwoptical_samples.py",
         "tests/test_status_notification.py",
         "tests/test_idle_notifications.py")
INPUTS = (
    "firmware/unified/build-20260924-integrated-switch-v1/unified-test-only.elf",
    "firmware/unified/build-20260924-parallel-integration-v1/stock-address/stock-append-NOT-INSTALLABLE.elf",
    *(f"firmware/unified/build-20260924-parallel-integration-v1/stock-address/{name}.o"
      for name in ("compiler_runtime", "stock_binding", "stock_result_commit", "stock_schedule_settings")),
    "firmware/rt02cr-stock-3.12.02.bin", "whip/__init__.py", "probe/__init__.py", "tests/__init__.py",
    "whip/fwbuild.py", "whip/fwunified.py", "whip/fwcontinuity.py", "whip/fwthumb.py",
    "whip/fwcommands.py", "whip/fwhealth_lifecycle.py", "whip/fwlayout.py",
    "whip/fwproof_guard.py", "probe/unified_build.py", "requirements-firmware-proof.txt",
    "whip/fwcapacity.py", "whip/fwhealth_adapter.py", "whip/fwcapacity_read.py",
    "probe/capacity_read.py", "whip/fwidentity.py", "whip/fwoptical.py", "whip/protocol.py",
    "whip/fwplacement.py", "whip/fwfifo_trace.py", "whip/fwstock_binding.py",
    "whip/fwtransport.py",
    "whip/fwindicator.py",
    "whip/fwrelocation_trial.py",
    "whip/fwhealth_schedule.py",
    "whip/fwrom_read.py", "whip/fwboot_read.py", "probe/rom_read.py", "whip/fwrom_integration.py",
    "whip/fwrom_execution.py",
    "whip/fwrom_resume.py",
    "whip/fwrom_support.py",
    "whip/fwrom_hook.py",
    "whip/fwoptical_dispatch.py",
    "whip/fwoptical_acquisition.py",
    "whip/fwoptical_samples.py",
    "whip/fwoptical_io.py",
    "probe/stock_link.py", "whip/fwstock_link.py", "firmware/unified/stock_append.ld",
    "probe/idle_notifications.py",
    "firmware/unified/compiler_runtime.c",
    "firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-boot.json",
    "firmware/research/2026-09-23/reference-boot/rtl8762e-sdk-timer-hook.json",
    "firmware/research/2026-09-23/boot-reference/boot-reference.json",
    "firmware/research/2026-09-23/boot-reference/transcript.jsonl",
    "firmware/research/2026-09-23/rom-integration-aborted/transcript.jsonl",
    "firmware/research/2026-09-23/rom-integration/rom-integration.json",
    "firmware/research/2026-09-23/rom-integration/transcript.jsonl",
    "firmware/research/2026-09-23/rom-timer-resume/rom-timer-resume-code.json",
    "firmware/research/2026-09-23/rom-timer-resume/transcript.jsonl",
    "firmware/research/2026-09-23/rom-support/rom-support.json",
    "firmware/research/2026-09-23/rom-support/transcript.jsonl",
    "firmware/research/2026-09-23/rom-create-hook-aborted/transcript.jsonl",
    "firmware/research/2026-09-23/rom-create-hook/rom-create-hook.json",
    "firmware/research/2026-09-23/rom-create-hook/transcript.jsonl",
    "firmware/research/2026-09-22/rom_symbol_gcc.axf",
    "firmware/research/2026-09-23/rom-timers/rom-timers.json",
    "firmware/research/2026-09-23/rom-timers/transcript.jsonl",
    "firmware/research/2026-09-23/rom-timer-internals/rom-timer-internals.json",
    "firmware/research/2026-09-23/rom-timer-internals/transcript.jsonl",
    "firmware/research/2026-09-23/rom-timer-hooks/rom-timer-hooks.json",
    "firmware/research/2026-09-23/rom-timer-hooks/transcript.jsonl",
    "whip/accel.py", "ios/R02Ring/Health/RingProtocol.swift",
    "ios/R02Ring/Gesture/GestureInference.swift",
    "ios/R02Ring/Health/UnifiedWire.swift",
    "ios/R02Ring/Health/UnifiedMode.swift",
    "firmware/research/2026-09-22/captures/check_1790071705479474000.jsonl",
    "firmware/research/2026-09-22/captures/firmware_validation_1790114546989490000.jsonl",
    "firmware/research/2026-09-23/bank0-descriptor/configuration.json",
    "firmware/research/2026-09-23/bank0-descriptor/report.json",
    "firmware/research/2026-09-23/bank0-descriptor/transcript.jsonl",
    "firmware/rt02cr-25hz.bin", "firmware/rt02cr-25hz-optical-off-v2-experimental.bin",
    *TESTS, "tests/native/sample_tap_stress.c", "tests/native/mode_controller_stress.c",
    "tests/native/health_adapter_stress.c", "tests/native/fresh_source_stress.c",
    "tests/native/dispatch_stress.c",
    *SUPPORT_SOURCES, "tests/native/arm_proof.ld",
    *(f"firmware/unified/{name}.{ext}" for name in SOURCES for ext in ("c", "h")),
    *(f"firmware/unified/{name}.{ext}" for name in UNLINKED_CANDIDATES for ext in ("c", "h")),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_info(path):
    from elftools.elf.elffile import ELFFile

    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != \
                (32, True, "EM_ARM", "ET_REL"):
            raise ValueError("not an ARM32 little-endian relocatable object")
        sizes = {s.name: s["sh_size"] for s in elf.iter_sections() if s["sh_flags"] & 2}
        undefined = sorted({s.name for s in elf.get_section_by_name(".symtab").iter_symbols()
                            if s.name and s["st_shndx"] == "SHN_UNDEF"})
    return {"sha256": digest(path), "allocated_section_bytes": sizes,
            "unresolved_symbols": undefined,
            "warning": "relocations unresolved; no stock placement or RAM reservation"}


def object_stack_report(path):
    """Clang emits no .su for a data-only object; never waive executable reports."""
    from elftools.elf.elffile import ELFFile

    report = path.with_suffix(".su")
    if report.is_file():
        return report
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if any(s["sh_size"] and s["sh_flags"] & 2 and s["sh_flags"] & 4
               for s in elf.iter_sections()):
            raise ValueError("missing stack report for executable object")
        symbols = elf.get_section_by_name(".symtab")
        if symbols is None or any(s["st_info"]["type"] == "STT_FUNC" and
                                  s["st_shndx"] != "SHN_UNDEF"
                                  for s in symbols.iter_symbols()):
            raise ValueError("missing stack report for function-bearing object")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zig", type=Path, help="Zig 0.15.2 toolchain executable (or set WHIP_ZIG)")
    args = parser.parse_args()
    try:
        import unicorn  # noqa: F401 — fail BEFORE producing artifacts if missing
        import elftools  # noqa: F401
        import pytest  # noqa: F401
    except ImportError as exc:
        parser.error(f"{exc}; install requirements-firmware-proof.txt in an isolated environment")
    compiler = shutil.which("clang")
    if not compiler:
        parser.error("Clang with ARMv6-M backend is required")
    swiftc = os.environ.get("WHIP_SWIFTC")
    if not swiftc:
        xcrun = shutil.which("xcrun")
        if xcrun:
            result = subprocess.run([xcrun, "--find", "swiftc"], capture_output=True, text=True)
            if result.returncode == 0:
                swiftc = result.stdout.strip()
        swiftc = swiftc or shutil.which("swiftc")
    swiftc = shutil.which(swiftc) if swiftc else None
    if not swiftc:
        parser.error("Swift compiler required for actual checked-in app decoder parity")
    swift_sdk = os.environ.get("WHIP_SWIFT_SDKROOT")
    if not swift_sdk and shutil.which("xcrun"):
        result = subprocess.run([shutil.which("xcrun"), "--show-sdk-path"],
                                capture_output=True, text=True)
        if result.returncode == 0:
            swift_sdk = result.stdout.strip()
    if not swift_sdk:
        parser.error("macOS SDK required; provide WHIP_SWIFT_SDKROOT or configure xcrun")
    swift_sdk = Path(swift_sdk).resolve()
    sdk_settings = swift_sdk / "SDKSettings.json"
    if not sdk_settings.is_file():
        parser.error("resolved Swift SDK must include SDKSettings.json")
    zig = str(args.zig.resolve()) if args.zig else os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not zig:
        parser.error("provide --zig or WHIP_ZIG for the linked ARM proof; no skipped execution tests allowed")
    zig = shutil.which(zig)
    if not zig:
        parser.error("Zig executable not found")
    # Baselines precede compilation. Hashing only after tests could attest an
    # edited source against an older object. This is a drift check, not a lock.
    sources = InputSnapshot({p: ROOT / p for p in INPUTS})
    tool_files = InputSnapshot({"clang": Path(compiler), "swiftc": Path(swiftc), "zig": Path(zig),
                                "python": Path(sys.executable)})
    sdk_files = InputSnapshot({"swift_sdk_settings": sdk_settings})

    def verify_inputs():
        sources.verify()
        tool_files.verify()
        sdk_files.verify()

    if subprocess.check_output([zig, "version"], text=True).strip() != "0.15.2":
        parser.error("linked proof currently pins Zig 0.15.2; validate a new toolchain before changing it")
    stock_path = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
    audit = audit_stock(stock_path.read_bytes())
    if audit.errors:
        parser.error("; ".join(audit.errors))
    layout = audit_layout(stock_path.read_bytes())
    indicators = audit_indicators(stock_path.read_bytes())
    capacity_capture = json.loads((ROOT /
        "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_text())
    placement = assess_placement(stock_path.read_bytes(), capacity_capture)
    fifo_audits = [audit_capture(ROOT / "firmware/research/2026-09-22/captures" / name)
                  for name in ("check_1790071705479474000.jsonl",
                               "firmware_validation_1790114546989490000.jsonl")]
    verify_inputs()
    out = args.output.resolve()
    if out.exists():
        parser.error("output already exists; choose a new directory (nothing overwritten)")
    out.mkdir()
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
             "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11",
             "-Wall", "-Wextra", "-Werror", "-fstack-usage", "-I", str(ROOT / "firmware/unified")]
    objects = {}
    compiled_snapshots = []
    units = [(name, ROOT / "firmware/unified" / (name + ".c")) for name in SOURCES]
    units += [(name, ROOT / "firmware/unified" / (name + ".c")) for name in UNLINKED_CANDIDATES]
    units += [(Path(path).stem, ROOT / path) for path in SUPPORT_SOURCES]
    compiled_files = []
    for name, source in units:
        target = out / (name + ".o")
        command = [compiler, *flags, "-c", str(source), "-o", str(target)]
        subprocess.run(command, check=True)
        report = object_stack_report(target)
        files = (target, report) if report else (target,)
        compiled_files.extend(files)
        snapshot = InputSnapshot({p.name: p for p in files})
        with tempfile.TemporaryDirectory(prefix="whip-rebuild-") as tmp:
            second = Path(tmp) / target.name
            subprocess.run([compiler, *flags, "-c", str(source), "-o", str(second)], check=True)
            if target.read_bytes() != second.read_bytes():
                raise RuntimeError(f"non-reproducible object: {name}")
        objects[name] = object_info(target)
        objects[name]["role"] = ("offline component" if name in SOURCES else
                                 "unlinked candidate only" if name in UNLINKED_CANDIDATES else
                                 "test support only")
        objects[name]["identical_second_build"] = True
        objects[name]["per_function_stack_report"] = report.read_text().splitlines() if report else []
        objects[name]["stack_report_kind"] = ("compiler report" if report else
                                               "verified data-only object; no functions or executable bytes")
        snapshot.verify()
        compiled_snapshots.append(snapshot)
        verify_inputs()
    for snapshot in compiled_snapshots:
        snapshot.verify()
    verify_inputs()
    test_elf = out / "unified-test-only.elf"
    link_inputs = [str(out / (name + ".o")) for name, _ in units if name not in UNLINKED_CANDIDATES]
    link_flags = ["cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
                  "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,-e,wr_init",
                  "-Wl,--build-id=none", "-Wl,--no-undefined"]
    env = dict(os.environ, WHIP_ZIG=zig, WHIP_SWIFTC=swiftc,
               WHIP_SWIFT_SDKROOT=str(swift_sdk),
               ZIG_GLOBAL_CACHE_DIR=str(out / "zig-cache"),
               ZIG_LOCAL_CACHE_DIR=str(out / "zig-local"))
    subprocess.run([zig, *link_flags, "-o", str(test_elf), *link_inputs], env=env, check=True)
    elf_snapshot = InputSnapshot({test_elf.name: test_elf})
    with tempfile.TemporaryDirectory(prefix="whip-relink-") as tmp:
        second = Path(tmp) / test_elf.name
        subprocess.run([zig, *link_flags, "-o", str(second), *link_inputs], env=env, check=True)
        if test_elf.read_bytes() != second.read_bytes():
            raise RuntimeError("non-reproducible test ELF link")
    for snapshot in (*compiled_snapshots, elf_snapshot):
        snapshot.verify()
    verify_inputs()
    # Independently link production components at their proposed stock append
    # addresses. Still no hooks, static RAM allocation, container or OTA image.
    from probe.stock_link import build as build_stock_address
    stock_out = out / "stock-address"
    stock_link = build_stock_address(stock_out, zig)
    from whip.fwthumb import RuntimeThumb
    arm_sizes = RuntimeThumb(test_elf.read_bytes())
    component_ram = {name: arm_sizes.call(symbol) for name, symbol in (
        ("sample_tap", "proof_tap_size"), ("runtime", "proof_runtime_size"),
        ("adapter", "proof_adapter_size"), ("dispatcher", "proof_dispatch_context_size"),
        ("dispatcher_and_frame", "proof_dispatch_size"), ("timer_fence", "proof_timer_fence_size"),
        ("source_profile", "proof_source_profile_size"),
        ("source_receipt", "proof_source_receipt_size"),
        ("source_delivery", "proof_source_delivery_size"))}
    stock_elf = stock_out / "stock-append-NOT-INSTALLABLE.elf"
    stock_files = [stock_out / name for name in stock_link["artifacts_sha256"]]
    stock_files.append(stock_out / "link-report.json")
    # Budget all implemented candidates TOGETHER, without proof scaffolding.
    # This is deliberately a real failed link, not omitted zero-cost glue or
    # an expanded test region being described as a fitting production image.
    complete = out / "full-candidates-REFUSED.elf"
    complete_objects = [str(out / (n + ".o")) for n in (*SOURCES, *UNLINKED_CANDIDATES)]
    complete_objects.append(str(stock_out / "compiler_runtime.o"))
    refusal = subprocess.run([zig, "cc", "-target", "thumb-freestanding-eabi",
        "-mcpu=cortex_m0plus", "-nostdlib", "-Wl,-T," + str(ROOT / "firmware/unified/stock_append.ld"),
        "-Wl,-e,wd_init", "-Wl,--build-id=none", "-Wl,--no-undefined", "-Wl,-z,max-page-size=4",
        "-o", str(complete), *complete_objects], env=env, capture_output=True, text=True)
    def capacity_refusal(result):
        lines = result.stderr.strip().splitlines()
        return result.returncode != 0 and lines and all(re.fullmatch(
            r"ld\.lld: error: section .+ will not fit in region 'append': overflowed by [0-9]+ bytes",
            line) for line in lines) and not complete.exists()
    if not capacity_refusal(refusal):
        raise RuntimeError("full-candidate capacity outcome changed; review before accepting: " + refusal.stderr)
    refusal_file = out / "full-candidates-link-refusal.txt"
    with refusal_file.open("x") as stream:
        stream.write(refusal.stderr)
    compiled_snapshots.append(InputSnapshot({refusal_file.name: refusal_file}))
    failed_map = out / "full-candidates-failed-link.map"
    mapped = subprocess.run([zig, "ld.lld", "-T", str(ROOT / "firmware/unified/stock_append.ld"),
        "-e", "wd_init", "--build-id=none", "--no-undefined", "-z", "max-page-size=4",
        "-Map=" + str(failed_map), "-o", str(complete), *complete_objects],
        env=env, capture_output=True, text=True)
    if not capacity_refusal(mapped):
        raise RuntimeError("full-candidate map did not reproduce capacity refusal: " + mapped.stderr)
    compiled_snapshots.append(InputSnapshot({failed_map.name: failed_map}))
    map_refusal_file = out / "full-candidates-map-refusal.txt"
    with map_refusal_file.open("x") as stream:
        stream.write(mapped.stderr)
    compiled_snapshots.append(InputSnapshot({map_refusal_file.name: map_refusal_file}))
    mapped_sections = [{"name": match[3], "address": int(match[0], 16), "bytes": int(match[2], 16)}
        for match in re.findall(
            r"^\s*([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+\d+\s+(\.text|\.ARM\.exidx)\s*$",
            failed_map.read_text(), re.MULTILINE)]
    if sorted(s["name"] for s in mapped_sections) != [".ARM.exidx", ".text"]:
        raise RuntimeError("unrecognized full-candidate failed-link map")
    full_candidate_budget = {"link_succeeded": False, "elf_emitted": False,
        "map_is_successful_fit_evidence": False, "flashable": False,
        "components": list(SOURCES), "included_candidates": list(UNLINKED_CANDIDATES),
        "failed_map_sections": mapped_sections,
        "warning": "all implemented components/candidates still omit real hardware/service/source hooks; unknown costs are not zero"}
    budget_files = (refusal_file, failed_map, map_refusal_file)
    from whip.fwoptical_io import sample_io_report
    io_plan = sample_io_report(stock_path.read_bytes(), stock_elf.read_bytes(), (ROOT /
        "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes())
    io_plan_file = out / "optical-io-call-plan.json"
    with io_plan_file.open("x") as stream:
        stream.write(json.dumps(io_plan, indent=2) + "\n")
    # Separate, production-REJECTED layouts only. These do not modify either
    # main ELF, stock bytes, approved storage or the production linker/verifier.
    # Archive both actual layouts instead of treating arithmetic as final fit.
    from whip.fwrelocation_trial import build_trial
    relocation_trials, relocation_files = {}, []
    for label, include_service in (("baseline", False), ("service", True)):
        directory = out / ("unowned-relocation-" + label)
        trial = build_trial(directory, zig, include_service=include_service)
        if (trial["flashable"] or trial["holes_owned"] or trial["whole_integration_complete"] or
                (trial["link_succeeded"] and not trial["production_rejection"]) or
                (not trial["link_succeeded"] and not trial["expected_bound_refusal"])):
            raise RuntimeError("diagnostic relocation unexpectedly became approved")
        relocation_trials[label] = trial
        relocation_files.extend(directory / p for p in trial["artifacts_sha256"])
        relocation_files.append(directory / "trial-report.json")
    verify_inputs()
    artifacts = InputSnapshot({str(p.relative_to(out)): p
                               for p in (*compiled_files, test_elf, *stock_files, *budget_files, io_plan_file,
                                         *relocation_files)})
    junit = out / "tests.xml"
    collected, executed = out / "collected.json", out / "executed.json"
    command = [sys.executable, "-m", "pytest", "-q", "-c", os.devnull, "--noconftest",
               "-o", "addopts=", "-p", "whip.fwproof_guard", "--rootdir", str(ROOT), *TESTS]
    # Prove identical collection AND passing setup/call/teardown for every test;
    # inherited PYTEST_ADDOPTS, plugins, or repo config cannot filter the gate.
    env = sanitized_pytest_env(env)
    env["WHIP_UNIFIED_TEST_ELF"] = str(test_elf)
    env["WHIP_STOCK_LINK_ELF"] = str(stock_elf)
    subprocess.run([*command, "--collect-only", "--proof-report", str(collected)],
                   cwd=ROOT, env=env, check=True)
    collection_snapshot = InputSnapshot({"collected.json": collected})
    collection = load_proof_report(collected, phase="collection")
    collection_snapshot.verify()
    verify_inputs()
    artifacts.verify()
    subprocess.run([*command, "--proof-expected", str(collected), "--proof-report", str(executed),
                    f"--junitxml={junit}"], cwd=ROOT, env=env, check=True)
    reports = InputSnapshot({p.name: p for p in (collected, executed, junit)})
    execution = load_proof_report(executed, phase="execution")
    if execution["collected"] != collection["collected"]:
        raise RuntimeError("test identities changed between collection and execution")
    suites = ET.parse(junit).getroot().iter("testsuite")
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.get(key, "0"))
    if counts["skipped"] or counts["failures"] or counts["errors"] or not counts["tests"]:
        raise RuntimeError(f"incomplete offline proof: {counts}")
    if counts["tests"] != len(collection["collected"]):
        raise RuntimeError("JUnit and identity reports disagree on test count")
    reports.verify()
    verify_inputs()
    artifacts.verify()
    for snapshot in (*compiled_snapshots, elf_snapshot):
        snapshot.verify()
    collection_snapshot.verify()
    manifest = {
        "artifact_type": "offline-objects-test-elf-and-stock-address-components", "flashable": False,
        "stock_linked": False, "hardware_access": False,
        "stock_audit": audit.as_dict(), "stock_layout_audit": layout,
        "stock_indicator_audit": indicators,
        "stock_placement_audit": placement, "archived_fifo_audits": fifo_audits,
        "objects": objects, "tests": counts,
        "unlinked_candidates": {name: {
            "in_main_test_elf": False, "in_stock_address_components": False,
            "warning": "object-only archive; focused tests do not establish whole-image fit or placement",
        } for name in UNLINKED_CANDIDATES},
        "stock_address_components": stock_link,
        "full_candidate_budget": full_candidate_budget,
        "unowned_relocation_trials": relocation_trials,
        "optical_io_call_plan": io_plan,
        "arm_context_bytes": component_ram,
        "ram_ownership_verified": False,
        "test_elf": {"sha256": artifacts.hashes[test_elf.name], "identical_second_link": True,
                     "code_address": "0x01000000", "linker_zig_version": "0.15.2",
                     "linker_executable_sha256": tool_files.hashes["zig"],
                     "warning": "artificial test layout, never stock-linked or installable"},
        "test_scope": "selected stock Thumb + native C + artificial and real-address ARM components; NOT complete stock candidate",
        "compiler": subprocess.check_output([compiler, "--version"], text=True).strip(),
        "swift_compiler": subprocess.check_output([swiftc, "--version"], text=True).strip(),
        "swift_sdk": {"path": str(swift_sdk), "settings_sha256": sdk_files.hashes["swift_sdk_settings"],
                      "warning": "SDK metadata fingerprint, not a hermetic hash of every library/header"},
        "flags": flags, "inputs_sha256": sources.hashes,
        "tool_executables_sha256": tool_files.hashes,
        "artifacts_sha256": artifacts.hashes, "proof_reports_sha256": reports.hashes,
        "test_identities": collection["collected"],
        "proof_integrity": "snapshots checked between stages; identical ordered test collection; no deselection, skip or xfail",
        "proof_limits": "not a filesystem lock or hermetic toolchain; no full boot, ROM, hardware, RTOS or physical timing proof",
    }
    verify_inputs()
    artifacts.verify()
    collection_snapshot.verify()
    reports.verify()
    with (out / "manifest.json").open("x") as stream:
        stream.write(json.dumps(manifest, indent=2) + "\n")
    print(f"Offline objects, test ELF and proof report: {out}; NOT FLASHABLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
