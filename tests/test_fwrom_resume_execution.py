"""Captured timer wrappers, defaults and allocation; OFFLINE synthetic state.

No ring I/O. Hook/config values, context/ticks, division, critical-section
serialization, list and queue bodies are explicit substitutes where used.
Captured arithmetic is executed, but its unread division callee is not proved.
"""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from tests.test_fwrom_execution import CAPTURE
from whip.fwrom_execution import ROMHarness, ROMAssertion, ROMBoundaryError
from whip.fwrom_resume import WINDOWS

ROOT = Path(__file__).resolve().parents[1]
RESUME = ROOT / "firmware/research/2026-09-23/rom-timer-resume/rom-timer-resume-code.json"
SLOT, TIMER, BITMAP, QUEUE = 0x300100, 0x300800, 0x300C00, 0x300D00
HOOK = 0x48000
ENTRIES = {"create": (0x13634, 0x13F9E, 0x201644),
           "start": (0x13670, 0x13FF6, 0x201648),
           "restart": (0x13694, 0x1405E, 0x20164C)}


class ResumeHarness(ROMHarness):
    def __init__(self):
        super().__init__(CAPTURE)
        raw = RESUME.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == "b09002f65a8b1ff4dbe1ba0aea54c79e2043a4f0ebd0683921229a731ae74064"
        saved = json.loads(raw)
        assert saved["repeated_equal"] and not saved["flash_authorized"]
        for name, address, length in WINDOWS:
            w = saved["windows"][name]
            data = bytes.fromhex(w["data_hex"])
            assert w["address"] == address and len(data) == length
            assert hashlib.sha256(data).hexdigest() == w["sha256"]
            self.uc.mem_write(address, data)
            self.windows[address] = data
            self.readable.append((address, address + length))
        self.synthetic_literals = {}
        self.select(0x13634, 0x136BC)

    def missing_literal_fixture(self, address, value):
        # These ROM words were NOT captured. Separate opt-in prevents silently
        # treating zero-filled mapped memory or an analogous literal as evidence.
        assert address in (0x14248, 0x1424C, 0x14250)
        assert not self.contains(self.readable, address, 4)
        self.uc.mem_write(address, struct.pack("<I", value))
        self.readable.append((address, address + 4))
        self.synthetic_literals[address] = value

    def defaults(self):
        # Never admit the embedded data at 0x14028..0x14034 as instructions.
        for lo, hi in ((0x13F9E, 0x13FF6), (0x13FF6, 0x14028),
                       (0x14034, 0x1405E), (0x1405E, 0x140CE)):
            self.select(lo, hi)


@pytest.mark.parametrize("which", ENTRIES)
@pytest.mark.parametrize("hook,handled,result,fallback", [
    (False, 0, 0, 0), (False, 0, 0, 1),
    (True, 0, 255, 7), (True, 1, 0, 1), (True, 1, 255, 0), (True, 7, 1, 0),
])
def test_captured_wrappers_preserve_all_arguments_and_distinguish_hook_result(which, hook, handled, result, fallback):
    h = ResumeHarness()
    entry, default, slot = ENTRIES[which]
    h.fixture(slot, struct.pack("<I", HOOK | 1 if hook else 0))  # NOT a device snapshot
    args = {"create": (SLOT, 0x12345678, 0x9ABCDEF0, 17, 1, 0x47101),
            "start": (SLOT,), "restart": (SLOT, 17)}[which]
    seen = []

    def override(cpu, regs):
        sp = cpu.uc.reg_read(cpu.a.UC_ARM_REG_SP)
        if which == "create":
            assert regs == args[:4]
            assert (cpu.word(sp), cpu.word(sp + 4)) == args[4:]
            result_at = cpu.word(sp + 8)
        elif which == "start":
            assert regs[0] == args[0]
            result_at = regs[1]
        else:
            assert regs[:2] == args
            result_at = regs[2]
        assert h.STACK - 56 <= result_at < h.STACK
        cpu.uc.mem_write(result_at, bytes([result]))
        seen.append("hook")
        # A declining hook may clobber every caller-saved argument register.
        for register in (cpu.a.UC_ARM_REG_R1, cpu.a.UC_ARM_REG_R2, cpu.a.UC_ARM_REG_R3):
            cpu.uc.reg_write(register, 0xDEADC0DE)
        cpu.return_value(handled)

    def fallback_body(cpu, regs):
        assert regs[:min(4, len(args))] == args[:4]
        if which == "create":
            sp = cpu.uc.reg_read(cpu.a.UC_ARM_REG_SP)
            assert (cpu.word(sp), cpu.word(sp + 4)) == args[4:]
        seen.append("fallback")
        cpu.return_value(fallback)

    h.mock(HOOK, "synthetic optional hook", override)
    h.mock(default, "isolated default-boundary substitute", fallback_body)
    assert h.call(entry, *args) == (result if hook and handled else fallback)
    assert seen == (["hook"] if hook and handled else (["hook", "fallback"] if hook else ["fallback"]))
    assert not h.writes


