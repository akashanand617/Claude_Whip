"""Actual six-argument ARM discovery callback, no registration or physical BLE.

Identity/ID are explicit artificial storage. The actual encoder initializes the
fixture before publication; no fixed production boot identity/provider is added.
"""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile
import pytest

from probe.owner_wait_budget import prior_inputs, unresolved_symbols, MISSING
from tests.test_stock_service_slot import ROOT, STOCK, DESCRIPTOR, CURRENT, CURRENT_SHA, BINDINGS
from whip import fwraw_relocation_trial as trial
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb

ARCHIVE = ROOT / "firmware/unified/research-20260925-wechat-routing-v1"
ARCHIVE_SHA = "8048944469be3727f3ec78f74672d3bcf5a3a9e83c6893fb4fb357aaf8725f02"
GATE_REPORT_SHA = "cff16be1b3ec48d107ebdd8e34a52e88857df3c6cf5e63dab07e1fbfb9ff0f1b"
OWNED = RuntimeThumb.CONTEXT + 448
IDENTITY = RuntimeThumb.CONTEXT + 464
LENGTH, VALUE = RuntimeThumb.CONTEXT + 496, RuntimeThumb.CONTEXT + 500
ABI = f'''
/* TEST ONLY: artificial storage, initialized by actual wdi_encode in tests. */
#include "stock_discovery_read.h"
#include "runtime.h"
_Static_assert(sizeof(wr_runtime) <= 448, "disjoint actual runtime fixture");
__asm__(".global wgs_service_id\\n.set wgs_service_id, {OWNED:#x}");
__asm__(".global wdr_identity\\n.set wdr_identity, {IDENTITY:#x}");
unsigned proof_runtime_size(void) {{ return 512; }}
unsigned proof_runtime_state_size(void) {{ return sizeof(wr_runtime); }}
'''


