"""Measure a UART-multiplexed/FEE7-retired layout; never build firmware.

This experiment keeps stock UART/DFU/DIS/HID and all Health components. It
omits only the unattached replacement-service/discovery units, retains only the
existing-UART 20-byte send wrapper, uses the separately tested compact dispatcher,
and places selected function sections in the gross surveyed FEE7 spans. The
ingress and clock bindings are fake size fixtures, so a fit is only a lead,
never production placement or flash approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from probe.owner_wait_budget import prior_inputs
from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import InputSnapshot

PARENT = ROOT / "firmware/unified/research-20260925-whole28-flags-rejected-v2"
PARENT_REPORT_SHA = "8cdcd42e778304624c48e809243c723314e8c53b0abfc197f365d1997d4b94e1"
EXPERIMENT = ROOT / "firmware/unified/experiments"
LINKER = EXPERIMENT / "uart_mux_measure.ld"
FUNCTION_SOURCES = ("adapter", "control_mailbox", "runtime", "sample_tap",
                    "stock_optical_work")
OMITTED = {"discovery", "stock_discovery_read", "stock_event_gate",
           "stock_legacy_gate", "stock_service", "stock_service_slot",
           "stock_transport"}
CANDIDATES = {
    "dispatch": EXPERIMENT / "dispatch_compact.c",
    "stock_uart_mux": EXPERIMENT / "stock_uart_mux.c",
    "stock_transport": EXPERIMENT / "uart_notify_only.c",
    "size-bindings": EXPERIMENT / "uart_mux_size_bindings.c",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--zig", type=Path, required=True)
    args = parser.parse_args()
    report_path = PARENT / "measurements.json"
    if sha(report_path) != PARENT_REPORT_SHA:
        raise ValueError("reviewed whole-28 parent changed")
    parent = json.loads(report_path.read_text())
    manifest, pins, _ = prior_inputs()
    if len(pins) != 22:
        raise ValueError("historical base inventory changed")
    baseline = PARENT / "baseline"
    current_names = {p.stem for p in baseline.glob("*.o")} - {"size-bindings"}
    if len(current_names) != 28 or not OMITTED < current_names:
        raise ValueError("whole-28 object inventory changed")
    for name in current_names:
        path = baseline / f"{name}.o"
        key = f"baseline/{name}.o"
        if sha(path) != parent["artifacts_sha256"][key]:
            raise ValueError("parent object changed: " + name)

    sources = {name: ROOT / f"firmware/unified/{name}.c" for name in FUNCTION_SOURCES}
    paths = {str(report_path.relative_to(ROOT)): report_path,
             str(Path(__file__).relative_to(ROOT)): Path(__file__),
             str(LINKER.relative_to(ROOT)): LINKER}
    copied_names = current_names - OMITTED - set(FUNCTION_SOURCES) - set(CANDIDATES)
    for name in copied_names:
        p = baseline / f"{name}.o"
        paths[str(p.relative_to(ROOT))] = p
    for p in (*sources.values(), *CANDIDATES.values()):
        paths[str(p.relative_to(ROOT))] = p
    for header in (ROOT / "firmware/unified").glob("*.h"):
        paths[str(header.relative_to(ROOT))] = header
    inputs = InputSnapshot(paths)
    tools = InputSnapshot({"clang": Path("/usr/bin/clang"),
                           "zig": args.zig.resolve(), "python": Path(sys.executable)})
    expected_tools = {name: manifest["tool_executables_sha256"][name]
                      for name in tools.hashes}
    if tools.hashes != expected_tools:
        raise ValueError("reviewed tools changed")
    if subprocess.check_output([args.zig, "version"], text=True).strip() != "0.15.2":
        raise ValueError("reviewed Zig required")

    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    artifacts: dict[str, str] = {}
    snapshots = [inputs, tools]
    command_index = 0

    def verify() -> None:
        for snapshot in snapshots:
            snapshot.verify()

    def capture(path: Path) -> None:
        key = str(path.relative_to(output))
        snapshots.append(InputSnapshot({key: path}))
        artifacts[key] = sha(path)

    def run(command: list[str]) -> None:
        nonlocal command_index
        verify()
        result = subprocess.run(command, text=True, capture_output=True, env=env)
        log = output / f"command-{command_index:03}.json"
        command_index += 1
        log.write_text(json.dumps({"command": command, "exit": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        capture(log)
        if result.returncode:
            raise RuntimeError(result.stderr)

    flags = list(manifest["flags"])
    builds = [output / "first", output / "repeat"]
    for directory in builds:
        directory.mkdir()
        for name in sorted(copied_names):
            shutil.copyfile(baseline / f"{name}.o", directory / f"{name}.o")
            capture(directory / f"{name}.o")
        for name, source in sources.items():
            obj = directory / f"{name}.o"
            run(["/usr/bin/clang", *flags, "-ffunction-sections", "-c",
                 str(source), "-o", str(obj)])
            capture(obj)
            if obj.with_suffix(".su").exists():
                capture(obj.with_suffix(".su"))
        for name, source in CANDIDATES.items():
            obj = directory / f"{name}.o"
            run(["/usr/bin/clang", *flags, "-c", str(source), "-o", str(obj)])
            capture(obj)
            if obj.with_suffix(".su").exists():
                capture(obj.with_suffix(".su"))
    for name in sorted((current_names - OMITTED) | set(CANDIDATES)):
        a, b = (directory / f"{name}.o" for directory in builds)
        if a.read_bytes() != b.read_bytes():
            raise ValueError("candidate compile did not reproduce: " + name)

    elfs = []
    maps = []
    for index, directory in enumerate(builds):
        target = output / f"MEASUREMENT-ONLY-uart-mux-{index}.elf"
        map_path = output / f"MEASUREMENT-ONLY-uart-mux-{index}.map"
        objects = sorted(directory.glob("*.o"))
        run([str(args.zig), "ld.lld", "-T", str(LINKER), "-e", "wd_init",
             "--build-id=none", "-z", "max-page-size=4", *map(str, objects),
             "-Map=" + str(map_path), "-o", str(target)])
        capture(target); capture(map_path)
        elfs.append(target); maps.append(map_path)
    if elfs[0].read_bytes() != elfs[1].read_bytes():
        raise ValueError("UART-mux link did not reproduce")

    elf = trial._elf(elfs[0].read_bytes())
    text = elf.get_section_by_name(".text")
    unwind = elf.get_section_by_name(".ARM.exidx")
    occupied = unwind["sh_addr"] + unwind["sh_size"] - 0x847AD0
    linked = {"append_text_bytes": text["sh_size"],
              "linked_unwind_bytes": unwind["sh_size"],
              "append_occupied_bytes": occupied,
              "configured_bytes": 9520, "margin_bytes": 9520 - occupied}
    if linked != {"append_text_bytes": 9384, "linked_unwind_bytes": 16,
                  "append_occupied_bytes": 9400, "configured_bytes": 9520,
                  "margin_bytes": 120}:
        raise ValueError("UART-mux measurement changed")
    expected_sections = {
        ".fee7_helper": (0x82DB44, 42), ".fee7_indicate": (0x82DB70, 14),
        ".fee7_confirm": (0x82DB82, 36), ".fee7_read": (0x82DBA6, 160),
        ".fee7_write": (0x82DC50, 110), ".fee7_cccd": (0x82DCC0, 76),
        ".fee7_add": (0x82DD10, 60), ".fee7_database": (0x8442C0, 252),
        ".fee7_callbacks": (0x8443BC, 10),
    }
    for name, (address, size) in expected_sections.items():
        section = elf.get_section_by_name(name)
        if not section or (section["sh_addr"], section["sh_size"]) != (address, size):
            raise ValueError("FEE7 trial section changed: " + name)
    symbols = elf.get_section_by_name(".symtab")
    names = {symbol.name for symbol in symbols.iter_symbols()}
    if not {"wlg_receive", "wg_stock_notify20", "wum_post20", "wd_init"} <= names:
        raise ValueError("UART-mux required symbol missing")
    if names & {"wg_stock_add", "wdi_encode", "wdi_read", "wdr_read",
                "wge_common", "wgs_replace_fee7", "wgs_callbacks", "wgs_service_id"}:
        raise ValueError("replacement-service symbol survived UART-mux link")
    verify()
    result = {
        "schema": "whip.rejected-uart-mux-compact-fit-lead.v1",
        "inputs_sha256": inputs.hashes, "tools_sha256": tools.hashes,
        "artifacts_sha256": artifacts, "linked": linked,
        "whole28_artificial_baseline_occupied_bytes": 10844,
        "baseline_over_bytes": 1324,
        "omitted_replacement_service_objects": sorted(OMITTED),
        "gross_fee7_bytes_surveyed": 790,
        "fee7_trial_text_bytes_placed": sum(size for _, size in expected_sections.values()),
        "fake_ingress_binding_text_bytes": 2,
        "fake_clock_text_bytes": 4,
        "exact_existing_uart_notify_text_bytes": 48,
        "uart_mux_text_bytes": 92,
        "compact_dispatch_text_bytes": 1120,
        "accepted_dispatch_text_bytes": 1202,
        "compact_dispatch_savings_bytes": 82,
        "accepted_source_changed": False, "production_elf": False,
        "hardware_access": False, "stock_bytes_written": 0,
        "physical_bindings_implemented": False, "flashable": False,
        "fit_proven": False, "adopted": False,
        "limits": "Expanded measurement linker uses nine previously unowned historical holes and all gross surveyed FEE7 spans without proving complete FEE7 reference retirement or ownership. Replacement service/discovery units are omitted and selected current sources are rebuilt with function sections. The compact dispatcher retains stale unreachable request/reply bytes until the next accepted request/reply overwrite; it needs explicit acceptance before replacing the zeroizing source. UART ingress and clock are fake six-byte functions; no original connection generation, callback drain, arrival time, send-buffer lifetime, status handshake, app migration, physical Health, recovery, OTA or target behavior is supplied. The artificial link has only120 bytes margin, so it is not a production fit or image.",
    }
    verify()
    report_out = output / "measurements.json"
    report_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    capture(report_out); verify()
    print(json.dumps({"archive": str(output), "report_sha256": sha(report_out),
                      "linked": linked, "artifacts": len(artifacts)}))


if __name__ == "__main__":
    main()