def kernel_create_harness(*, free=True, allocated=False, reload=0, period=2):
    h = ResumeHarness()
    h.defaults()
    for lo, hi in ((0x10774, 0x107E8), (0x10ABC, 0x10AF8),
                   (0x10B5C, 0x10BD8), (0x10A92, 0x10A96)):
        h.select(lo, hi)
    state = bytearray(0x28)
    struct.pack_into("<I", state, 4, QUEUE)  # existing queue avoids queue creation
    struct.pack_into("<IIII", state, 0xC, TIMER if free else 0,
                     TIMER if free else 0, TIMER, BITMAP)
    h.fixture(0x201474, state, writable=True)
    timer = bytearray(b"\xa5" * 48)
    struct.pack_into("<I", timer, 0x24, 0)
    struct.pack_into("<I", timer, 0x2C, 0)
    h.fixture(TIMER, timer, writable=True)
    h.fixture(BITMAP, struct.pack("<I", int(allocated)), writable=True)
    for addr in (0x110C4, 0x110E0, 0x1105E, 0x11080):
        h.mock(addr, "out-of-scope critical-section serialization", lambda c, r: c.return_value())
    # List-item and log helpers are not executed or assumed to clear all bytes.
    h.mock(0xE89A, "unread list-item initializer", lambda c, r: c.return_value())
    h.mock(0x5E6A, "unread log identifier helper", lambda c, r: c.return_value(0x77))
    h.mock(0x5AA8, "unread diagnostic log", lambda c, r: c.return_value())
    return h, timer, (0x12345678, period, reload, 0x9ABCDEF0, 0x47101)


@pytest.mark.parametrize("reload", [0, 1, 2, 0xFFFFFFFF])
def test_captured_kernel_create_allocates_new_identity_and_callback_but_does_not_start(reload):
    h, original, args = kernel_create_harness(reload=reload)
    assert h.call(0x10B5C, *args) == TIMER
    expected = bytearray(original)
    struct.pack_into("<I", expected, 0, args[0])
    struct.pack_into("<III", expected, 0x18, args[1], args[3], args[4])
    expected[0x28] = 4 if reload else 0  # autoreload, not active
    assert bytes(h.uc.mem_read(TIMER, 48)) == expected
    assert h.word(BITMAP) == 1 and h.word(0x201480) == h.word(0x201484) == 0
    assert int.from_bytes(h.uc.mem_read(0x201474, 2), "little") == 1
    assert not any(c.address == 0x108E0 for c in h.calls)
    assert [c.registers[0] for c in h.calls if c.address == 0xE89A] == [TIMER + 4]
    # The real list-item body is missing: sentinel list bytes deliberately stay.


@pytest.mark.parametrize("free,allocated", [(False, False), (True, True)])
def test_captured_allocator_refuses_empty_or_marked_free_head_without_mutating_pool(free, allocated):
    h, timer, args = kernel_create_harness(free=free, allocated=allocated)
    before = bytes(h.uc.mem_read(0x201474, 0x28))
    assert h.call(0x10B5C, *args) == 0
    assert bytes(h.uc.mem_read(TIMER, 48)) == timer
    assert bytes(h.uc.mem_read(0x201474, 0x28)) == before
    assert h.word(BITMAP) == int(allocated) and not h.writes


