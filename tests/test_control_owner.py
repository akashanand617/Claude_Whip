"""Persistent actual C owner/coordinator + selected stock paths, OFF-RING only.

Artificial singleton/clock/stock-pointer bindings exist ONLY in the test ABI.
The wait ROM, task-body boundaries, RTOS scheduling, physical receipts, source
and scheduler preparation are named fixtures, never inferred Health success.
No stock file, production linker/pin, device or firmware container is changed.
"""
from collections import deque
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

from probe.owner_wait_budget import prior_inputs, unresolved_symbols
from tests.test_stock_coordinator import (
    CoordinatorThumb, REVISION, PREPARED, HEALTH_MODE, ENTERING, GESTURE,
    RETURNING, FAULT, QUIESCE, HOLD, START, STOP, RESUME,
)
from tests.test_stock_switch import SCRATCH
from tests.test_stock_optical_work import HEALTH, BUFFER, STATUS, REJECTED
from tests.test_fwstock_link import STOCK, DESCRIPTOR
from tests.test_unified_wire import BOOT, frames, request, reply
from whip.fwcontinuity import BIAS, FIFO_DRAIN, StockMotionHarness, ProofError
from whip.fwoptical_io import _bl
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf

ROOT = Path(__file__).resolve().parents[1]
BASE = HEALTH - 408
INBOX, FIRST, COORDINATOR, RECEIPT = (BASE + n for n in (764, 820, 824, 852))
CLOCK = 0x226500
WAIT_HANDLE = 0x221234
BODY_SITES = dict(zip((0x657C, 0xCD60, 0x905C, 0x1202, 0x343A, 0x1279E, 0x3FD2),
                      (0x1366, 0x136E, 0x1374, 0x137A, 0x1382, 0x138A, 0x1392)))
WC_IDLE, WC_WAIT_DRAIN, WC_STOP_SUBMITTED, WC_WAIT_STOP, WC_HOLD_READY, WC_WAIT_RESUME, WC_REJECTED, WC_FAILED = range(8)
WD_CLOSED, WD_IDLE, WD_RECEIVING, WD_WAITING, WD_REPLY = range(5)
NEW = ("control_mailbox", "stock_supervisor_wait", "control_owner")
BINDINGS = {"wco_bound_owner", "wco_bound_stock", "wco_monotonic_ms"}
ABI = f"""
/* TEST ONLY: artificial singleton, addresses, clock and ABI witnesses. */
#include "control_owner.h"
#include <stddef.h>
__asm__(".global wco_bound_owner\\n.set wco_bound_owner, {BASE:#x}");
const wco_stock wco_bound_stock = {{(const volatile uint32_t *){REVISION:#x},
                                    (uint8_t *){BUFFER:#x}, (uint8_t *){STATUS:#x}}};
uint32_t wco_monotonic_ms(void) {{ return *(const volatile uint32_t *){CLOCK:#x}; }}
unsigned proof_wc_owner_size(void) {{ return sizeof(wc_owner); }}
unsigned proof_wc_stop_size(void) {{ return sizeof(wc_stop_receipt); }}
unsigned proof_wc_resume_size(void) {{ return sizeof(wc_resume_receipt); }}
unsigned proof_wco_layout(unsigned n) {{
    switch(n) {{
    case 0: return sizeof(wco_owner);
    case 1: return sizeof(wd_dispatch);
    case 2: return offsetof(wco_owner,inbox);
    case 3: return offsetof(wco_owner,first_arrival);
    case 4: return offsetof(wco_owner,coordinator);
    case 5: return offsetof(wco_owner,stop);
    case 6: return sizeof(wim_mailbox);
    case 7: return offsetof(wd_dispatch,state);
    case 8: return offsetof(wm_controller,connected);
    default: return offsetof(wm_controller,charging);
    }}
}}
"""


