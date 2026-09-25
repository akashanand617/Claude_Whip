"""Exact saved ROM-read replay and wrapper execution; no device I/O.

The code bytes were captured. Out-of-window literals, hook pointer/content and
fallback implementations are synthetic boundaries, NOT further device reads.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import struct

import pytest

from whip import fwrom_read as rr, protocol

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-23/rom-timers"
CODE_SHA256 = "bf0174582ef92307490e0cdcf0802c912f6f36d8946aac5208f641ad81514e88"


@pytest.mark.parametrize("name,digest", [
    ("rom-timers.json", "4290a08b6703c6b3e2ddf262285a28100368253ccff6a46b9116d31df039f16d"),
    ("transcript.jsonl", "fa32687d8e7f15a83c721ff2678f1fc9273d1245eea08b514bc42a9854962a78"),
])
def test_archive_hash(name, digest):
    assert hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("directory,capture_name,plan,count", [
    ("rom-timers", "rom-timers.json", "rom-timers-v1", 114),
    ("rom-timer-internals", "rom-timer-internals.json", "rom-timer-internals-v1", 142),
    ("rom-timer-hooks", "rom-timer-hooks.json", "rom-timer-hooks-v1", 144),
])
def test_actual_transactions_replay_and_reproduce_capture(directory, capture_name, plan, count):
    archive = ARCHIVE.parent / directory
    saved = json.loads((archive / capture_name).read_text())
    rows = [json.loads(s) for s in (archive / "transcript.jsonl").read_text().splitlines()]
    assert rows[0]["plan"] == plan
    assert rows[-2] == {"kind": "disconnected", "confirmed": True}
    assert rows[-1]["kind"] == "completed" and not rows[-1]["flash_authorized"]
    pairs = [row for row in rows if row["kind"] in ("request", "reply")]
    assert len(pairs) == count * 2
    for request, reply in zip(pairs[::2], pairs[1::2], strict=True):
        assert (request["kind"], reply["kind"]) == ("request", "reply")
        assert (request["address"], request["length"]) == (reply["address"], reply["length"])
        assert request["monotonic"] < reply["monotonic"]
        for row in (request, reply):
            p = bytes.fromhex(row["packet"])
            assert len(p) == 16 and protocol.checksum(p[:-1]) == p[-1]
        p = bytes.fromhex(request["packet"])
        assert p[:2] == b"\xcd\x01" and p[2] == request["length"]
        assert int.from_bytes(p[3:7], "big") == request["address"]

    class Replay:
        index = 0

        async def write_gatt_char(self, uuid, packet, *, response):
            assert uuid == protocol.UART_RX_CHAR_UUID and response is False
            assert bytes(packet).hex() == pairs[self.index]["packet"]
            self.reader.notify(None, bytes.fromhex(pairs[self.index + 1]["packet"]))
            self.index += 2

    client = Replay()
    internal = count >= 142
    reader_class = rr.ROMInternalsReader if internal else rr.ROMTimerReader
    if count == 144: reader_class = rr.ROMHookReader
    client.reader = reader_class(client, lambda _: None, spacing=0)
    args = (client.reader,
        (ROOT / "firmware/rt02cr-25hz.bin").read_bytes(),
        (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes(),
        (ROOT / "firmware/research/2026-09-22/rom_symbol_gcc.axf").read_bytes(), saved["session_id"])
    if count == 144:
        task = rr.collect_rom_hooks(*args, (ARCHIVE / "rom-timers.json").read_bytes(),
            (ARCHIVE.parent / "rom-timer-internals/rom-timer-internals.json").read_bytes())
    elif internal:
        task = rr.collect_rom_internals(*args, (ARCHIVE / "rom-timers.json").read_bytes())
    else:
        task = rr.collect_rom_timers(*args)
    actual = asyncio.run(task)
    assert actual == saved and client.index == count * 2
    assert client.reader.closed and not client.reader.poisoned
    code = bytes.fromhex(actual["timer_code"]["data_hex"])
    assert len(code) == 72 and hashlib.sha256(code).hexdigest() == CODE_SHA256


@pytest.mark.parametrize("which", ["stop", "delete"])
@pytest.mark.parametrize("hook,handled,result,fallback", [
    (False, False, 0, 0), (False, False, 0, 1),
    (True, False, 1, 0), (True, False, 0, 1),
    (True, True, 0, 1), (True, True, 1, 0),
    (True, True, 255, 0), (True, False, 255, 7),
])
def test_actual_rom_wrapper_hook_result_and_fallback(which, hook, handled, result, fallback):
    import unicorn as u
    from unicorn import arm_const as a

    code = bytes.fromhex(json.loads((ARCHIVE / "rom-timers.json").read_text())["timer_code"]["data_hex"])
    assert hashlib.sha256(code).hexdigest() == CODE_SHA256
    start, literal, callee = ((0x136BC, 0x137F8, 0x140CE) if which == "stop"
                              else (0x136E0, 0x137FC, 0x14124))
    # The PC-relative literal addresses are decoded from actual captured LDRs.
    ldr = struct.unpack_from("<H", code, start + 4 - 0x136BC)[0]
    assert ldr >> 8 == 0x48
    assert ((start + 8) & ~3) + (ldr & 255) * 4 == literal
    uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
    uc.mem_map(0x13000, 0x2000, u.UC_PROT_READ | u.UC_PROT_EXEC)
    uc.mem_map(0x300000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)
    uc.mem_write(0x136BC, code)
    slot, callback, returned, sp = 0x300000, 0x14F00, 0x14F10, 0x302000
    uc.mem_write(literal, struct.pack("<I", slot))  # UNREAD literal: explicit fixture.
    uc.mem_write(slot, struct.pack("<I", (callback | 1) if hook else 0))
    uc.mem_write(sp - 32, b"\xA5" * 32)
    calls, done = [], []

    def observe_code(cpu, pc, size, _):
        if pc == returned:
            done.append(True)
            cpu.emu_stop()
            return
        if pc == callback:
            assert cpu.reg_read(a.UC_ARM_REG_R0) == 0x12345678
            assert cpu.reg_read(a.UC_ARM_REG_R1) == sp - 16
            calls.append("hook")
            cpu.mem_write(sp - 16, bytes([result]))
            cpu.reg_write(a.UC_ARM_REG_R0, int(handled))
            cpu.reg_write(a.UC_ARM_REG_PC, cpu.reg_read(a.UC_ARM_REG_LR))
        elif pc == callee:
            assert cpu.reg_read(a.UC_ARM_REG_R0) == 0x12345678
            calls.append("fallback")
            cpu.reg_write(a.UC_ARM_REG_R0, fallback)
            cpu.reg_write(a.UC_ARM_REG_PC, cpu.reg_read(a.UC_ARM_REG_LR))
        else:
            assert start <= pc < pc + size <= start + 36

    def observe_memory(cpu, access, address, size, value, _):
        if access == u.UC_MEM_WRITE:
            assert sp - 16 <= address < address + size <= sp
        else:
            assert (sp - 16 <= address < address + size <= sp or
                    (address, size) in ((literal, 4), (slot, 4)))

    uc.hook_add(u.UC_HOOK_CODE, observe_code)
    uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, observe_memory)
    uc.reg_write(a.UC_ARM_REG_R0, 0x12345678)  # Never dereferenced by the wrapper.
    uc.reg_write(a.UC_ARM_REG_R4, 0x456789AB)
    uc.reg_write(a.UC_ARM_REG_R5, 0x98765432)
    uc.reg_write(a.UC_ARM_REG_SP, sp)
    uc.reg_write(a.UC_ARM_REG_LR, returned | 1)
    uc.emu_start(start | 1, 0, count=100)
    assert done == [True]
    assert uc.reg_read(a.UC_ARM_REG_SP) == sp
    assert uc.reg_read(a.UC_ARM_REG_R4) == 0x456789AB
    assert uc.reg_read(a.UC_ARM_REG_R5) == 0x98765432
    assert uc.reg_read(a.UC_ARM_REG_R0) == (result if hook and handled else fallback)
    assert calls == (["hook"] if hook and handled else (["hook", "fallback"] if hook else ["fallback"]))


@pytest.mark.parametrize("name,digest", [
    ("rom-timer-internals.json", "79fe567846b308a081d6820ce552b45fba107470f2258035d67e4cd2d1c88525"),
    ("transcript.jsonl", "cd7bee72e54f8a3d346c8b835e0eed4cf29c8c4cfaa6c99741b622f1a774f9c7"),
])
def test_internal_archive_hash(name, digest):
    assert hashlib.sha256((ARCHIVE.parent / "rom-timer-internals" / name).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("name,digest", [
    ("rom-timer-hooks.json", "1551f253f43fbd3b852f866ea76da07084c503124406ae38a3acbdfbb028de53"),
    ("transcript.jsonl", "9bc112033d125cbd9d0da037e4ed085f8a4751522e0518dcb1f8cf7f8133f504"),
])
def test_hook_archive_hash(name, digest):
    assert hashlib.sha256((ARCHIVE.parent / "rom-timer-hooks" / name).read_bytes()).hexdigest() == digest