def test_zero_native_period_asserts_after_pool_allocation_without_rollback():
    h, _, args = kernel_create_harness(period=0)
    with pytest.raises(ROMAssertion): h.call(0x10B5C, *args)
    assert h.word(BITMAP) == 1 and h.word(0x201480) == h.word(0x201484) == 0
    assert int.from_bytes(h.uc.mem_read(0x201474, 2), "little") == 1
    assert bytes(h.uc.mem_read(TIMER + 0x28, 1)) == b"\0"
    assert h.word(TIMER + 0x20) == 0xA5A5A5A5  # old callback not replaced before assert
    assert not any(c.address in (0xE89A, 0x108E0) for c in h.calls)
    # Assertion handler behavior is unknown; only the pre-assert mutations are proved.


def create_default(*, free=True, period=17, existing=0, gate=0, callback=0x47101):
    h, _, _ = kernel_create_harness(free=free)
    h.fixture(0x201644, bytes(4))  # synthetic: selects captured default
    h.fixture(SLOT, struct.pack("<I", existing), writable=True)
    h.fixture(0x20037D, bytes([gate]))
    h.fixture(0x200484, struct.pack("<I", 100))  # hypothesis: 100 native ticks/sec

    def divide(cpu, regs):
        assert regs[1] != 0
        q, r = divmod(regs[0], regs[1])
        cpu.return_value(q)
        cpu.uc.reg_write(cpu.a.UC_ARM_REG_R1, r)

    h.mock(0x3F97A, "UNPROVEN unsigned-division hypothesis", divide)
    return h, (SLOT, 0x12345678, 0x9ABCDEF0, period, 1, callback)


@pytest.mark.parametrize("free", [False, True])
def test_actual_create_wrapper_default_allocator_propagate_failure_or_new_handle(free):
    h, args = create_default(free=free)
    assert h.call(0x13634, *args) == int(free)
    assert h.word(SLOT) == (TIMER if free else 0)
    assert h.word(BITMAP) == int(free)
    divides = [c.registers[:2] for c in h.calls if c.address == 0x3F97A]
    assert divides == [(1000, 100), (26, 10)]  # 17ms -> 2 ticks ONLY under the mock
    if free:
        assert (h.word(TIMER + 0x18), h.word(TIMER + 0x1C), h.word(TIMER + 0x20)) == (2, args[2], args[5])
    assert not h.synthetic_literals  # create uses only captured ROM literals


@pytest.mark.parametrize("invalid", ["null_slot", "zero_period", "null_callback", "inhibited", "occupied"])
def test_create_default_rejects_invalid_inputs_without_acquiring_timer(invalid):
    h, args = create_default(period=0 if invalid == "zero_period" else 17,
        callback=0 if invalid == "null_callback" else 0x47101,
        gate=1 if invalid == "inhibited" else 0,
        existing=TIMER if invalid == "occupied" else 0)
    if invalid == "null_slot": args = (0, *args[1:])
    before = bytes(h.uc.mem_read(0x201474, 0x28))
    assert h.call(0x13634, *args) == 0
    assert h.word(BITMAP) == 0 and not h.writes
    assert bytes(h.uc.mem_read(0x201474, 0x28)) == before
    # An occupied slot is checked AFTER both conversion calls, not before them.
    assert len(h.calls) == (2 if invalid == "occupied" else 0)


@pytest.mark.parametrize("period", [0xFFFFFFF7, 0xFFFFFFFF])
def test_conversion_hypothesis_exposes_large_period_wrap_before_native_assert(period):
    h, args = create_default(period=period)
    with pytest.raises(ROMAssertion): h.call(0x13634, *args)
    assert h.word(SLOT) == 0  # native create never returned to publish the handle
    assert h.word(BITMAP) == 1  # allocation was nevertheless consumed
    # Conditional on division/config fixtures, not physical time-conversion proof.