@pytest.fixture(scope="module")
def owner_build(tmp_path_factory):
    manifest, pins, previous = prior_inputs()
    clang, zig = shutil.which("clang"), shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    assert clang and zig, "reviewed Clang/Zig required; never skip"
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig), "python": Path(sys.executable)})
    assert tools.hashes == {k: manifest["tool_executables_sha256"][k] for k in tools.hashes}
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    paths = {str(p.relative_to(ROOT)): p for p in pins.values()}
    for name in (*pins, *NEW):
        for ext in ("c", "h"):
            p = ROOT / f"firmware/unified/{name}.{ext}"
            if not p.exists():
                assert (name, ext) == ("compiler_runtime", "h")
                continue
            key = str(p.relative_to(ROOT))
            if key in manifest["inputs_sha256"]:
                assert hashlib.sha256(p.read_bytes()).hexdigest() == manifest["inputs_sha256"][key]
            paths[key] = p
    for p in (Path(__file__), previous, ROOT / "tests/native/arm_proof.ld",
              ROOT / "firmware/unified/build-20260924-raw-ingress-v1/manifest.json",
              ROOT / "requirements-firmware-proof.txt",
              ROOT / "firmware/rt02cr-stock-3.12.02.bin",
              ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json"):
        paths[str(p.relative_to(ROOT))] = p
    for module in tuple(sys.modules.values()):
        p = Path(getattr(module, "__file__", "") or "/").absolute()
        if p.suffix == ".py" and p.is_relative_to(ROOT):
            paths[str(p.relative_to(ROOT))] = p
    inputs = InputSnapshot(paths)
    output = tmp_path_factory.mktemp("control-owner")
    snapshots, objects = [], []

    def verify():
        for item in (inputs, tools, *snapshots):
            item.verify()

    def capture(*files):
        snapshots.append(InputSnapshot({str(p.relative_to(output)): p for p in files}))

    for name in (*NEW, "proof_only_owner_bindings"):
        pair = [output / (name + suffix) for suffix in (".o", "-repeat.o")]
        for obj in pair:
            verify()
            source = ["-x", "c", "-"] if name.startswith("proof_") else [str(ROOT / f"firmware/unified/{name}.c")]
            subprocess.run([clang, *manifest["flags"], "-c", *source, "-o", str(obj)],
                           input=ABI if name.startswith("proof_") else None, text=True, check=True)
            capture(obj, obj.with_suffix(".su"))
        assert all(pair[0].with_suffix(ext).read_bytes() == pair[1].with_suffix(ext).read_bytes()
                   for ext in (".o", ".su"))
        objects.append(pair[0])
    production = {name: p.read_bytes() for name, p in pins.items()} | {
        name: p.read_bytes() for name, p in zip(NEW, objects)}
    assert unresolved_symbols(production) == BINDINGS
    symbols = ELFFile(BytesIO(production["control_owner"])).get_section_by_name(".symtab")
    for name in BINDINGS:
        sym, = symbols.get_symbol_by_name(name)
        assert sym["st_shndx"] == "SHN_UNDEF" and sym["st_info"]["bind"] == "STB_GLOBAL"
    supervisor, = symbols.get_symbol_by_name("wuw_supervise")
    assert supervisor["st_shndx"] != "SHN_UNDEF" and supervisor["st_info"]["bind"] == "STB_GLOBAL"
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"), ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
            "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,-e,wr_init",
            "-Wl,--build-id=none", "-Wl,--no-undefined"]
    refused_path = output / "no-physical-bindings-REFUSED.elf"
    verify()
    refused = subprocess.run([*link, "-o", str(refused_path), *map(str, pins.values()),
                              *map(str, objects[:3])], env=env, capture_output=True, text=True)
    refusal_log = output / "missing-physical-bindings-link.json"
    refusal_log.write_text(json.dumps({"command": refused.args, "exit": refused.returncode,
                                      "stdout": refused.stdout, "stderr": refused.stderr}, indent=2) + "\n")
    capture(refusal_log)
    assert refused.returncode and not refused_path.exists()
    assert all("undefined symbol: " + name in refused.stderr for name in BINDINGS)
    targets = [output / n for n in ("OWNER-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for target in targets:
        verify()
        subprocess.run([*link, "-o", str(target), *map(str, pins.values()), *map(str, objects)], env=env, check=True)
        capture(target)
    assert targets[0].read_bytes() == targets[1].read_bytes()
    local_stack, text_bytes = {}, {}
    for name, obj in zip(NEW, objects):
        elf = ELFFile(BytesIO(obj.read_bytes()))
        text_bytes[name] = sum(s["sh_size"] for s in elf.iter_sections()
                               if s.name == ".text" or s.name.startswith(".text."))
        local_stack[name] = {}
        for line in obj.with_suffix(".su").read_text().splitlines():
            label, size, kind = line.split("\t")
            assert kind == "static"
            local_stack[name][label.rsplit(":", 1)[-1]] = int(size)
    report = {
        "schema": "whip.control-owner-code.v1",
        "inputs_sha256": inputs.hashes, "tools_sha256": tools.hashes,
        "artifacts_sha256": {k: v for item in snapshots for k, v in item.hashes.items()},
        "compiler_flags": manifest["flags"], "input_objects": {
            name: str(path.relative_to(ROOT)) for name, path in pins.items()},
        "production_object_count": len(production), "proof_only_binding_object_count": 1,
        "new_text_bytes": text_bytes, "local_stack_bytes": local_stack,
        "unresolved_strong_physical_bindings": sorted(BINDINGS),
        "real_supervisor_composition": True, "missing_bindings_link_refused": True,
        "double_compile_and_link_identical": True, "control_owner_bytes": 880,
        "mailbox_bytes": 56, "physical_qualification_proven": False,
        "whole_code_fit_proven": False, "ram_or_stack_owned": False,
        "stock_image_constructed": False, "hardware_access": False,
        "tests_run": False,
        "limits": [
            "Build provenance only; separate guarded pytest report proves execution outcomes.",
            "Artificial singleton, clock slot, stock pointers, RAM and link addresses are TEST ONLY.",
            "No production GATT callback, clock binding, boot identity generator or task attachment.",
            "ROM semaphore, RTOS interleavings and seven stock body callees are contract fixtures.",
            "Source profile has synthetic reviewed shape, not physical qualification.",
            "Inventory, physical STOP/source, drain and current-settings scheduler preparation remain fixtures.",
            "Original stock sample/motion consumers execute, not physical Health or steps/sleep proof.",
            "Local stack sizes exclude nesting/interrupts and do not establish real task headroom.",
            "The artificial ELF is not an image fit, has no retirement stubs and must never be installed.",
        ],
    }
    verify()
    report_path = output / "owner-code-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    capture(report_path)
    verify()
    yield {"elf": targets[0].read_bytes(), "directory": output, "refused": refused,
           "inputs": inputs, "tools": tools, "snapshots": snapshots, "report": report}
    verify()


class OwnerThumb(CoordinatorThumb):
    """Reuse selected original paths; C service owns all polling composition."""
    def __init__(self, raw, *, profile=False, inventory=True):
        self.raw = raw
        self.clock_values, self.clock_reads, self.core_times = deque(), [], []
        self.owner_calls, self.wait_takes, self.body_calls, self.body_marks = [], [], [], []
        self.step_return = None
        self.wait_active = False
        self.wait_tops = 0
        self.wait_result = 0
        self.inject_on_mutex = None
        self.capture_stop_submission = False
        self.stop_submission_return = None
        self.stop_submission_copy = None
        self.guards_live = False
        self.entry_names = {}
        self.masked_count = self.masked_run = self.masked_max = 0
        self.observed_low = self.STACK
        super().__init__(raw, inventory=inventory)
        assert self.base == BASE
        assert tuple(self.function("proof_wco_layout", i) for i in range(7)) == (880, 764, 764, 820, 824, 852, 56)
        self.state_offset, self.connected_offset, self.charging_offset = (
            self.function("proof_wco_layout", i) for i in (7, 8, 9))
        assert (self.state_offset, self.connected_offset, self.charging_offset) == (740, 32, 33)
        e = ELFFile(BytesIO(raw))
        self.stock_binding = e.get_section_by_name(".symtab").get_symbol_by_name("wco_bound_stock")[0]["st_value"]
        self.fixtures.clear()  # Parent's temporary initialization is discarded below.
        self.uc.mem_write(BASE - 16, b"\xa5" * (880 + 32))
        assert self.function("wco_init", BASE, 1, int(inventory), BOOT & 0xFFFFFFFF, BOOT >> 32)
        self.fixture("artificial singleton/clock/storage and serialized task", True)
        self.fixture("test-only producer inventory", inventory)
        if profile:
            self.uc.mem_write(SCRATCH, struct.pack("<II32sIIHH6B2x", 1, 2, b"\xee" + bytes(31),
                                                  101, 2000, 20, 20, 0, 0x23, 5, 15, 0x74, 0xC8))
            assert self.adapter("wa_prepare", SCRATCH)
            self.fixture("synthetic source profile with reviewed shape, not physically qualified", True)
        assert self.function("wco_open", BASE, 7, 0, 0)
        self.original = self.new_job() if inventory else None
        self.owner_calls.clear(); self.core_times.clear()
        self.uc.mem_write(CLOCK, bytes(4))
        self.uc.mem_write(0x208C90, struct.pack("<I", WAIT_HANDLE))
        assert STOCK[0x135C:0x1360] == bytes.fromhex("ecf728d8")
        self.wait_edit = _bl(BIAS + 0x135C, self.functions["wuw_take"])
        self.uc.mem_write(BIAS + 0x135C, self.wait_edit)
        expected = bytearray(STOCK)
        for edit in self.plan:
            expected[edit.file_offset:edit.file_offset + 4] = edit.after
        expected[0x135C:0x1360] = self.wait_edit
        assert bytes(self.uc.mem_read(BIAS, len(STOCK))) == expected
        self.guards_live = True

    def function(self, name, *args):
        result = super().function(name, *args)
        if self.guards_live:
            assert bytes(self.uc.mem_read(BASE - 16, 16)) == b"\xa5" * 16
            assert bytes(self.uc.mem_read(BASE + 880, 16)) == b"\xa5" * 16
        return result

    def _code(self, uc, address, size, opaque):
        if address == self.stop_submission_return:
            # Capture the completed output at the actual C pump return, BEFORE
            # the second clock/tick can invalidate it. Never relabel a callback
            # by rereading the reusable output slot at observation time.
            self.stop_submission_copy = bytes(uc.mem_read(RECEIPT, 28))
            uc.mem_write(PREPARED, self.stop_submission_copy)
            self.stop_submission_return = None
            self.capture_stop_submission = False
            self.fixture("immutable STOP observer identity copied at pump return", True)
        mask = uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
        self.masked_count += bool(mask)
        self.masked_run = self.masked_run + 1 if mask else 0
        self.masked_max = max(self.masked_max, self.masked_run)
        self.observed_low = min(self.observed_low, uc.reg_read(self.a.UC_ARM_REG_SP))
        if address == self.step_return:
            self.step_return = None
        if len(self.entry_names) != len(self.functions):
            self.entry_names = {value & ~1: name for name, value in self.functions.items()}
        name = self.entry_names.get(address)
        if name in ("wco_service", "wuw_supervise", "wc_pump", "wb_stock_stop_writes"):
            if name != "wco_service":
                assert mask == 0
            self.owner_calls.append(name)
        if name == "wc_pump" and self.capture_stop_submission:
            self.stop_submission_return = uc.reg_read(self.a.UC_ARM_REG_LR) & ~1
        if name == "wco_step" and mask == 0 and uc.reg_read(self.a.UC_ARM_REG_IPSR) == 0:
            self.step_return = uc.reg_read(self.a.UC_ARM_REG_LR) & ~1
        if self.step_return is not None:
            assert 0x1000000 <= address < 0x1010000, "pure owner step escaped into stock/ROM"
            if name in ("wd_tick", "wd_receive", "wa_link", "wim_take", "wim_admitted"):
                assert mask == 1, "pure software admission escaped outer PRIMASK"
        if name == "wd_tick":
            self.core_times.append(uc.reg_read(self.registers[1]))
        if name == "wd_receive":
            self.core_times.append(struct.unpack("<I", uc.mem_read(uc.reg_read(self.a.UC_ARM_REG_SP), 4))[0])
        if name == "wco_monotonic_ms":
            assert mask == 0 and self.clock_values, "unexpected clock read"
            value = self.clock_values.popleft()
            uc.mem_write(CLOCK, struct.pack("<I", value))
            self.clock_reads.append(value)
            self.fixture("fresh monotonic clock slot sample", value)
        if address == 0x133F4 and self.inject_on_mutex is not None:
            assert mask == 0
            callback, self.inject_on_mutex = self.inject_on_mutex, None
            callback(self)
        if self.wait_active:
            if address == BIAS + 0x1356:
                self.wait_tops += 1
                if self.wait_tops == 2:
                    uc.emu_stop()
                    return
            if address == 0x13360:
                assert mask == 0
                args = tuple(uc.reg_read(r) for r in self.registers[:2])
                assert args == (WAIT_HANDLE, 100)
                self.wait_takes.append(args)
                self.fixture("ROM semaphore take result, not elapsed timeout", self.wait_result)
                self._return(self.wait_result)
                return
            if address - BIAS in BODY_SITES:
                offset = address - BIAS
                assert uc.reg_read(self.a.UC_ARM_REG_LR) == (BIAS + BODY_SITES[offset] + 4) | 1
                self.body_calls.append(offset)
                self.body_marks.append(bytes(uc.mem_read(0x208C88, 1))[0])
                self.fixture("stock qc_app body callee boundary", offset)
                self._return(0xCAFEBABE)
                return
            if BIAS + 0x1350 <= address < BIAS + 0x139C:
                return
        super()._code(uc, address, size, opaque)

    def state(self):
        return bytes(self.uc.mem_read(BASE + self.state_offset, 1))[0]

    def close_input(self, reasons=4, generation=7):
        return self.function("wim_close", INBOX, generation, reasons)

    def post(self, packet, received=0, generation=7):
        self.uc.mem_write(SCRATCH, packet)
        return self.function("wim_post", INBOX, generation, SCRATCH, len(packet), received)

    def command(self, operation, request_id, now):
        for packet in frames(1, request_id, request(operation)):
            assert self.post(packet, now)

    def step(self, now):
        return self.function("wco_step", BASE, now)

    def service(self, now=0, after=None):
        assert not self.clock_values
        self.clock_values.extend((now, now if after is None else after))
        result = self.function("wco_service", BASE, self.stock_binding)
        assert not self.clock_values
        return result

    def pump(self, now=1, **unused):
        return self.service(now)

    def stopped(self, now=1, verified=True, *, receipt=RECEIPT, buffer=BUFFER, status=STATUS):
        return self.function("wc_optics_stopped", COORDINATOR, receipt, int(verified), buffer, status, now)

    def physical(self, proof, now):
        self.uc.mem_write(SCRATCH, struct.pack("<6I", self.token, self.session, self.mode(4), proof, 1, 2))
        return self.function("wc_physical_done", COORDINATOR, SCRATCH, now)

    def prepare_resume(self, now=2, *, revision=17, controls=None, preserved=True, rebound=True):
        controls = self.controls() if controls is None else controls
        self.uc.mem_write(PREPARED, struct.pack("<4I2B2x", self.token, self.word(4), revision,
                                              controls, int(preserved), int(rebound)))
        self.fixture("fresh current-settings scheduler preparation", (preserved, rebound))
        return self.function("wc_resume_prepared", COORDINATOR, PREPARED, REVISION, now)

    def wait_once(self, now, *, taken=0, after=None):
        assert not self.clock_values
        self.clock_values.extend((now, now if after is None else after))
        self.wait_active, self.wait_tops, self.wait_result = True, 0, taken
        self.uc.reg_write(self.a.UC_ARM_REG_R5, 3)  # explicit original task-prologue fixture
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        try:
            self.uc.emu_start((BIAS + 0x1350) | 1, 0xFFFFFFFF, count=100000)
        finally:
            self.wait_active = False
        assert self.wait_tops == 2 and not self.clock_values
        assert self.uc.reg_read(self.a.UC_ARM_REG_SP) == self.STACK

    def reply_result(self, operation, request_id, now, result=0):
        expected = frames(2, request_id, reply(operation, result, self.mode(), 0, session=self.session))
        for part, packet in enumerate(expected):
            assert self.adapter("wd_reply_next", 7, SCRATCH, now)
            assert bytes(self.uc.mem_read(SCRATCH, 20)) == packet
            assert self.adapter("wd_reply_sent", 7, request_id, part, self.submit20(packet), now)


def test_actual_owner_build_requires_three_strong_bindings_and_rejects_production(owner_build):
    h = OwnerThumb(owner_build["elf"])
    assert h.function("proof_wco_layout", 0) == 880
    assert owner_build["refused"].returncode
    report = owner_build["report"]
    assert report["production_object_count"] == 25
    assert report["new_text_bytes"] == {
        "control_mailbox": 564, "stock_supervisor_wait": 72, "control_owner": 744}
    assert report["local_stack_bytes"]["control_owner"]["wco_step"] == 88
    assert report["local_stack_bytes"]["control_owner"]["wco_service"] == 40
    with pytest.raises(ValueError):
        inspect_elf(owner_build["elf"], STOCK, DESCRIPTOR)


@pytest.mark.parametrize("taken", [0, 1, 0xFFFFFFFF])
def test_exact_stock_wait_runs_real_owner_and_two_fragment_status(owner_build, taken):
    h = OwnerThumb(owner_build["elf"])
    h.command(1, 1, 5)
    h.wait_once(6, taken=taken)
    assert h.mode() == HEALTH_MODE and h.state() == WD_REPLY
    assert h.owner_calls == ["wuw_supervise", "wco_service", "wc_pump"]
    assert h.wait_takes == [(WAIT_HANDLE, 100)] and h.clock_reads == [6, 6]
    assert h.body_calls == (list(BODY_SITES) if taken else [])
    assert h.body_marks == ([0, 1, 2, 3, 4, 6, 7] if taken else [])
    assert not h.transfers and not h.timer_calls and not h.allocations
    h.reply_result(1, 1, 6)
    assert h.state() == WD_IDLE and len(h.gatt_sends) == 2


@pytest.mark.parametrize("inventory,profile", [(True, False), (False, True)])
def test_missing_real_admission_evidence_leaves_default_health(owner_build, inventory, profile):
    h = OwnerThumb(owner_build["elf"], inventory=inventory, profile=profile)
    h.command(3, 1, 1)
    assert h.service(1) == WC_IDLE
    assert h.mode() == HEALTH_MODE and not h.transfers and not h.timer_calls
    h.reply_result(3, 1, 1, result=1)


def test_synthetic_reviewed_profile_waits_for_real_drain_and_idle_ticks_cleanup(owner_build):
    h = OwnerThumb(owner_build["elf"], profile=True)
    h.command(3, 1, 1)
    assert h.service(1) == WC_WAIT_DRAIN
    assert (h.mode(), h.mode(4)) == (ENTERING, QUIESCE)
    assert not h.transfers and not h.physical(0x0F, 1)
    h.wait_once(3001)
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    h.wait_once(6001)
    assert h.mode() == FAULT and not h.adapter("wa_health_allowed", 0)
    assert not h.transfers and not h.timer_calls


@pytest.mark.parametrize("second", [False, True])
def test_original_arrival_deadline_cannot_be_reset_by_delayed_dequeue(owner_build, second):
    h = OwnerThumb(owner_build["elf"])
    packets = frames(1, 1, request(1))
    assert h.post(packets[0], 0) and h.step(900)
    assert h.state() == WD_RECEIVING
    if second:
        assert h.post(packets[1], 1500)
    assert h.step(1500 if second else 1001)
    assert h.state() == WD_CLOSED and h.mode() == HEALTH_MODE
    assert 0 not in h.core_times and h.core_times[-1] == (1500 if second else 1001)


@pytest.mark.parametrize("start,now,accept", [(0, 1000, True), (0, 1001, False),
    (0xFFFFFF00, 0x2E8, True), (0xFFFFFF00, 0x2E9, False)])
def test_complete_burst_age_boundary_and_clock_wrap(owner_build, start, now, accept):
    h = OwnerThumb(owner_build["elf"])
    h.command(1, 1, start)
    assert h.step(now)
    assert h.state() == (WD_REPLY if accept else WD_CLOSED)
    assert h.mode() == HEALTH_MODE


@pytest.mark.parametrize("first,second,now", [(100, 99, 100), (100, 101, 100)])
def test_backward_or_future_original_arrival_refuses(owner_build, first, second, now):
    h = OwnerThumb(owner_build["elf"])
    packets = frames(1, 1, request(1))
    assert h.post(packets[0], first) and h.post(packets[1], second)
    assert h.step(now) and h.state() == WD_CLOSED


def test_charging_after_already_consumed_disconnect_is_not_lost(owner_build):
    h = OwnerThumb(owner_build["elf"])
    assert h.close_input(4) and h.step(1)
    assert h.state() == WD_CLOSED
    assert bytes(h.uc.mem_read(BASE + h.connected_offset, 2)) == b"\0\0"
    assert h.close_input(8) and h.step(2)
    assert bytes(h.uc.mem_read(BASE + h.connected_offset, 2)) == b"\0\1"
    assert not h.adapter("wa_request", 1, 3)
    assert h.mode() == HEALTH_MODE


@pytest.mark.parametrize("name", ["wco_step", "wco_service", "wco_open", "wco_init"])
@pytest.mark.parametrize("mask,exception", [(1, 0), (0, 15), (1, 15)])
def test_invalid_entry_context_preserves_mask_and_owner(owner_build, name, mask, exception):
    h = OwnerThumb(owner_build["elf"])
    before = bytes(h.uc.mem_read(BASE, 880))
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, exception)
    args = {"wco_step": (BASE, 1), "wco_service": (BASE, h.stock_binding),
            "wco_open": (BASE, 8, 0, 1), "wco_init": (BASE, 1, 1, 1, 1)}[name]
    assert h.function(name, *args) == (WC_REJECTED if name == "wco_service" else 0)
    assert bytes(h.uc.mem_read(BASE, 880)) == before and not h.clock_reads
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == mask
    assert h.uc.reg_read(h.a.UC_ARM_REG_IPSR) == exception


@pytest.mark.parametrize("stale_preparation", [False, True])
def test_persistent_wait_owner_coordinator_and_preserved_stock_health_round_trip(owner_build, stale_preparation):
    h = OwnerThumb(owner_build["elf"], profile=True)
    initial, old = h.controls(), h.original
    baseline = StockMotionHarness(STOCK)
    batch = [(10, -20, 8005), (11, -21, 8006)]
    baseline.fifo.extend(batch); baseline.call(FIFO_DRAIN)
    expected_motion = baseline.consume_health()
    assert h.read() == 0 and h.commit(old)
    assert h.drain_motion(batch) == expected_motion
    h.command(3, 1, 1); h.wait_once(1)
    assert (h.mode(), h.mode(4)) == (ENTERING, QUIESCE)
    h.enter(requested=True)
    assert h.read() == REJECTED and not h.commit(old)
    assert h.observe((1, 2, 8005)) == 2 and h.mode() == GESTURE
    h.reply_result(3, 1, 1)
    assert h.submit_motion(1)[3]
    assert h.drain_motion(batch) == expected_motion and h.controls() == initial
    h.command(2, 2, 2); h.wait_once(2); h.to_resume()
    h.uc.mem_write(REVISION, struct.pack("<I", 18))
    h.set_controls((60, 4, 3, 1))
    assert h.service(2) == WC_WAIT_RESUME
    if stale_preparation:
        assert not h.prepare_resume(revision=17)
        assert h.mode() == RETURNING and not h.adapter("wa_health_allowed", 0)
        return  # No automatic retry/relabel after consuming bad preparation.
    assert h.prepare_resume(revision=18) and h.mode() == HEALTH_MODE
    h.reply_result(2, 2, 2)
    assert not h.commit(old)
    fresh = h.new_job(); h.configure_samples()
    h.fixture("fresh physical optical setup", True)
    assert h.read(ticket=fresh) == 0 and h.commit(fresh)
    assert h.drain_motion(batch) == expected_motion
    assert h.controls() == int.from_bytes(bytes((60, 4, 3, 1)), "little")
    assert not h.timer_calls and not h.allocations
    assert h.retirements == 1 and h.owner_calls.count("wc_pump") >= 4


@pytest.mark.parametrize("close_during_stop", [False, True])
def test_after_blocking_stop_fresh_clock_and_close_invalidate_original_submission(owner_build, close_during_stop):
    h = OwnerThumb(owner_build["elf"], profile=True)
    h.command(3, 1, 1); assert h.service(1) == WC_WAIT_DRAIN
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    original_token = h.token
    h.fixture("test-only cancellation and producer/queue fence receipts", True)
    h.capture_stop_submission = True
    if close_during_stop:
        producer = OwnerThumb(owner_build["elf"])

        def queued_disconnect(target):
            # Separate artificial CPU/stack executes actual C producer; this
            # is an RTOS interleaving fixture, not hardware exception entry.
            producer.uc.mem_write(BASE, bytes(target.uc.mem_read(BASE, 880)))
            assert producer.close_input(4)
            target.uc.mem_write(INBOX, bytes(producer.uc.mem_read(INBOX, 56)))
            target.fixture("disconnect producer during blocking mutex boundary", True)

        h.inject_on_mutex = queued_disconnect
    assert h.service(1, after=2 if close_during_stop else 3001) == WC_REJECTED
    assert h.clock_reads[-2:] == [1, 2 if close_during_stop else 3001]
    assert h.transfers[-2:] == [b"\x7b\xa5", b"\x7b\0"]
    saved = h.stop_submission_copy
    assert saved is not None and bytes(h.uc.mem_read(PREPARED, 28)) == saved
    assert struct.unpack_from("<I", saved)[0] == original_token
    assert h.token != original_token and (h.mode(), h.mode(4)) == (RETURNING, STOP)
    h.uc.mem_write(RECEIPT, bytes(28))  # later output reuse cannot change the saved identity
    assert not h.stopped(2 if close_during_stop else 3001, receipt=PREPARED)
    assert h.retirements == 0 and not h.adapter("wa_health_allowed", 0)