@pytest.fixture(scope="module")
def read_build(tmp_path_factory):
    manifest, pins, previous = prior_inputs()
    current_path = CURRENT / "budget-report.json"
    assert hashlib.sha256(current_path.read_bytes()).hexdigest() == CURRENT_SHA
    current = json.loads(current_path.read_text())
    archive_path = ARCHIVE / "proof-supplement.json"
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == ARCHIVE_SHA
    archive = json.loads(archive_path.read_text())
    gate_path = ARCHIVE / "executed-proof/stock-event-gate0/event-gate-code-report.json"
    assert hashlib.sha256(gate_path.read_bytes()).hexdigest() == GATE_REPORT_SHA
    gate = json.loads(gate_path.read_text())
    for name in ("control_mailbox", "stock_supervisor_wait", "control_owner"):
        pins[name] = CURRENT / (name + ".o")
        assert hashlib.sha256(pins[name].read_bytes()).hexdigest() == current["artifacts_sha256"][name + ".o"]
    for name, relative in {
        "stock_service_slot": "executed-proof/stock-service-slot1/stock_service_slot.o",
        "stock_event_gate": "executed-proof/stock-event-gate0/stock_event_gate.o",
    }.items():
        pins[name] = ARCHIVE / relative
        assert hashlib.sha256(pins[name].read_bytes()).hexdigest() == archive["artifacts_sha256"][relative]
    paths = {}
    for name, digest in gate["inputs_sha256"].items():
        if Path(name).is_absolute(): continue  # Old temporary artifacts are not dependencies; archived objects above are.
        p = ROOT / name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
        paths[name] = p
    for p in (*pins.values(), current_path, archive_path, gate_path, previous, Path(__file__),
              ROOT / "docs/UNIFIED_GATT_READ_BINDING.md", ROOT / "whip/fwthumb.py",
              ROOT / "firmware/unified/stock_discovery_read.c",
              ROOT / "firmware/unified/stock_discovery_read.h"):
        paths[str(p.relative_to(ROOT))] = p
    for module in tuple(sys.modules.values()):
        p = Path(getattr(module, "__file__", "") or "/").absolute()
        if p.suffix == ".py" and p.is_relative_to(ROOT): paths[str(p.relative_to(ROOT))] = p
    inputs = InputSnapshot(paths)
    clang, zig = shutil.which("clang"), shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    assert clang and zig, "reviewed compilers required, never skip"
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig), "python": Path(sys.executable)})
    assert tools.hashes == {name: manifest["tool_executables_sha256"][name] for name in tools.hashes}
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    directory = tmp_path_factory.mktemp("stock-discovery-read")
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    artifacts = []

    def verify():
        for captured in (inputs, tools, *artifacts): captured.verify()

    def snapshot(*files):
        artifacts.append(InputSnapshot({str(p.relative_to(directory)): p for p in files}))

    def run(command, outputs=(), source=None, success=True):
        verify()
        result = subprocess.run(command, input=source, text=True, capture_output=True, env=env)
        produced = [p for p in outputs if p.exists()]
        if produced: snapshot(*produced)
        log = directory / f"command-{len(artifacts):03}.json"
        log.write_text(json.dumps({"command": command, "exit": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        snapshot(log)
        if success: assert result.returncode == 0, result.stderr
        return result

    compiled = {}
    for name in ("stock_discovery_read", "proof_only_read_bindings"):
        pair = [directory / (name + suffix) for suffix in (".o", "-repeat.o")]
        for obj in pair:
            source = ["-x", "c", "-"] if name.startswith("proof_") else [str(ROOT / f"firmware/unified/{name}.c")]
            run([clang, *manifest["flags"], "-c", *source, "-o", str(obj)],
                outputs=(obj, obj.with_suffix(".su")), source=ABI if name.startswith("proof_") else None)
        assert all(pair[0].with_suffix(ext).read_bytes() == pair[1].with_suffix(ext).read_bytes()
                   for ext in (".o", ".su"))
        compiled[name] = pair[0]
    pins["stock_discovery_read"] = compiled["stock_discovery_read"]
    production = {name: p.read_bytes() for name, p in pins.items()}
    missing = MISSING | BINDINGS | {"wdr_identity"}
    assert unresolved_symbols(production) == missing
    obj = ELFFile(BytesIO(production["stock_discovery_read"]))
    for name in ("wgs_service_id", "wdr_identity"):
        sym, = obj.get_section_by_name(".symtab").get_symbol_by_name(name)
        assert sym["st_shndx"] == "SHN_UNDEF" and sym["st_info"]["bind"] == "STB_GLOBAL"
    assert not any(s["sh_size"] and s["sh_flags"] & 3 == 3 for s in obj.iter_sections())
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
            "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,--build-id=none", "-Wl,--no-undefined"]
    target = directory / "MISSING-IDENTITY-AND-ID-REFUSED.elf"
    result = run([*link, "-Wl,-e,wdr_read", "-o", str(target), str(pins["stock_discovery_read"])], success=False)
    assert result.returncode and not target.exists()
    assert all("undefined symbol: " + name in result.stderr for name in ("wdr_identity", "wgs_service_id"))
    minimal = [pins[name] for name in ("runtime", "mode_controller", "sample_tap", "compiler_runtime",
                                      "wire", "discovery", "stock_discovery_read")]
    elfs = [directory / name for name in ("READ-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for target in elfs:
        run([*link, "-Wl,-e,wr_init", "-o", str(target), *map(str, minimal),
             str(compiled["proof_only_read_bindings"])], outputs=(target,))
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    functions, constants, sizes, unwind = trial._inventory(production)
    script = directory / "UNCHANGED-UNOWNED-geometry.ld"
    script.write_text(trial.linker_script(sizes)); snapshot(script)
    for index in range(2):
        target = directory / f"FULL28-REFUSED-{index}.elf"
        result = run([zig, "ld.lld", "-T", str(script), "-e", "wd_init", "--no-undefined",
                      "--build-id=none", "-z", "max-page-size=4", "-o", str(target),
                      *map(str, pins.values())], success=False)
        assert result.returncode and not target.exists()
        assert all("undefined symbol: " + name in result.stderr for name in missing)
    rodata = sum(s["sh_size"] for raw in production.values() for s in trial._elf(raw).iter_sections()
                 if s.name == ".rodata")
    lower = sum(sizes.values()) + rodata - sum(sizes[name] for name in trial.PLACEMENTS)
    stack = {}
    for line in pins["stock_discovery_read"].with_suffix(".su").read_text().splitlines():
        label, amount, kind = line.split("\t"); assert kind == "static"
        stack[label.rsplit(":", 1)[-1]] = int(amount)
    report = {
        "schema": "whip.stock-discovery-read-code.v1", "inputs_sha256": inputs.hashes,
        "tools_sha256": tools.hashes, "artifacts_sha256": {k: v for a in artifacts for k, v in a.hashes.items()},
        "compiler_flags": manifest["flags"], "object_count": len(production),
        "function_count": sum(functions.values()), "constant_count": sum(constants.values()),
        "read_text_bytes": sizes["stock_discovery_read"], "read_input_unwind_bytes": obj.get_section_by_name(".ARM.exidx")["sh_size"],
        "local_stack_bytes": stack, "whole_input_unwind_bytes": unwind,
        "append_input_lower_bound_bytes": lower, "append_lower_bound_over_bytes": lower - 9520,
        "missing_strong_bindings": sorted(missing), "identity_bytes_already_planned": 20,
        "additional_callback_constant_bytes": 12, "additional_owned_service_id_bytes": 1,
        "new_owned_storage_bytes": 0, "stock_bytes_written": 0, "reclaimed_bytes_approved": 0,
        "flashable": False, "hardware_access": False, "whole_code_fit_proven": False, "tests_run": False,
        "limits": "Unattached six-argument read callback; no service callback table, write/CCCD, stack/provider or production allocation. Boot owner must successfully encode fresh qualified identity before ID publication and never rewrite while borrowed. Mutable storage declaration permits initialization, not runtime mutation; read returns const borrowed pointer. No parser, ID generator, mode/session/capability action, or real stack-lifetime proof. Missing output0x411 is source-supported application policy, not measured on-ring behavior. Eight-object artificial ARM proof; strict full28 refuses six strong bindings. Existing20 identity bytes not double-counted. NEVER INSTALL.",
    }
    verify()
    report_path = directory / "discovery-read-code-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n"); snapshot(report_path)
    verify()
    yield {"elf": elfs[0].read_bytes(), "report": report, "directory": directory}
    verify()


@pytest.fixture
def arm(read_build):
    h = RuntimeThumb(read_build["elf"])
    h.invoke("wr_init")
    assert h.word(0) == 0 and h.call("proof_runtime_state_size") == 408
    h.uc.mem_write(OWNED, b"\xff")
    return h


def initialize(h, owned=3, boot=0xFEDCBA9876543210, build=0x1020304050607080):
    assert h.call("wdi_encode", IDENTITY, boot & 0xFFFFFFFF, boot >> 32,
                  build & 0xFFFFFFFF, build >> 32) == 1
    h.uc.mem_write(OWNED, bytes([owned]))  # TEST ONLY boot-owner publication fixture.
    return b"WI\1\0" + struct.pack("<QQ", boot, build)


def outputs(h):
    return struct.unpack("<H", h.uc.mem_read(LENGTH, 2))[0], struct.unpack("<I", h.uc.mem_read(VALUE, 4))[0]


def read(h, connection=3, service=3, index=7, offset=0, length=LENGTH, value=VALUE):
    return h.call("wdr_read", connection, service, index, offset, length, value)


def test_read_whole28_budget_strong_bindings_and_production_refusal(read_build):
    r = read_build["report"]
    assert (r["object_count"], r["function_count"], r["constant_count"]) == (28, 149, 3)
    assert r["append_input_lower_bound_bytes"] == 10706 + r["read_text_bytes"]
    assert r["append_lower_bound_over_bytes"] == 1186 + r["read_text_bytes"]
    assert r["new_owned_storage_bytes"] == 0 and r["identity_bytes_already_planned"] == 20
    with pytest.raises(ValueError): inspect_elf(read_build["elf"], STOCK.read_bytes(), DESCRIPTOR.read_bytes())


@pytest.mark.parametrize("owned,connection", [(0, 0), (3, 3), (254, 254), (3, 255)])
def test_actual_six_argument_read_returns_stable_encoded_view_without_mode_change(arm, owned, connection):
    expected = initialize(arm, owned=owned)
    before = bytes(arm.uc.mem_read(arm.CONTEXT, 512))
    for _ in range(3):
        assert read(arm, connection=connection, service=owned) == 0
        assert outputs(arm) == (20, IDENTITY)
        assert bytes(arm.uc.mem_read(IDENTITY, 20)) == expected
    after = bytes(arm.uc.mem_read(arm.CONTEXT, 512))
    changed = set(range(496, 498)) | set(range(500, 504))
    assert all(a == b for i, (a, b) in enumerate(zip(before, after)) if i not in changed)
    assert arm.word(0) == 0 and arm.word(4) == 0  # Actual runtime remains Health/no action.


@pytest.mark.parametrize("service,owned", [(255, 3), (3, 255), (255, 255), (2, 3), (254, 0)])
def test_invalid_or_unpublished_service_clears_outputs_without_identity_read(arm, service, owned):
    arm.uc.mem_write(OWNED, bytes([owned]))
    reads = []
    arm.uc.hook_add(arm.u.UC_HOOK_MEM_READ, lambda uc, access, address, size, value, opaque:
                    reads.append((address, size)))
    assert read(arm, service=service) == 0x40A
    assert outputs(arm) == (0, 0)
    assert bytes(arm.uc.mem_read(IDENTITY, 20)) == b"\xa5" * 20
    assert all(address + size <= IDENTITY or address >= IDENTITY + 20 for address, size in reads)


@pytest.mark.parametrize("index", [0, 2, 4, 5, 6, 8, 0xFFFF])
def test_other_attributes_refused_with_both_outputs_cleared(arm, index):
    expected = initialize(arm)
    assert read(arm, index=index) == 0x40A and outputs(arm) == (0, 0)
    assert bytes(arm.uc.mem_read(IDENTITY, 20)) == expected


@pytest.mark.parametrize("offset", [1, 19, 20, 21, 0x100, 0xFFFF])
def test_all_supported_width_nonzero_offsets_refused_without_slicing(arm, offset):
    initialize(arm)
    assert read(arm, offset=offset) == 0x407 and outputs(arm) == (0, 0)


@pytest.mark.parametrize("length,value", [(0, VALUE), (LENGTH, 0), (0, 0)])
def test_null_output_arguments_clear_each_remaining_slot(arm, length, value):
    expected = initialize(arm)
    assert read(arm, length=length, value=value) == 0x411
    assert outputs(arm) == (0 if length else 0xA5A5, 0 if value else 0xA5A5A5A5)
    assert bytes(arm.uc.mem_read(IDENTITY, 20)) == expected


def test_failed_encoder_does_not_publish_and_later_success_can_be_borrowed(arm):
    assert arm.call("wdi_encode", IDENTITY, 0, 0, 1, 0) == 0
    assert read(arm) == 0x40A and outputs(arm) == (0, 0)
    assert bytes(arm.uc.mem_read(IDENTITY, 20)) == b"\xa5" * 20
    expected = initialize(arm, boot=1, build=2)
    assert read(arm) == 0 and outputs(arm) == (20, IDENTITY)
    assert bytes(arm.uc.mem_read(IDENTITY, 20)) == expected


def test_output_slots_are_exact_halfword_and_word_not_a_struct_write(arm):
    initialize(arm)
    assert read(arm) == 0
    assert bytes(arm.uc.mem_read(LENGTH - 2, 2)) == b"\xa5" * 2
    assert bytes(arm.uc.mem_read(LENGTH + 2, 2)) == b"\xa5" * 2
    assert bytes(arm.uc.mem_read(VALUE + 4, 8)) == b"\xa5" * 8
    assert read(arm, offset=1) == 0x407 and outputs(arm) == (0, 0)
    assert bytes(arm.uc.mem_read(LENGTH + 2, 2)) == b"\xa5" * 2
