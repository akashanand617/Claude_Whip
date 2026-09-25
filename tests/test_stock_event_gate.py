"""Unattached opaque event gate, actual ARM and stock callback roots only.

No production patch or callback/ROM ownership proof. The setup, legacy callback
and its selected logging/wake paths execute; stack registration/RTOS are the
existing explicitly named fixtures. No event completion provider is invented.
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
from tests.test_stock_service_slot import (
    slot_build, SlotHarness, ROOT, STOCK, DESCRIPTOR, CURRENT, CURRENT_SHA,
    OWNED_ID, EVENT, CALLBACK_SELECTOR, BINDINGS,
)
from whip import fwraw_relocation_trial as trial
from whip.fwcontinuity import BIAS
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwtransport import SMALL_QUEUE


@pytest.fixture(scope="module")
def gate_build(tmp_path_factory, slot_build):
    manifest, pins, _ = prior_inputs()
    current_path = CURRENT / "budget-report.json"
    assert hashlib.sha256(current_path.read_bytes()).hexdigest() == CURRENT_SHA
    current = json.loads(current_path.read_text())
    for name in ("control_mailbox", "stock_supervisor_wait", "control_owner"):
        pins[name] = CURRENT / (name + ".o")
        assert hashlib.sha256(pins[name].read_bytes()).hexdigest() == current["artifacts_sha256"][name + ".o"]
    parent = slot_build["directory"]
    pins["stock_service_slot"] = parent / "stock_service_slot.o"
    paths = {name: ROOT / name for name in slot_build["report"]["inputs_sha256"]}
    for name, digest in slot_build["report"]["artifacts_sha256"].items():
        p = parent / name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
        paths[str(p)] = p
    for p in (parent / "slot-code-report.json", Path(__file__),
              ROOT / "firmware/unified/stock_event_gate.c",
              ROOT / "firmware/unified/stock_event_gate.h"):
        paths[str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)] = p
    for module in tuple(sys.modules.values()):
        p = Path(getattr(module, "__file__", "") or "/").absolute()
        if p.suffix == ".py" and p.is_relative_to(ROOT):
            paths[str(p.relative_to(ROOT))] = p
    inputs = InputSnapshot(paths)
    clang, zig = shutil.which("clang"), shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    assert clang and zig, "pinned compiler/linker required, never skip"
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig), "python": Path(sys.executable)})
    assert tools.hashes == {name: manifest["tool_executables_sha256"][name] for name in tools.hashes}
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    directory = tmp_path_factory.mktemp("stock-event-gate")
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    artifacts = []

    def verify():
        for captured in (inputs, tools, *artifacts): captured.verify()

    def snapshot(*files):
        artifacts.append(InputSnapshot({str(p.relative_to(directory)): p for p in files}))

    def run(command, outputs=(), success=True):
        verify()
        result = subprocess.run(command, text=True, capture_output=True, env=env)
        produced = [p for p in outputs if p.exists()]
        if produced: snapshot(*produced)
        log = directory / f"command-{len(artifacts):03}.json"
        log.write_text(json.dumps({"command": command, "exit": result.returncode,
                                   "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")
        snapshot(log)
        if success: assert result.returncode == 0, result.stderr
        return result

    pair = [directory / name for name in ("stock_event_gate.o", "stock_event_gate-repeat.o")]
    for obj in pair:
        run([clang, *manifest["flags"], "-c", str(ROOT / "firmware/unified/stock_event_gate.c"),
             "-o", str(obj)], outputs=(obj, obj.with_suffix(".su")))
    assert all(pair[0].with_suffix(ext).read_bytes() == pair[1].with_suffix(ext).read_bytes()
               for ext in (".o", ".su"))
    pins["stock_event_gate"] = pair[0]
    production = {name: path.read_bytes() for name, path in pins.items()}
    assert unresolved_symbols(production) == MISSING | BINDINGS
    gate_elf = ELFFile(BytesIO(pair[0].read_bytes()))
    symbol, = gate_elf.get_section_by_name(".symtab").get_symbol_by_name("wgs_service_id")
    assert symbol["st_shndx"] == "SHN_UNDEF" and symbol["st_info"]["bind"] == "STB_GLOBAL"
    minimal = [pins[name] for name in ("stock_transport", "stock_service", "stock_service_slot", "stock_event_gate")]
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
            "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,--build-id=none", "-Wl,--no-undefined"]
    refused = directory / "NO-OWNED-ID-REFUSED.elf"
    result = run([*link, "-Wl,-e,wge_common", "-o", str(refused), str(pair[0])], success=False)
    assert result.returncode and not refused.exists() and "undefined symbol: wgs_service_id" in result.stderr
    elfs = [directory / name for name in ("GATE-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for target in elfs:
        run([*link, "-Wl,-e,wr_init", "-o", str(target), *map(str, minimal),
             str(parent / "proof_only_slot_bindings.o")], outputs=(target,))
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    functions, constants, sizes, unwind = trial._inventory(production)
    script = directory / "UNCHANGED-UNOWNED-geometry.ld"
    script.write_text(trial.linker_script(sizes)); snapshot(script)
    for index in range(2):
        target = directory / f"FULL27-REFUSED-{index}.elf"
        result = run([zig, "ld.lld", "-T", str(script), "-e", "wd_init", "--no-undefined",
                      "--build-id=none", "-z", "max-page-size=4", "-o", str(target),
                      *map(str, pins.values())], success=False)
        assert result.returncode and not target.exists()
        assert all("undefined symbol: " + name in result.stderr for name in MISSING | BINDINGS)
    rodata = sum(section["sh_size"] for raw in production.values()
                 for section in trial._elf(raw).iter_sections() if section.name == ".rodata")
    lower = sum(sizes.values()) + rodata - sum(sizes[name] for name in trial.PLACEMENTS)
    stack = {}
    for line in pair[0].with_suffix(".su").read_text().splitlines():
        label, amount, kind = line.split("\t"); assert kind == "static"
        stack[label.rsplit(":", 1)[-1]] = int(amount)
    report = {
        "schema": "whip.stock-event-gate-code.v1", "inputs_sha256": inputs.hashes,
        "tools_sha256": tools.hashes, "artifacts_sha256": {k: v for a in artifacts for k, v in a.hashes.items()},
        "compiler_flags": manifest["flags"], "object_count": len(production),
        "function_count": sum(functions.values()), "constant_count": sum(constants.values()),
        "gate_text_bytes": sizes["stock_event_gate"],
        "gate_input_unwind_bytes": gate_elf.get_section_by_name(".ARM.exidx")["sh_size"],
        "local_stack_bytes": stack, "whole_input_unwind_bytes": unwind,
        "append_input_lower_bound_bytes": lower, "append_lower_bound_over_bytes": lower - 9520,
        "missing_strong_bindings": sorted(MISSING | BINDINGS),
        "additional_owned_service_id_bytes": 1, "additional_callback_constant_bytes": 12,
        "new_owned_storage_bytes": 0, "emulator_stock_edit_span_bytes": 12,
        "stock_bytes_written": 0, "reclaimed_bytes_approved": 0, "flashable": False,
        "hardware_access": False, "whole_code_fit_proven": False, "tests_run": False,
        "limits": "Opaque suppression only, not event action/completion/admission. Published unique ID must remain stable per boot. Dedicated callbacks must fail closed before publication and never fall through. Both literal roots patched only in emulator; direct/retained/computed old-entry roots remain open. GlobalFF forwarded unchanged, no invented packing/parser/receipt. Original ROM/RTOS/logging fixtures, never physical GATT or ownership. Artificial five-object ELF; strict full27 refuses five strong bindings. Callback12 flash and shared ID1 RAM remain additionally required; gate adds no allocation. NEVER INSTALL.",
    }
    verify()
    report_path = directory / "event-gate-code-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n"); snapshot(report_path)
    verify()
    yield {"elf": elfs[0].read_bytes(), "report": report, "directory": directory}
    verify()


class GateHarness(SlotHarness):
    def __init__(self, build, roots=(0x7788, 0x77AC)):
        super().__init__(build)
        entry, size = self.symbols["wge_common"]
        self.shim_functions["wge_common"] = entry
        self.shim_spans.append((entry & ~1, (entry & ~1) + size))
        self.gate = entry
        self.old_entries = []
        self.second_routes = 0
        self.add_arguments = []
        expected = bytearray(self.uc.mem_read(BIAS, len(self.image)))
        for offset in roots:
            assert offset in (0x7788, 0x77AC)
            assert self.image[offset:offset + 4] == bytes.fromhex("d9ce8200")
            replacement = struct.pack("<I", entry)
            self.uc.mem_write(BIAS + offset, replacement)
            expected[offset:offset + 4] = replacement
        assert bytes(self.uc.mem_read(BIAS, len(self.image))) == expected
        allowed = {offset + i for offset in (0x76DE, *roots) for i in range(4)}
        assert {i for i, (old, new) in enumerate(zip(self.image, expected)) if old != new} <= allowed
        self.edit_span_bytes = len(allowed)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if hasattr(self, "old_entries"):
            if offset == 0x6F28:
                self.old_entries.append(tuple(uc.reg_read(r) for r in self.registers[:2]))
            if offset == 0x6FF2: self.second_routes += 1
            if offset in (0x7B40, 0x7A2A, 0x7918, 0x1445C):
                self.add_arguments.append((offset, uc.reg_read(self.registers[0])))
        # Review covers the original common callback; tests select only its
        # logging/return/wake paths, not its parameter-write action branches.
        if 0x6F80 <= offset < 0x703E:
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def through(self, entry, service, event=EVENT):
        return self.call((entry & ~1) - BIAS, service, event)

    def selectors(self, first, second):
        self.uc.mem_write(CALLBACK_SELECTOR, bytes((first, second)))


def test_gate_strong_binding_whole27_budget_and_production_refusal(gate_build):
    report = gate_build["report"]
    assert (report["object_count"], report["function_count"], report["constant_count"]) == (27, 148, 3)
    assert report["append_input_lower_bound_bytes"] == 10674 + report["gate_text_bytes"]
    assert report["append_lower_bound_over_bytes"] == 1154 + report["gate_text_bytes"]
    assert report["new_owned_storage_bytes"] == 0
    assert set(report["missing_strong_bindings"]) == MISSING | BINDINGS
    with pytest.raises(ValueError): inspect_elf(gate_build["elf"], STOCK.read_bytes(), DESCRIPTOR.read_bytes())


def test_both_literal_roots_keep_five_services_and_preserved_callback_tables(gate_build):
    baseline, h = GateHarness(gate_build, roots=()), GateHarness(gate_build)
    baseline.call(0x76B8); h.call(0x76B8)
    assert h.edit_span_bytes == 12
    assert h.stack_calls[0][:2] == (0x3100, 5) and len(h.registrations) == 5
    assert h.registrations == baseline.registrations
    assert h.setup_boundaries == baseline.setup_boundaries
    assert h.separate_id() == 3 and bytes(h.uc.mem_read(0x209E1B, 5)) == b"\0\1\2\xff\4"
    assert h.add_arguments == [(offset, h.gate) for offset in (0x7B40, 0x7A2A, 0x7918, 0x1445C)]
    for slot in (0x209E44, 0x209E40, 0x20CC48):
        assert struct.unpack("<I", h.uc.mem_read(slot, 4))[0] == h.gate
    # DIS ignores its application-callback argument: there is no fourth store.
    assert bytes(h.uc.mem_read(0x209E50, 4)) == bytes(baseline.uc.mem_read(0x209E50, 4))
    assert [call[:2] for call in h.stack_calls if call[0] == 0x3104] == [(0x3104, h.gate)]
    assert not h.old_entries and not h.sends and not h.messages


@pytest.mark.parametrize("owned", [0, 3, 254])
@pytest.mark.parametrize("selector", [0, 1])
def test_published_id_suppressed_before_either_legacy_selector(gate_build, owned, selector):
    h = GateHarness(gate_build)
    h.uc.mem_write(OWNED_ID, bytes([owned]))
    selectors = [0x55, 0x56]; selectors[selector] = owned
    h.selectors(*selectors)
    assert h.call_shim("wge_common", owned, EVENT) == 0
    assert not h.old_entries and h.fee7_routes == h.second_routes == 0
    assert h.call(0x6F28, owned, EVENT) == 0
    assert (h.fee7_routes, h.second_routes) == ((1, 0) if selector == 0 else (0, 1))


@pytest.mark.parametrize("pointer", [0, 0xDEADBEEF, 0xFFFFFFFF])
def test_owned_event_pointer_is_never_dereferenced(gate_build, pointer):
    h = GateHarness(gate_build)
    h.uc.mem_write(OWNED_ID, b"\x03")
    reads = []
    h.uc.hook_add(h.u.UC_HOOK_MEM_READ, lambda uc, access, address, size, value, opaque:
                  reads.append((address, size)))
    assert h.call_shim("wge_common", 3, pointer) == 0
    assert not h.old_entries and not h.logs and not h.messages
    assert all(not address <= pointer < address + size for address, size in reads)


@pytest.mark.parametrize("service,selectors,event", [
    (0, (0, 4), bytes([7, 1, 0, 0, 1]) + bytes(11)),
    (1, (9, 1), bytes([7, 1, 1]) + bytes(13)),
    (2, (9, 4), bytes(16)),
    (4, (9, 4), bytes([7, 2, 0]) + bytes(13)),
])
def test_preserved_service_events_forward_opaque_with_original_effects(gate_build, service, selectors, event):
    baseline, h = GateHarness(gate_build, roots=()), GateHarness(gate_build)
    for runner in (baseline, h):
        runner.call(0x76B8)
        runner.selectors(*selectors)
        runner.uc.mem_write(EVENT, event)
    def retained_pointer(runner):
        if service == 2:
            # DIS does not retain/invoke an application callback; this is only
            # its actual setup argument, not an invented DIS callback path.
            return dict(runner.add_arguments)[0x7918]
        slot = {0: 0x209E44, 1: 0x209E40, 4: 0x20CC48}[service]
        return struct.unpack("<I", runner.uc.mem_read(slot, 4))[0]
    assert h.through(retained_pointer(h), service) == baseline.through(retained_pointer(baseline), service)
    assert h.old_entries == [(service, EVENT)]
    assert h.logs == baseline.logs and h.messages == baseline.messages
    assert h.fee7_routes == baseline.fee7_routes and h.second_routes == baseline.second_routes
    assert bytes(h.uc.mem_read(EVENT, 16)) == event


@pytest.mark.parametrize("kind,cause", [(0, 0), (1, 0), (1, 1), (1, 0x1234), (2, 0)])
@pytest.mark.parametrize("owned", [3, 255])
def test_global_ff_always_retains_original_general_event_behavior(gate_build, kind, cause, owned):
    baseline, h = GateHarness(gate_build, roots=()), GateHarness(gate_build)
    # Only offsets read by actual stock are assigned semantics. Other bytes
    # are deliberately opaque, not a claimed send-completion structure.
    event = bytearray(b"\xa5" * 16); event[0] = kind; event[8:10] = struct.pack("<H", cause)
    for runner in (baseline, h):
        runner.call(0x76B8)
        runner.uc.mem_write(OWNED_ID, bytes([owned]))
        runner.uc.mem_write(EVENT, bytes(event))
        runner.uc.mem_write(SMALL_QUEUE + 2, struct.pack("<HH", 0, 1))
    def registered(runner):
        entry, = [call[1] for call in runner.stack_calls if call[0] == 0x3104]
        return entry
    assert h.through(registered(h), 255) == baseline.through(registered(baseline), 255) == 0
    assert h.old_entries == [(255, EVENT)]
    assert h.logs == baseline.logs and h.messages == baseline.messages
    assert not h.fee7_routes and not h.second_routes


def test_unpublished_id_does_not_falsely_identify_new_events(gate_build):
    h = GateHarness(gate_build)
    h.selectors(3, 4)
    assert h.separate_id() == 255
    assert h.call_shim("wge_common", 3, EVENT) == 0
    assert h.old_entries == [(3, EVENT)] and h.fee7_routes == 1
    # This is the explicit pre-publication limitation: dedicated callbacks
    # MUST refuse, not use this forwarding path as an admission decision.


@pytest.mark.parametrize("only_root", [0x7788, 0x77AC])
def test_partial_root_substitution_leaves_the_other_callback_unfenced(gate_build, only_root):
    h = GateHarness(gate_build, roots=(only_root,))
    h.call(0x76B8); h.selectors(3, 4)
    local = struct.unpack("<I", h.uc.mem_read(0x209E44, 4))[0]
    general, = [call[1] for call in h.stack_calls if call[0] == 0x3104]
    assert (local == h.gate, general == h.gate) == (only_root == 0x7788, only_root == 0x77AC)
    assert h.through(local, 3) == h.through(general, 3) == 0
    assert h.old_entries == [(3, EVENT)] and h.fee7_routes == 1
    # Explicit synthetic event through each retained root, not a real UART
    # event carrying the unified ID or proof of physical callback delivery.
