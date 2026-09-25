"""Unattached mailbox: actual ARM, independent model, artificial caller storage.

No ROM/RTOS/device mocks or production owner. Interrupt interleavings execute a
producer on a separate artificial CPU/stack and share only mailbox bytes; they
do not emulate hardware exception entry, priority arbitration or physical drain.
Missing proof dependencies/tools fail collection/setup, never skip.
"""
from dataclasses import dataclass, field
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile
import pytest

from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb, ThumbProofError

ROOT = Path(__file__).resolve().parents[1]
U32 = 0xFFFFFFFF
MAILBOX_BYTES = 56
API = {"wim_init", "wim_open", "wim_post", "wim_close", "wim_admitted", "wim_take", "wim_retire"}
ABI = '''#include "control_mailbox.h"
#include <stddef.h>
_Static_assert(sizeof(wim_mailbox)==56 && sizeof(wim_event)==32,"storage");
_Static_assert(offsetof(wim_mailbox,generation)==0 && offsetof(wim_mailbox,flags)==4,"mailbox ABI");
_Static_assert(offsetof(wim_mailbox,slots)==8 && sizeof(((wim_mailbox*)0)->slots[0])==24,"slot ABI");
_Static_assert(offsetof(wim_mailbox,slots[0].received)==8 && offsetof(wim_mailbox,slots[0].frame)==12,"slot 0");
_Static_assert(offsetof(wim_mailbox,slots[1].received)==32 && offsetof(wim_mailbox,slots[1].frame)==36,"slot 1");
_Static_assert(offsetof(wim_event,frame)==8 && offsetof(wim_event,reasons)==28,"event ABI");
void wr_init(void) {}
unsigned proof_runtime_size(void) { return sizeof(wim_mailbox); }
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify_build(build):
    for snapshot in (build["inputs"], build["tools"], *build["snapshots"]):
        snapshot.verify()


@pytest.fixture(scope="module")
def mailbox_build(tmp_path_factory):
    checkpoint = ROOT / "firmware/unified/build-20260924-raw-ingress-v1/manifest.json"
    pinned = json.loads(checkpoint.read_text())
    clang = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    assert clang and zig, "pinned Clang and explicit reviewed Zig required; never skip"
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig), "python": Path(sys.executable)})
    assert tools.hashes == {key: pinned["tool_executables_sha256"][key] for key in tools.hashes}
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    paths = [Path(__file__), checkpoint, ROOT / "whip/fwthumb.py", ROOT / "whip/fwproof_guard.py",
             ROOT / "whip/fwstock_link.py", ROOT / "tests/native/arm_proof.ld",
             ROOT / "firmware/rt02cr-stock-3.12.02.bin",
             ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json",
             *(ROOT / f"firmware/unified/{name}" for name in
               ("control_mailbox.c", "control_mailbox.h", "wire.h", "compiler_runtime.c"))]
    inputs = InputSnapshot({str(p.relative_to(ROOT)): p for p in paths})
    for name in ("wire.h", "compiler_runtime.c"):
        key = "firmware/unified/" + name
        assert inputs.hashes[key] == pinned["inputs_sha256"][key]
    directory = tmp_path_factory.mktemp("control-mailbox")
    build = {"inputs": inputs, "tools": tools, "snapshots": [], "directory": directory}
    flags = pinned["flags"]
    commands = []

    def run(command, outputs, stdin=None):
        verify_build(build)
        result = subprocess.run(command, input=stdin, text=True, capture_output=True, env=env)
        # Snapshot immediately, before another compiler/linker may run.
        for path in outputs:
            if path.exists():
                build["snapshots"].append(InputSnapshot({path.name: path}))
        log = directory / f"command-{len(commands)}.json"
        record = {"command": command, "stdin_sha256": sha(stdin.encode()) if stdin else None,
                  "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        log.write_text(json.dumps(record, indent=2) + "\n")
        build["snapshots"].append(InputSnapshot({log.name: log}))
        commands.append(record)
        verify_build(build)
        assert result.returncode == 0, record
        assert all(path.is_file() for path in outputs)

    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    objects = []
    for name in ("control_mailbox", "compiler_runtime", "abi"):
        pair = [directory / (name + suffix) for suffix in (".o", "-repeat.o")]
        for path in pair:
            source = (["-x", "c", "-"] if name == "abi" else
                      [str(ROOT / f"firmware/unified/{name}.c")])
            run([clang, *flags, "-c", *source, "-o", str(path)],
                (path, path.with_suffix(".su")), ABI if name == "abi" else None)
        assert pair[0].read_bytes() == pair[1].read_bytes()
        assert pair[0].with_suffix(".su").read_bytes() == pair[1].with_suffix(".su").read_bytes()
        objects.append(str(pair[0]))
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
            "-nostdlib", "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
            "-Wl,-e,wr_init", "-Wl,--build-id=none", "-Wl,--no-undefined"]
    elfs = [directory / name for name in ("MAILBOX-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for path in elfs:
        run([*link, "-o", str(path), *objects], (path,))
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    raw = elfs[0].read_bytes()
    obj = ELFFile(BytesIO((directory / "control_mailbox.o").read_bytes()))
    functions = {s.name: s["st_size"] for s in obj.get_section_by_name(".symtab").iter_symbols()
                 if s["st_info"]["type"] == "STT_FUNC" and s["st_size"]}
    assert API <= functions.keys()
    assert not any(s["sh_size"] and s["sh_flags"] & 3 == 3 for s in obj.iter_sections())
    local_stack = {}
    for row in (directory / "control_mailbox.su").read_text().splitlines():
        label, size, kind = row.split("\t")
        assert kind == "static"
        local_stack[label.rsplit(":", 1)[-1]] = int(size)
    report = {"schema": 1, "kind": "artificial-mailbox-code-diagnostic",
              "compiler_flags": flags, "inputs_sha256": inputs.hashes, "tools_sha256": tools.hashes,
              "artifacts_sha256": {k: v for s in build["snapshots"] for k, v in s.hashes.items()},
              "abi_stdin_sha256": sha(ABI.encode()), "identical_double_compile_and_link": True,
              "mailbox_object_text_bytes": obj.get_section_by_name(".text")["sh_size"],
              "function_bytes": functions, "local_stack_bytes": local_stack,
              "mailbox_bytes": MAILBOX_BYTES, "consumer_scratch_bytes": 32,
              "whole_code_fit_proven": False, "ram_or_stack_owned": False,
              "physical_headroom_proven": False, "task_owner_bound": False,
              "deadline_service_bound": False, "hardware_access": False,
              "physical_fence_proven": False, "production_ready": False}
    verify_build(build)
    report_path = directory / "mailbox-code-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    build["snapshots"].append(InputSnapshot({report_path.name: report_path}))
    build.update(elf=raw, report=report)
    yield build
    verify_build(build)


@dataclass
class Model:
    """Semantic two-element FIFO; a storage shadow checks retained private bytes."""
    generation: int = 0
    slots: list = field(default_factory=lambda: [(0, bytes(20)), (0, bytes(20))])
    queued: list = field(default_factory=list)
    head: int = 0
    state: str = "retired"
    reasons: int = 0
    reported: bool = False
    output: bytes = b"\xa5" * 32

    def packed(self):
        flags = ((self.state != "retired") + 64 * len(self.queued) + 256 * self.head
                 + self.reasons + 32 * self.reported)
        return struct.pack("<II", self.generation, flags) + b"".join(
            struct.pack("<I20s", received, frame) for received, frame in self.slots)

    def operate(self, operation, *, generation=1, frame=bytes(20), length=20, received=0,
                reasons=4, now=0, null_mailbox=False, null_output=False, **unused):
        if null_mailbox:
            return 0
        if operation == "init":
            self.generation, self.head = 0, 0
            self.slots, self.queued = [(0, bytes(20)), (0, bytes(20))], []
            self.state, self.reasons, self.reported = "retired", 0, False
            return 0
        if operation == "open":
            allowed = self.state == "retired" and generation > self.generation and generation != 0
            if allowed:
                self.generation, self.state = generation, "open"
            return int(allowed)
        same = self.state != "retired" and generation == self.generation and generation != 0
        if operation == "admitted":
            return int(same and self.state == "open")
        if operation == "post":
            if not same or self.state == "closed":
                return 0
            if frame is None or length != 20 or len(self.queued) == 2:
                self.state, self.reasons, self.reported = "closed", 16, False
                self.queued.clear()
                return 0
            self.slots[(self.head + len(self.queued)) % 2] = (received, frame)
            self.queued.append((received, frame))
            return 1
        if operation == "close":
            if not same or reasons not in (4, 8, 12, 16, 20, 24, 28):
                return 0
            if reasons | self.reasons != self.reasons:
                self.reported = False
            self.reasons |= reasons
            self.state = "closed"
            self.queued.clear()
            return 1
        if operation == "take":
            if null_output:
                return 0
            if self.queued and ((now - self.queued[0][0]) & U32) > 1000:
                self.state, self.reasons, self.reported = "closed", 16, False
                self.queued.clear()
            if self.state == "closed" and not self.reported:
                self.output = struct.pack("<II20sI", self.generation, 0, bytes(20), self.reasons)
                self.reported = True
                return 2
            if self.queued:
                received, frame = self.queued.pop(0)
                self.output = struct.pack("<II20sI", self.generation, received, frame, 0)
                self.head = 1 - self.head
                return 1
            return 0
        if operation == "retire":
            allowed = same and self.state == "closed" and self.reported
            if allowed:
                self.state, self.reasons, self.reported = "retired", 0, False
                self.head = 0
            return int(allowed)
        raise AssertionError(operation)


class MailboxThumb(RuntimeThumb):
    """Narrow state/output/input access; every live shared access must be masked."""
    def __init__(self, raw):
        self.raw, self.operation = raw, None
        self.trace, self.memory_trace = [], []
        self.injection, self.injected = None, False
        self.frame_address, self.frame_length = self.BATCH, 0
        super().__init__(raw)
        self.uc.mem_write(self.OUTPUT - 16, b"\xa5" * 64)

    def _code(self, uc, address, size, opaque):
        super()._code(uc, address, size, opaque)
        if address == self.RETURN:
            return
        mask = uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
        point = len(self.trace)
        self.trace.append((address, mask, bytes(uc.mem_read(address, size)).hex()))
        if self.injection and point == self.injection[0]:
            assert mask == 0, "cannot inject a normal maskable producer while PRIMASK=1"
            self.injected = True
            self.injection[1](self)

    def _access(self, address, size, write):
        end = address + size
        shared = ((self.CONTEXT, self.CONTEXT + MAILBOX_BYTES), (self.OUTPUT, self.OUTPUT + 32))
        stack = ((self.STACK - 0x1000, self.STACK + 32),)
        source = ((self.frame_address, self.frame_address + self.frame_length),)
        permitted = (*shared, *stack) if write else (*shared, *stack, *source, *self.loaded_spans)
        if not any(lo <= address < end <= hi for lo, hi in permitted):
            raise ThumbProofError(f"mailbox access outside exact objects: {address:#x}+{size}")
        needs_mask = any(lo <= address < end <= hi for lo, hi in (*shared, *source))
        mask = self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
        if self.operation and self.operation != "init" and needs_mask:
            assert mask == 1, "live mailbox/input/output access escaped critical section"
        if write and self.STACK - 0x1000 <= address < self.STACK:
            self.stack_low = min(self.stack_low, address)
        self.memory_trace.append((len(self.trace) - 1, address, size, write, mask))

    def _read(self, uc, access, address, size, value, opaque):
        self._access(address, size, False)

    def _write(self, uc, access, address, size, value, opaque):
        self._access(address, size, True)

    def execute(self, operation, *, generation=1, frame=bytes(20), length=20, received=0,
                reasons=4, now=0, null_mailbox=False, null_output=False, bad_pointer=False,
                alignment=0, mask=0, exception=0):
        self.operation = operation
        self.trace, self.memory_trace = [], []
        self.frame_address, self.frame_length = self.BATCH + alignment, 20 if frame is not None else 0
        self.uc.mem_write(self.BATCH - 16, b"\xa5" * 64)
        if frame is not None:
            assert len(frame) == 20
            self.uc.mem_write(self.frame_address, frame)
        input_before = bytes(self.uc.mem_read(self.BATCH - 16, 64))
        pointer = 0xDEAD0000 if bad_pointer else self.frame_address if frame is not None else 0
        mailbox = 0 if null_mailbox else self.CONTEXT
        output = 0 if null_output else self.OUTPUT
        args = {"init": (mailbox,), "open": (mailbox, generation),
                "post": (mailbox, generation, pointer, length, received),
                "close": (mailbox, generation, reasons), "take": (mailbox, now, output),
                "retire": (mailbox, generation), "admitted": (mailbox, generation)}[operation]
        self.uc.reg_write(self.a.UC_ARM_REG_PRIMASK, mask)
        self.uc.reg_write(self.a.UC_ARM_REG_IPSR, exception)
        result = self.call("wim_" + operation, *args, budget=4000)
        assert self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == mask
        assert self.uc.reg_read(self.a.UC_ARM_REG_IPSR) == exception
        assert bytes(self.uc.mem_read(self.BATCH - 16, 64)) == input_before
        for location in (self.OUTPUT - 16, self.OUTPUT + 32):
            assert bytes(self.uc.mem_read(location, 16)) == b"\xa5" * 16
        return 0 if operation == "init" else result


@pytest.fixture
def pair(mailbox_build):
    h, model = MailboxThumb(mailbox_build["elf"]), Model()
    assert h.execute("init") == model.operate("init")
    return h, model


def step(pair, operation, **kwargs):
    h, model = pair
    wanted = model.operate(operation, **kwargs)
    actual = h.execute(operation, **kwargs)
    assert actual == wanted, (operation, kwargs)
    assert bytes(h.uc.mem_read(h.CONTEXT, MAILBOX_BYTES)) == model.packed(), (operation, kwargs)
    assert bytes(h.uc.mem_read(h.OUTPUT, 32)) == model.output, (operation, kwargs)
    return actual


def test_build_is_reproducible_narrow_and_not_production_fit(mailbox_build):
    verify_build(mailbox_build)
    report = mailbox_build["report"]
    assert report["mailbox_bytes"] == MAILBOX_BYTES and report["consumer_scratch_bytes"] == 32
    assert report["mailbox_object_text_bytes"] >= sum(report["function_bytes"].values()) > 0
    assert set(report["local_stack_bytes"]) == set(report["function_bytes"])
    assert not any(report[name] for name in ("whole_code_fit_proven", "ram_or_stack_owned",
                   "physical_headroom_proven", "task_owner_bound", "deadline_service_bound",
                   "hardware_access", "physical_fence_proven", "production_ready"))
    with pytest.raises(ValueError):
        inspect_elf(mailbox_build["elf"], (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes(),
                    (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes())


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("alignment", range(4))
def test_exact_frame_copy_arrival_identity_and_caller_canaries(pair, mask, alignment):
    step(pair, "open", generation=0xFEDCBA98, mask=mask)
    for frame in (bytes(range(20)), bytes(20), b"\xff" * 20):
        # No wire-content validation is promised by this handoff primitive.
        step(pair, "post", generation=0xFEDCBA98, frame=frame, received=U32 - 400,
             alignment=alignment, mask=mask)
        assert step(pair, "take", now=599, mask=mask) == 1  # exactly 1000 ms, across wrap
        assert step(pair, "take", now=600, mask=mask) == 0


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("alignment", range(4))
def test_two_frame_burst_preserves_fifo_payloads_and_individual_arrival_times(pair, mask, alignment):
    step(pair, "open", generation=7, mask=mask)
    for frame, received in ((b"A" * 20, 10), (b"B" * 20, 29)):
        assert step(pair, "post", generation=7, frame=frame, received=received,
                    alignment=alignment, mask=mask)
    assert step(pair, "admitted", generation=7, mask=mask)  # full is not closed
    for frame, received in ((b"A" * 20, 10), (b"B" * 20, 29)):
        assert step(pair, "take", now=30, mask=mask) == 1
        assert pair[1].output == struct.pack("<II20sI", 7, received, frame, 0)
    assert step(pair, "take", now=30, mask=mask) == 0


@pytest.mark.parametrize("mask", [0, 1])
def test_interleaved_refill_wraps_both_heads_without_overwriting_oldest(pair, mask):
    step(pair, "open", mask=mask)
    for cycle in range(6):
        now = cycle * 100
        values = [(now + i, bytes([3 * cycle + i]) * 20) for i in range(3)]
        for received, frame in values[:2]:
            assert step(pair, "post", received=received, frame=frame, mask=mask)
        assert step(pair, "take", now=now + 3, mask=mask) == 1
        assert pair[1].output == struct.pack("<II20sI", 1, *values[0], 0)
        assert step(pair, "post", received=values[2][0], frame=values[2][1], mask=mask)
        for received, frame in values[1:]:
            assert step(pair, "take", now=now + 4, mask=mask) == 1
            assert pair[1].output == struct.pack("<II20sI", 1, received, frame, 0)
        assert step(pair, "take", now=now + 5, mask=mask) == 0
        assert pair[1].head == (cycle + 1) % 2
    # Retire/open resets head bookkeeping but intentionally retains both slots.
    step(pair, "post", received=700, mask=mask)
    step(pair, "take", now=700, mask=mask)
    assert pair[1].head == 1
    step(pair, "close", mask=mask)
    step(pair, "take", now=700, mask=mask)
    step(pair, "retire", mask=mask)
    step(pair, "open", generation=2, mask=mask)
    assert pair[1].head == 0 and step(pair, "admitted", generation=2, mask=mask)


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("generation", [0, 6, 8, U32])
def test_stale_third_frame_does_not_overflow_or_close_current_two_slot_fifo(pair, mask, generation):
    step(pair, "open", generation=7, mask=mask)
    for frame in (b"A" * 20, b"B" * 20):
        step(pair, "post", generation=7, frame=frame, received=10, mask=mask)
    assert not step(pair, "post", generation=generation, bad_pointer=True, mask=mask)
    assert step(pair, "admitted", generation=7, mask=mask)
    for frame in (b"A" * 20, b"B" * 20):
        assert step(pair, "take", now=11, mask=mask) == 1
        assert pair[1].output[8:28] == frame


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("first,second,take_first,take_second", [
    (100, 900, 1100, 1901), (U32 - 500, 50, 499, 1051)])
def test_each_slot_expires_using_its_own_original_timestamp(pair, mask, first, second, take_first, take_second):
    step(pair, "open", mask=mask)
    step(pair, "post", frame=b"A" * 20, received=first, mask=mask)
    step(pair, "post", frame=b"B" * 20, received=second, mask=mask)
    assert step(pair, "take", now=take_first, mask=mask) == 1
    assert pair[1].output == struct.pack("<II20sI", 1, first, b"A" * 20, 0)
    assert step(pair, "take", now=take_second, mask=mask) == 2
    assert not step(pair, "admitted", mask=mask)
    assert step(pair, "take", now=take_second, mask=mask) == 0


@pytest.mark.parametrize("mask", [0, 1])
def test_expired_head_closes_and_drops_even_a_fresh_second_slot(pair, mask):
    step(pair, "open", mask=mask)
    step(pair, "post", frame=b"A" * 20, received=0, mask=mask)
    step(pair, "post", frame=b"B" * 20, received=999, mask=mask)
    assert step(pair, "take", now=1001, mask=mask) == 2
    assert pair[1].output == struct.pack("<II20sI", 1, 0, bytes(20), 16)
    assert step(pair, "take", now=1001, mask=mask) == 0


@pytest.mark.parametrize("mask", [0, 1])
def test_admission_query_preserves_state_and_is_not_a_future_commit_lease(pair, mask):
    assert not step(pair, "admitted", mask=mask)
    step(pair, "open", generation=7, mask=mask)
    assert step(pair, "admitted", generation=7, mask=mask)
    for generation in (0, 6, 8, U32):
        assert not step(pair, "admitted", generation=generation, mask=mask)
    step(pair, "post", generation=7, frame=b"A" * 20, received=0, mask=mask)
    step(pair, "post", generation=7, frame=b"B" * 20, received=1, mask=mask)
    assert step(pair, "take", now=1, mask=mask) == 1
    assert step(pair, "admitted", generation=7, mask=mask)
    delivered = pair[1].output
    step(pair, "close", generation=7, reasons=8, mask=mask)
    assert pair[1].output == delivered
    assert not step(pair, "admitted", generation=7, mask=mask)
    assert step(pair, "take", now=2, mask=mask) == 2  # B is dropped, A cannot be retracted
    assert not step(pair, "admitted", generation=7, mask=mask)
    step(pair, "retire", generation=7, mask=mask)
    assert not step(pair, "admitted", generation=7, mask=mask)


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("length", [0, 1, 19, 21, 255, 0x10000, U32])
def test_bad_current_length_closes_without_dereferencing_frame(pair, mask, length):
    step(pair, "open", mask=mask)
    assert not step(pair, "post", length=length, bad_pointer=True, mask=mask)
    assert step(pair, "take", mask=mask) == 2
    assert step(pair, "take", mask=mask) == 0


@pytest.mark.parametrize("mask", [0, 1])
def test_nulls_stale_and_not_open_inputs_do_not_touch_unrelated_state(pair, mask):
    for op in ("init", "open", "post", "close", "take", "retire", "admitted"):
        step(pair, op, null_mailbox=True, bad_pointer=True, mask=mask)
    step(pair, "post", generation=0, bad_pointer=True, mask=mask)
    step(pair, "open", generation=10, mask=mask)
    step(pair, "post", generation=10, received=50, mask=mask)
    for generation in (0, 1, 9, 11, U32):
        for op in ("post", "close", "retire", "open", "admitted"):
            step(pair, op, generation=generation, bad_pointer=True, length=20, mask=mask)
    assert step(pair, "take", now=100, null_output=True, mask=mask) == 0
    assert step(pair, "take", now=100, mask=mask) == 1
    assert not step(pair, "post", generation=10, frame=None, mask=mask)
    assert step(pair, "take", mask=mask) == 2


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("why", [0, 1, 2, 3, 32, 36, 0x80000000, U32])
def test_invalid_close_reasons_are_atomic_refusal(pair, mask, why):
    step(pair, "open", mask=mask)
    step(pair, "post", received=0, mask=mask)
    assert not step(pair, "close", reasons=why, mask=mask)
    assert step(pair, "take", now=0, mask=mask) == 1


@pytest.mark.parametrize("mask", [0, 1])
def test_overflow_close_priority_reasons_rereport_and_retirement(pair, mask):
    step(pair, "open", generation=7, mask=mask)
    step(pair, "post", generation=7, received=91, frame=b"x" * 20, mask=mask)
    assert step(pair, "post", generation=7, received=92, frame=b"y" * 20, mask=mask)
    assert not step(pair, "post", generation=7, received=93, frame=b"z" * 20, mask=mask)
    assert not step(pair, "retire", generation=7, mask=mask)
    assert step(pair, "take", now=92, mask=mask) == 2
    step(pair, "close", generation=7, reasons=16, mask=mask)
    assert step(pair, "take", mask=mask) == 0  # duplicate reason does not re-report
    step(pair, "close", generation=7, reasons=4, mask=mask)
    assert not step(pair, "retire", generation=7, mask=mask)
    assert step(pair, "take", mask=mask) == 2
    step(pair, "close", generation=7, reasons=8, mask=mask)
    assert step(pair, "take", mask=mask) == 2
    assert not step(pair, "post", generation=7, bad_pointer=True, mask=mask)
    assert not step(pair, "open", generation=8, mask=mask)
    assert step(pair, "retire", generation=7, mask=mask)
    assert not step(pair, "open", generation=7, mask=mask)
    assert step(pair, "open", generation=8, mask=mask)
    assert not step(pair, "close", generation=7, reasons=28, mask=mask)
    assert step(pair, "take", mask=mask) == 0


@pytest.mark.parametrize("mask", [0, 1])
def test_generation_exhaustion_never_wraps_or_reuses(pair, mask):
    assert not step(pair, "open", generation=0, mask=mask)
    assert step(pair, "open", generation=U32, mask=mask)
    step(pair, "close", generation=U32, mask=mask)
    step(pair, "take", mask=mask)
    step(pair, "retire", generation=U32, mask=mask)
    for generation in (0, 1, U32 - 1, U32):
        assert not step(pair, "open", generation=generation, mask=mask)


@pytest.mark.parametrize("received,age", [(0, 0), (0, 999), (0, 1000), (0, 1001),
                                         (U32 - 200, 1000), (U32 - 200, 1001),
                                         (123, 0x7FFFFFFF), (123, U32)])
@pytest.mark.parametrize("mask", [0, 1])
def test_unsigned_age_boundary_and_wrap(pair, received, age, mask):
    step(pair, "open", mask=mask)
    step(pair, "post", received=received, mask=mask)
    assert step(pair, "take", now=(received + age) & U32, mask=mask) == (1 if age <= 1000 else 2)
    # age U32 is deliberately invalid caller chronology, tested as fail-closed,
    # not support for ambiguous intervals >= 2**31.


@pytest.mark.parametrize("mask", [0, 1])
def test_close_after_take_does_not_retract_already_delivered_frame(pair, mask):
    step(pair, "open", mask=mask)
    step(pair, "post", frame=b"f" * 20, received=50, mask=mask)
    assert step(pair, "take", now=51, mask=mask) == 1
    delivered = pair[1].output
    step(pair, "close", reasons=4, mask=mask)
    assert pair[1].output == delivered  # downstream commit still needs its own gate
    assert step(pair, "take", now=52, mask=mask) == 2


@pytest.mark.parametrize("mask", [0, 1])
@pytest.mark.parametrize("exception", [16, 31, 63])
def test_maskable_irq_producers_preserve_context_without_calling_consumer(pair, mask, exception):
    step(pair, "open")
    step(pair, "post", frame=b"I" * 20, received=0, mask=mask, exception=exception)
    assert pair[1].output == b"\xa5" * 32
    step(pair, "close", reasons=4, mask=mask, exception=exception)
    assert pair[1].output == b"\xa5" * 32
    assert step(pair, "take", now=1) == 2  # separate thread-owner call


@pytest.mark.parametrize("seed", [0x57494D, 0xA51, 0x203800, 0xFFFFFFFF])
def test_randomized_persistent_sequences_match_independent_model(pair, seed):
    rng = random.Random(seed)
    now = U32 - 500
    for _ in range(700):
        model = pair[1]
        op = rng.choice(("open", "post", "post", "take", "take", "close", "retire", "admitted"))
        now = (now + rng.randrange(0, 1600)) & U32
        generation = rng.choice((0, model.generation, min(model.generation + 1, U32),
                                 max(0, model.generation - 1)))
        frame = None if rng.randrange(8) == 0 else bytes(rng.randrange(256) for _ in range(20))
        step(pair, op, generation=generation, frame=frame,
             length=rng.choice((0, 19, 20, 20, 20, 21, U32)), received=now, now=now,
             reasons=rng.choice((0, 1, 4, 8, 12, 16, 20, 24, 28, 32)),
             mask=rng.randrange(2), alignment=rng.randrange(4),
             null_output=rng.randrange(40) == 0, null_mailbox=rng.randrange(50) == 0)


INTERLEAVINGS = [
    ("post_close", [], "post", {"received": 40}, "close", {"reasons": 4}),
    ("post_post", [], "post", {"received": 40}, "post", {"received": 41, "frame": b"i" * 20}),
    ("take_close", [("post", {"received": 40})], "take", {"now": 41}, "close", {"reasons": 8}),
    ("take_post", [("post", {"received": 40})], "take", {"now": 41}, "post", {"received": 41}),
    ("take_empty_post", [], "take", {"now": 41}, "post", {"received": 41}),
    ("close_post", [], "close", {"reasons": 4}, "post", {"received": 41}),
    ("close_new_reason", [("close", {"reasons": 4}), ("take", {})],
     "close", {"reasons": 8}, "close", {"reasons": 16}),
    ("stale_post_close", [], "post", {"generation": 2, "bad_pointer": True}, "close", {"reasons": 4}),
    ("post_second_close", [("post", {"received": 40})],
     "post", {"received": 41}, "close", {"reasons": 8}),
    ("take_full_post", [("post", {"received": 40}), ("post", {"received": 41})],
     "take", {"now": 42}, "post", {"received": 42}),
    ("take_full_close", [("post", {"received": 40}), ("post", {"received": 41})],
     "take", {"now": 42}, "close", {"reasons": 4}),
    ("take_wrapped_full_post", [("post", {"received": 40}), ("take", {"now": 40}),
                                 ("post", {"received": 41}), ("post", {"received": 42})],
     "take", {"now": 43}, "post", {"received": 43}),
    ("admitted_close", [], "admitted", {}, "close", {"reasons": 4}),
    ("admitted_full_third_post", [("post", {"received": 40}), ("post", {"received": 41})],
     "admitted", {}, "post", {"received": 42}),
]


@pytest.mark.parametrize("case", INTERLEAVINGS, ids=[case[0] for case in INTERLEAVINGS])
def test_every_legal_unmasked_instruction_boundary_serializes_producer(mailbox_build, case):
    _, setup, outer, outer_args, producer, producer_args = case

    def fresh():
        pair = (MailboxThumb(mailbox_build["elf"]), Model())
        step(pair, "init")
        step(pair, "open")
        for op, args in setup:
            step(pair, op, **args)
        return pair

    baseline, model = fresh()
    step((baseline, model), outer, **outer_args)
    points = [index for index, (_, mask, _) in enumerate(baseline.trace) if mask == 0]
    assert points and any(mask for _, mask, _ in baseline.trace)
    memory_points = {event[0] for event in baseline.memory_trace if event[4] == 0}
    assert memory_points <= set(points)
    seen_before = seen_after = 0
    for point in points:
        h, model = fresh()
        after_commit = any(mask for _, mask, _ in baseline.trace[:point])
        if after_commit:
            wanted = model.operate(outer, **outer_args)
            producer_wanted = model.operate(producer, **producer_args)
            seen_after += 1
        else:
            producer_wanted = model.operate(producer, **producer_args)
            wanted = model.operate(outer, **outer_args)
            seen_before += 1

        def interrupt(current):
            other = MailboxThumb(mailbox_build["elf"])
            other.uc.mem_write(other.CONTEXT, bytes(current.uc.mem_read(current.CONTEXT, MAILBOX_BYTES)))
            result = other.execute(producer, **producer_args)
            assert result == producer_wanted
            current.uc.mem_write(current.CONTEXT, bytes(other.uc.mem_read(other.CONTEXT, MAILBOX_BYTES)))

        h.injection = (point, interrupt)
        assert h.execute(outer, **outer_args) == wanted
        assert h.injected
        assert bytes(h.uc.mem_read(h.CONTEXT, MAILBOX_BYTES)) == model.packed()
        assert bytes(h.uc.mem_read(h.OUTPUT, 32)) == model.output
    assert seen_before and seen_after
    # Starting masked exposes no legal normal-IRQ preemption boundary.
    h, model = fresh()
    step((h, model), outer, **outer_args, mask=1)
    assert all(mask == 1 for _, mask, _ in h.trace)


def test_live_reads_and_writes_require_mask_and_strict_spans_detect_harness_misuse(pair):
    h, _ = pair
    h.operation = "post"
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, 0)
    with pytest.raises(AssertionError, match="escaped critical section"):
        h._access(h.CONTEXT, 4, False)
    with pytest.raises(ThumbProofError, match="outside exact objects"):
        h._access(h.CONTEXT + MAILBOX_BYTES, 1, True)
    with pytest.raises(ThumbProofError, match="outside exact objects"):
        h._access(h.OUTPUT + 32, 1, True)


@pytest.mark.parametrize("which", ["mask", "restore"])
def test_missing_mask_or_restore_instruction_mutants_are_detected(mailbox_build, which):
    # Explicit negative ELF only: original source/object/ELF and provenance stay
    # untouched. Mutation scope is one generated function, not geometry approval.
    raw = bytearray(mailbox_build["elf"])
    elf = ELFFile(BytesIO(raw))
    symbol = next(s for s in elf.get_section_by_name(".symtab").iter_symbols() if s.name == "wim_post")
    section = elf.get_section(symbol["st_shndx"])
    start = section["sh_offset"] + (symbol["st_value"] & ~1) - section["sh_addr"]
    body = bytes(raw[start:start + symbol["st_size"]])
    if which == "mask":
        locations = [i for i in range(0, len(body) - 1, 2) if body[i:i + 2] == b"\x72\xb6"]
        assert len(locations) == 1
        offset, size = locations[0], 2
    else:
        # Thumb MSR PRIMASK, Rn: F38n 8810. Do not mutate MRS or any other system register.
        locations = [i for i in range(0, len(body) - 3, 2)
                     if body[i] & 0xF0 == 0x80 and body[i + 1:i + 4] == b"\xf3\x10\x88"]
        assert len(locations) == 1
        offset, size = locations[0], 4
    raw[start + offset:start + offset + size] = b"\x00\xbf" * (size // 2)
    h = MailboxThumb(bytes(raw))
    h.execute("init")
    h.execute("open")
    with pytest.raises(AssertionError, match="escaped critical section" if which == "mask" else None):
        h.execute("post", received=1)
    verify_build(mailbox_build)