def control_default(which, *, selector=1, result=1, wake=False,
                    empty=False, inhibited=False):
    h = ResumeHarness()
    h.defaults()
    h.fixture(ENTRIES[which][2], bytes(4))
    h.fixture(SLOT, struct.pack("<I", 0 if empty else TIMER), writable=True)
    h.fixture(0x20037D, bytes([int(inhibited)]))  # captured start literal
    if which == "restart":
        h.missing_literal_fixture(0x1424C, 0x300300)
        h.missing_literal_fixture(0x14250, 0x300340)
        h.fixture(0x300319, bytes([int(inhibited)]))
        h.fixture(0x300360, struct.pack("<I", 100))
    if wake:
        h.missing_literal_fixture(0x14248, 0x300380)
        h.fixture(0x300384, bytes(4), writable=True)
    h.mock(0x14238, "UNREAD task/ISR selector", lambda c, r: c.return_value(selector))
    h.mock(0xFCFC, "unread task tick", lambda c, r: c.return_value(123))
    h.mock(0xFD02, "unread ISR tick", lambda c, r: c.return_value(456))
    commands = []

    def divide(cpu, regs):
        assert regs[1] != 0
        q, r = divmod(regs[0], regs[1])
        cpu.return_value(q)
        cpu.uc.reg_write(cpu.a.UC_ARM_REG_R1, r)

    def command(cpu, regs):
        sp = cpu.uc.reg_read(cpu.a.UC_ARM_REG_SP)
        assert regs[0] == TIMER and cpu.word(sp) == 0  # zero queue wait
        assert regs[3] == (0 if selector else sp + 4)
        if not selector:
            assert cpu.word(regs[3]) == 0
            cpu.uc.mem_write(regs[3], struct.pack("<I", int(wake)))
        commands.append(regs[:3])
        cpu.return_value(result)

    h.mock(0x3F97A, "UNPROVEN unsigned-division hypothesis", divide)
    h.mock(0x108E0, "isolated generic command boundary", command)
    return h, commands


@pytest.mark.parametrize("which", ["start", "restart"])
@pytest.mark.parametrize("selector,wake", [(1, False), (7, False), (0, False), (0, True)])
@pytest.mark.parametrize("result", [0, 1, 2, 0xFFFFFFFF])
def test_defaults_choose_task_isr_commands_and_require_exact_acceptance(which, selector, wake, result):
    h, commands = control_default(which, selector=selector, wake=wake, result=result)
    assert h.call(ENTRIES[which][0], SLOT, 17) == int(result == 1)
    command = (1 if selector else 6) if which == "start" else (4 if selector else 9)
    value = (123 if selector else 456) if which == "start" else 2
    assert commands == [(TIMER, command, value)]
    assert h.word(SLOT) == TIMER
    assert h.writes == ([(0x300384, 4, 1 << 28)] if wake else [])
    # Wake can be requested even when queue result is failure; it is not success.
    expected_calls = ([0x14238, 0xFCFC if selector else 0xFD02, 0x108E0] if which == "start"
                      else [0x3F97A, 0x3F97A, 0x14238, 0x108E0])
    assert [c.address for c in h.calls] == expected_calls


@pytest.mark.parametrize("which", ["start", "restart"])
@pytest.mark.parametrize("bad", ["null_slot", "empty", "inhibited"])
def test_control_defaults_refuse_invalid_slot_or_gate_without_scheduling(which, bad):
    h, commands = control_default(which, empty=bad == "empty", inhibited=bad == "inhibited")
    assert h.call(ENTRIES[which][0], 0 if bad == "null_slot" else SLOT, 17) == 0
    assert not commands and not h.calls and not h.writes


@pytest.mark.parametrize("period", [0, 0xFFFFFFF7, 0xFFFFFFFF])
def test_restart_under_division_hypothesis_can_submit_zero_period_as_accepted(period):
    h, commands = control_default("restart")
    assert h.call(0x13694, SLOT, period) == 1
    assert commands == [(TIMER, 4, 0)] and h.word(SLOT) == TIMER
    # The captured daemon's zero-period assertion is tested in test_fwrom_rearm.
    # This wrapper-to-zero path is conditional on the explicit division/config mocks.


def test_restart_refuses_to_execute_through_unread_literal_without_fixture():
    h = ResumeHarness()
    h.defaults()
    h.fixture(0x20164C, bytes(4))
    h.fixture(SLOT, struct.pack("<I", TIMER))
    with pytest.raises(ROMBoundaryError, match="read outside admitted evidence/fixtures at 0x1424c"):
        h.call(0x13694, SLOT, 17)
    assert not h.calls and not h.writes and not h.synthetic_literals


@pytest.mark.parametrize("which", ENTRIES)
def test_unread_hook_state_is_not_implicitly_zero(which):
    h = ResumeHarness()
    with pytest.raises(ROMBoundaryError, match="outside admitted evidence/fixtures"):
        h.call(ENTRIES[which][0], SLOT, 17, 1, 17, 1, 0x47101)
    assert not h.calls and not h.writes
