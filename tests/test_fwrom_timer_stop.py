"""Execute captured wrappers + defaults; unread ROM/state remain explicit mocks.

No device I/O. No claim about actual hook contents, scheduler/queue internals,
callback drain or physical shutdown follows from this selected-code proof.
"""
import hashlib
import json
from pathlib import Path
import struct

import pytest

ARCHIVE = Path(__file__).resolve().parents[1] / "firmware/research/2026-09-23/rom-timer-internals"


def captured():
    raw = (ARCHIVE / "rom-timer-internals.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "79fe567846b308a081d6820ce552b45fba107470f2258035d67e4cd2d1c88525"
    report = json.loads(raw)
    hook_raw = (ARCHIVE.parent / "rom-timer-hooks/rom-timer-hooks.json").read_bytes()
    assert hashlib.sha256(hook_raw).hexdigest() == "1551f253f43fbd3b852f866ea76da07084c503124406ae38a3acbdfbb028de53"
    hook_capture = json.loads(hook_raw)
    assert hook_capture["internal_windows"] == report["internal_windows"]
    assert hook_capture["timer_code"] == report["timer_code"]
    windows = [report["timer_code"], *report["internal_windows"].values(), hook_capture["hook_slots"]]
    for w in windows:
        assert hashlib.sha256(bytes.fromhex(w["data_hex"])).hexdigest() == w["sha256"]
    return windows


@pytest.mark.parametrize("which", ["stop", "delete"])
@pytest.mark.parametrize("case", ["task_ok", "isr_ok", "isr_wake", "task_fail", "isr_fail",
                                  "nonboolean", "null_argument", "empty_handle", "gate_blocked"])
def test_actual_defaults_forward_command_result_without_additional_drain_call(which, case):
    import unicorn as u
    from unicorn import arm_const as a

    uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
    uc.mem_map(0x10000, 0x5000, u.UC_PROT_READ | u.UC_PROT_EXEC)
    uc.mem_map(0x201000, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
    uc.mem_map(0x300000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)
    for w in captured(): uc.mem_write(w["address"], bytes.fromhex(w["data_hex"]))

    start, end, slot, default, default_end = ((0x136BC, 0x136E0, 0x201650, 0x140CE, 0x14124)
        if which == "stop" else (0x136E0, 0x13704, 0x201654, 0x14124, 0x14154))
    literal = 0x137F8 if which == "stop" else 0x137FC
    assert struct.unpack("<I", uc.mem_read(literal, 4))[0] == slot  # Actual captured literal.
    # Actual repeated idle snapshot: no hook installed THEN. This does not claim
    # hook state is immutable across initialization, sleep or other operations.
    assert bytes(uc.mem_read(slot, 4)) == bytes(4)
    handle_at, handle, gate_at, yield_at, sp, returned = 0x300000, 0x300100, 0x300040, 0x300080, 0x302000, 0x14F00
    empty = case == "empty_handle"
    uc.mem_write(handle_at, struct.pack("<I", 0 if empty else handle))
    # These two external literals were not captured. Never treat these synthetic
    # RAM locations as the ring's state block or scheduling peripheral address.
    uc.mem_write(0x1424C, struct.pack("<I", gate_at))
    uc.mem_write(0x14248, struct.pack("<I", yield_at))
    uc.mem_write(gate_at + 0x19, bytes([1 if case == "gate_blocked" else 0]))
    uc.mem_write(sp - 80, b"\xA5" * 80)
    is_task = not case.startswith("isr")
    queued = 0 if case.endswith("fail") else (2 if case == "nonboolean" else 1)
    wake = case == "isr_wake"
    calls, stores, done = [], [], []

    def ret(value):
        uc.reg_write(a.UC_ARM_REG_R0, value)
        uc.reg_write(a.UC_ARM_REG_PC, uc.reg_read(a.UC_ARM_REG_LR))

    def code(cpu, pc, size, _):
        if pc == returned:
            done.append(True); cpu.emu_stop(); return
        if pc == 0x14238:  # Unread context detector; synthetic result.
            assert which == "stop"
            calls.append(("context",))
            ret(int(is_task)); return
        if pc == 0x108E0:  # Symbol-pinned xTimerGenericCommand, body unread.
            r0, r1, r2, r3 = [cpu.reg_read(r) for r in
                (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)]
            current_sp = cpu.reg_read(a.UC_ARM_REG_SP)
            fifth = struct.unpack("<I", cpu.mem_read(current_sp, 4))[0]
            assert (r0, r2, fifth) == (handle, 0, 0)
            expected_command = 5 if which == "delete" else (3 if is_task else 8)
            assert r1 == expected_command
            if which == "stop" and not is_task:
                assert r3 == current_sp + 4
                cpu.mem_write(r3, struct.pack("<I", int(wake)))
            else:
                assert r3 == 0
            calls.append(("command", r1))
            # Do not execute/dequeue any pending callback; this mock deliberately
            # returns only command-boundary success/failure.
            ret(queued); return
        assert start <= pc < pc + size <= end or default <= pc < pc + size <= default_end

    def memory(cpu, access, address, size, value, _):
        stack = sp - 32 <= address < address + size <= sp
        if access == u.UC_MEM_WRITE:
            assert stack or (address, size) in ((handle_at, 4), (yield_at + 4, 4))
            if not stack: stores.append((address, size, value))
        else:
            assert stack or (address, size) in ((literal, 4), (slot, 4), (handle_at, 4),
                (0x1424C, 4), (gate_at + 0x19, 1), (0x14248, 4))

    uc.hook_add(u.UC_HOOK_CODE, code)
    uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, memory)
    uc.reg_write(a.UC_ARM_REG_R0, 0 if case == "null_argument" else handle_at)
    uc.reg_write(a.UC_ARM_REG_R4, 0xABCDEF01)
    uc.reg_write(a.UC_ARM_REG_R5, 0x12345678)
    uc.reg_write(a.UC_ARM_REG_SP, sp)
    uc.reg_write(a.UC_ARM_REG_LR, returned | 1)
    uc.emu_start(start | 1, 0, count=200)
    assert done == [True] and uc.reg_read(a.UC_ARM_REG_SP) == sp
    assert (uc.reg_read(a.UC_ARM_REG_R4), uc.reg_read(a.UC_ARM_REG_R5)) == (0xABCDEF01, 0x12345678)
    early = case in ("null_argument", "empty_handle", "gate_blocked")
    success = not early and (bool(queued) if which == "delete" else queued == 1)
    assert uc.reg_read(a.UC_ARM_REG_R0) == int(success)
    assert calls == ([] if early else (([("context",)] if which == "stop" else [])
        + [("command", 5 if which == "delete" else (3 if is_task else 8))]))
    final_handle = struct.unpack("<I", uc.mem_read(handle_at, 4))[0]
    assert final_handle == (0 if empty or (which == "delete" and success) else handle)
    expected_stores = ([(handle_at, 4, 0)] if which == "delete" and success else [])
    if which == "stop" and wake and not early: expected_stores.append((yield_at + 4, 4, 1 << 28))
    assert stores == expected_stores
