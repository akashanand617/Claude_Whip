"""Actual stock five-service setup with one emulator-only FEE7 call edit.

Callback bodies, stack registration and assigned-ID uniqueness are fixtures.
This is no GATT binding, source retirement, physical discovery or installable
firmware. Accepted sources/pins, stock files and production lists are unchanged.
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
from whip import fwraw_relocation_trial as trial
from whip.fwcontinuity import BIAS, ProofError
from whip.fwoptical_io import _bl
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwtransport import StockTransportHarness, DATA

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
DESCRIPTOR = ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"
CURRENT = ROOT / "firmware/unified/research-20260925-control-owner-v2"
CURRENT_SHA = "bef0a01786a01e84b4bc998c012375eb70612010013181755d4b423d63e005f0"
OWNED_ID, CALLBACKS, EVENT = DATA + 32, DATA + 64, DATA + 128
OLD_SLOT = 0x209E1E
CALLBACK_SELECTOR = 0x209DF7
BINDINGS = {"wgs_service_id", "wgs_callbacks"}
ABI = f'''
/* TEST ONLY: artificial owned byte/table and NEVER-CALLED callback fixtures. */
#include "stock_service_slot.h"
__asm__(".global wgs_service_id\\n.set wgs_service_id, {OWNED_ID:#x}");
__asm__(".global wgs_callbacks\\n.set wgs_callbacks, {CALLBACKS:#x}");
void wr_init(void) {{}}
unsigned proof_read_callback_fixture(void) {{ return 0xdead; }}
unsigned proof_write_callback_fixture(void) {{ return 0xdead; }}
unsigned proof_cccd_callback_fixture(void) {{ return 0xdead; }}
'''


@pytest.fixture(scope="module")
def slot_build(tmp_path_factory):
    manifest, pins, previous = prior_inputs()
    current_path = CURRENT / "budget-report.json"
    assert hashlib.sha256(current_path.read_bytes()).hexdigest() == CURRENT_SHA
    current = json.loads(current_path.read_text())
    for name in ("control_mailbox", "stock_supervisor_wait", "control_owner"):
        pins[name] = CURRENT / (name + ".o")
        assert hashlib.sha256(pins[name].read_bytes()).hexdigest() == current["artifacts_sha256"][name + ".o"]
    paths = {n: ROOT / n for n in current["inputs_sha256"]}
    assert InputSnapshot(paths).hashes == current["inputs_sha256"]
    for p in (*pins.values(), current_path, previous, Path(__file__),
              ROOT / "tests/native/arm_proof.ld", STOCK, DESCRIPTOR,
              ROOT / "firmware/unified/stock_service_slot.c",
              ROOT / "firmware/unified/stock_service_slot.h"):
        paths[str(p.relative_to(ROOT))] = p
    for module in tuple(sys.modules.values()):
        p = Path(getattr(module, "__file__", "") or "/").absolute()
        if p.suffix == ".py" and p.is_relative_to(ROOT):
            paths[str(p.relative_to(ROOT))] = p
    inputs = InputSnapshot(paths)
    clang, zig = shutil.which("clang"), shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    assert clang and zig, "pinned compiler/linker required, never skip"
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig), "python": Path(sys.executable)})
    assert tools.hashes == {n: manifest["tool_executables_sha256"][n] for n in tools.hashes}
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    directory = tmp_path_factory.mktemp("stock-service-slot")
    artifacts = []

    def verify():
        for snapshot in (inputs, tools, *artifacts): snapshot.verify()

    def snapshot(*files):
        artifacts.append(InputSnapshot({str(p.relative_to(directory)): p for p in files}))

    def run(command, outputs=(), source=None, success=True):
        verify()
        result = subprocess.run(command, input=source, text=True, env=env, capture_output=True)
        produced = [p for p in outputs if p.exists()]
        if produced: snapshot(*produced)
        log = directory / f"command-{len(artifacts):03}.json"
        log.write_text(json.dumps({"command": command, "exit": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        snapshot(log)
        if success: assert result.returncode == 0, result.stderr
        return result

    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    objects = []
    for name in ("stock_service_slot", "proof_only_slot_bindings"):
        pair = [directory / (name + suffix) for suffix in (".o", "-repeat.o")]
        for obj in pair:
            source = ["-x", "c", "-"] if name.startswith("proof_") else [str(ROOT / f"firmware/unified/{name}.c")]
            run([clang, *manifest["flags"], "-c", *source, "-o", str(obj)],
                outputs=(obj, obj.with_suffix(".su")), source=ABI if name.startswith("proof_") else None)
        assert all(pair[0].with_suffix(ext).read_bytes() == pair[1].with_suffix(ext).read_bytes()
                   for ext in (".o", ".su"))
        objects.append(pair[0])
    production = {n: p.read_bytes() for n, p in pins.items()} | {"stock_service_slot": objects[0].read_bytes()}
    assert unresolved_symbols(production) == MISSING | BINDINGS
    objelf = ELFFile(BytesIO(objects[0].read_bytes()))
    for name in BINDINGS:
        sym, = objelf.get_section_by_name(".symtab").get_symbol_by_name(name)
        assert sym["st_shndx"] == "SHN_UNDEF" and sym["st_info"]["bind"] == "STB_GLOBAL"
    minimal = [pins["stock_transport"], pins["stock_service"], objects[0]]
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
            "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,--build-id=none", "-Wl,--no-undefined"]
    refused = directory / "NO-OWNED-SLOT-BINDINGS-REFUSED.elf"
    result = run([*link, "-Wl,-e,wgs_replace_fee7", "-o", str(refused), *map(str, minimal)], success=False)
    assert result.returncode and not refused.exists()
    assert all("undefined symbol: " + name in result.stderr for name in BINDINGS)
    elfs = [directory / n for n in ("SLOT-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for target in elfs:
        run([*link, "-Wl,-e,wr_init", "-o", str(target), *map(str, minimal), str(objects[1])], outputs=(target,))
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    functions, constants, sizes, unwind = trial._inventory(production)
    script = directory / "UNCHANGED-UNOWNED-geometry.ld"
    script.write_text(trial.linker_script(sizes)); snapshot(script)
    for index in range(2):
        target = directory / f"FULL26-REFUSED-{index}.elf"
        result = run([zig, "ld.lld", "-T", str(script), "-e", "wd_init", "--no-undefined",
                      "--build-id=none", "-z", "max-page-size=4", "-o", str(target),
                      *map(str, pins.values()), str(objects[0])], success=False)
        assert result.returncode and not target.exists()
        assert all("undefined symbol: " + name in result.stderr for name in MISSING | BINDINGS)
    rodata = sum(s["sh_size"] for raw in production.values() for s in trial._elf(raw).iter_sections()
                 if s.name == ".rodata")
    lower = sum(sizes.values()) + rodata - sum(sizes[n] for n in trial.PLACEMENTS)
    stack = {}
    for line in objects[0].with_suffix(".su").read_text().splitlines():
        label, amount, kind = line.split("\t"); assert kind == "static"
        stack[label.rsplit(":", 1)[-1]] = int(amount)
    report = {
        "schema": "whip.stock-service-slot-code.v1", "inputs_sha256": inputs.hashes,
        "tools_sha256": tools.hashes, "artifacts_sha256": {k: v for a in artifacts for k, v in a.hashes.items()},
        "compiler_flags": manifest["flags"], "object_count": len(production),
        "function_count": sum(functions.values()), "constant_count": sum(constants.values()),
        "adapter_text_bytes": sizes["stock_service_slot"],
        "adapter_input_unwind_bytes": objelf.get_section_by_name(".ARM.exidx")["sh_size"],
        "local_stack_bytes": stack, "whole_input_unwind_bytes": unwind,
        "append_input_lower_bound_bytes": lower, "append_lower_bound_over_bytes": lower - 9520,
        "missing_strong_bindings": sorted(MISSING | BINDINGS),
        "additional_owned_service_id_bytes": 1, "additional_callback_constant_bytes": 12,
        "existing_unified_table_bytes_already_counted": 240, "original_fee7_table_bytes": 252,
        "table_only_net_bytes_if_closed_replacement_approved": 12,
        "reclaimed_bytes_approved": 0, "stock_bytes_written": 0, "hardware_access": False,
        "flashable": False, "whole_code_fit_proven": False, "tests_run": False,
        "limits": "Unattached candidate; no actual callbacks/admission/owned byte. Two strong slot bindings remain absent. Additional callbacks12 and ID1 not in object-only lower bound. Artificial four-object ELF only; full26 links refuse. Setup slot209e1e is NOT shared callback selectors209df7/209df8; returningff does NOT close legacy routing. Common-callback demultiplexing/fencing and advertising/feature closure remain required. One emulator-only BL substitution, not FEE7 root closure, a heap/slot allocation proof or physical GATT registration. Stock stack/result/ID uniqueness/callback bodies remain explicit fixtures. NEVER INSTALL.",
    }
    verify()
    report_path = directory / "slot-code-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n"); snapshot(report_path)
    verify()
    yield {"elf": elfs[0].read_bytes(), "report": report, "directory": directory}
    verify()


class SlotHarness(StockTransportHarness):
    def __init__(self, build, *, patched=True):
        super().__init__(STOCK.read_bytes())
        self.load_shim(build["elf"])
        elf = ELFFile(BytesIO(build["elf"]))
        symbols = elf.get_section_by_name(".symtab")
        self.symbols = {s.name: (s["st_value"], s["st_size"]) for s in symbols.iter_symbols() if s.name}
        entry, size = self.symbols["wgs_replace_fee7"]
        self.shim_functions["wgs_replace_fee7"] = entry
        self.shim_spans.append((entry & ~1, (entry & ~1) + size))
        self.table, self.table_size = self.symbols["wgd_database"]
        self.callbacks = tuple(self.symbols["proof_" + n + "_callback_fixture"][0] for n in ("read", "write", "cccd"))
        self.uc.mem_write(OWNED_ID - 16, b"\xa5" * 33)
        self.uc.mem_write(OWNED_ID, b"\xff")
        self.uc.mem_write(CALLBACKS, struct.pack("<III", *self.callbacks))
        self.uc.mem_write(EVENT, bytes(16))
        self.fee7_routes = 0
        self.registration_publication = []
        self.callback_entries = {v & ~1 for v in self.callbacks}
        expected = bytearray(self.image)
        assert self.image[0x76DE:0x76E2] == bytes.fromhex("00f03efb")
        if patched:
            edit = _bl(BIAS + 0x76DE, entry)
            self.uc.mem_write(BIAS + 0x76DE, edit)
            expected[0x76DE:0x76E2] = edit
        assert bytes(self.uc.mem_read(BIAS, len(self.image))) == expected

    def _read_bytes(self, address, length):
        if hasattr(self, "table") and address == self.table and length == self.table_size:
            return bytes(self.uc.mem_read(address, length))
        return super()._read_bytes(address, length)

    def _code(self, uc, address, size, opaque):
        if hasattr(self, "callback_entries"):
            assert address not in self.callback_entries, "callback fixture must NEVER execute"
        offset = address - BIAS
        if offset == 0x6F3E:
            self.fee7_routes += 1
        if address == 0x4926 and uc.reg_read(self.registers[0]) == 0x3102 and uc.reg_read(self.registers[2]) == self.table:
            self.registration_publication.append((bytes(uc.mem_read(OWNED_ID, 1))[0], uc.reg_read(self.registers[1])))
        if 0x6FEC <= offset < 0x6FF2:
            self.executed.add(offset)
            return  # exact additional stock compare/branch to shared return
        super()._code(uc, address, size, opaque)

    def separate_id(self):
        assert bytes(self.uc.mem_read(OWNED_ID - 16, 16)) == b"\xa5" * 16
        assert bytes(self.uc.mem_read(OWNED_ID + 1, 16)) == b"\xa5" * 16
        return bytes(self.uc.mem_read(OWNED_ID, 1))[0]


def test_strong_bindings_budget_and_artificial_production_refusal(slot_build):
    r = slot_build["report"]
    assert (r["object_count"], r["function_count"], r["constant_count"]) == (26, 147, 3)
    assert r["append_input_lower_bound_bytes"] == 10610 + r["adapter_text_bytes"]
    assert r["additional_owned_service_id_bytes"] + r["additional_callback_constant_bytes"] == 13
    assert r["reclaimed_bytes_approved"] == 0 and r["table_only_net_bytes_if_closed_replacement_approved"] == 12
    with pytest.raises(ValueError): inspect_elf(slot_build["elf"], STOCK.read_bytes(), DESCRIPTOR.read_bytes())


def test_actual_stock_setup_preserves_four_services_and_reserved_count_five(slot_build):
    baseline, h = SlotHarness(slot_build, patched=False), SlotHarness(slot_build)
    baseline.call(0x76B8); h.call(0x76B8)
    assert len(baseline.registrations) == len(h.registrations) == 5
    assert baseline.stack_calls[0] == h.stack_calls[0] and h.stack_calls[0][:2] == (0x3100, 5)
    for index in (0, 1, 2, 4): assert baseline.registrations[index] == h.registrations[index]
    assert baseline.setup_boundaries == h.setup_boundaries
    assert bytes(h.uc.mem_read(0x209E1B, 5)) == b"\0\1\2\xff\4"
    assert h.separate_id() == 3
    assert h.registrations[3] == (h.table, bytes(h.uc.mem_read(h.table, 224)), h.callbacks)
    assert h.registration_publication[0][0] == 255 and h.registration_publication[0][1] != OWNED_ID
    assert 0x7D5E not in h.executed and 0x15824 in h.executed and 0x76E2 in h.executed
    assert not h.sends and not h.legacy_receives and not h.messages


@pytest.mark.parametrize("result,assigned", [(1, 0), (1, 3), (1, 254), (1, 255), (0, 3), (2, 3), (255, 3)])
def test_checked_add_publishes_only_separate_id_and_always_returns_sentinel(slot_build, result, assigned):
    h = SlotHarness(slot_build)
    h.uc.mem_write(OLD_SLOT, b"\xa7")  # direct adapter never writes stock slot itself
    h.registration_results.append((result, assigned))
    assert h.call_shim("wgs_replace_fee7", 0xDEADBEEF) == 255
    assert h.separate_id() == (assigned if result == 1 and assigned != 255 else 255)
    assert bytes(h.uc.mem_read(OLD_SLOT, 1)) == b"\xa7"
    assert h.registration_publication[0][0] == 255
    assert len(h.registrations) == 1 and h.registrations[0][2] == h.callbacks


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("invalid", [0, 2, 0xFFFFFFFE])
def test_each_missing_or_non_thumb_callback_refuses_without_registration(slot_build, index, invalid):
    h = SlotHarness(slot_build)
    callbacks = list(h.callbacks); callbacks[index] = invalid
    h.uc.mem_write(CALLBACKS, struct.pack("<III", *callbacks))
    h.uc.mem_write(OWNED_ID, b"\x03")
    assert h.call_shim("wgs_replace_fee7", BIAS + 0x6F29) == 255
    assert h.separate_id() == 255 and not h.registrations and not h.stack_calls


@pytest.mark.parametrize("result,assigned", [(0, 3), (1, 255), (2, 3)])
def test_failed_replacement_keeps_old_slot_closed_and_finishes_other_stock_setup(slot_build, result, assigned):
    h = SlotHarness(slot_build)
    h.registration_results.extend([(1, 0), (1, 1), (1, 2), (result, assigned), (1, 4)])
    h.call(0x76B8)
    assert h.separate_id() == 255
    assert bytes(h.uc.mem_read(0x209E1B, 5)) == b"\0\1\2\xff\4"
    assert len(h.registrations) == 5 and h.registrations[-1][0] == BIAS + 0x1FF70


def test_setup_sentinel_does_not_close_distinct_shared_callback_selector(slot_build):
    h = SlotHarness(slot_build)
    h.call(0x76B8)
    assert struct.unpack_from("<I", h.image, 0x705C)[0] + 3 == CALLBACK_SELECTOR
    assert struct.unpack_from("<I", h.image, 0x7778)[0] - 6 + 3 == OLD_SLOT
    assert struct.unpack_from("<I", h.image, 0x7788)[0] == BIAS + 0x6F29
    # Explicit selector-state fixture, NOT its measured value or ownership.
    h.uc.mem_write(CALLBACK_SELECTOR, b"\xfe\xfd")
    assert h.call(0x6F28, h.separate_id(), EVENT) == 0
    assert h.fee7_routes == 0 and 0x6FEC in h.executed
    h.uc.mem_write(OLD_SLOT, bytes([h.separate_id()]))
    assert h.call(0x6F28, h.separate_id(), EVENT) == 0
    assert h.fee7_routes == 0  # Changing the setup slot does NOT change routing.
    h.uc.mem_write(OLD_SLOT, b"\xff")
    h.uc.mem_write(CALLBACK_SELECTOR, bytes([h.separate_id()]))
    assert h.call(0x6F28, h.separate_id(), EVENT) == 0
    assert h.fee7_routes == 1
    assert bytes(h.uc.mem_read(OLD_SLOT, 1)) == b"\xff"


def test_general_sentinel_callback_keeps_its_original_branch(slot_build):
    baseline, h = SlotHarness(slot_build, patched=False), SlotHarness(slot_build)
    baseline.call(0x76B8); h.call(0x76B8)
    baseline.call(0x6F28, 255, EVENT); h.call(0x6F28, 255, EVENT)
    assert h.fee7_routes == baseline.fee7_routes == 0
    assert h.logs == baseline.logs and h.messages == baseline.messages
