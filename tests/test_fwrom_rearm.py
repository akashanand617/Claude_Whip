"""Captured timer-kernel restart behavior; native tick fixtures, not ms or RTOS.

This does NOT implement a resume API. Missing vendor wrapper/hook semantics,
job provenance and real serialization must be resolved before attaching one.
"""
import struct

import pytest

from tests.test_fwrom_execution import CAPTURE, command_harness
from whip.fwrom_execution import ROMHarness, ROMAssertion


@pytest.mark.parametrize("command", [1, 2, 4])
@pytest.mark.parametrize("result", [0, 1, 2, 0xFFFFFFFF])
def test_generic_rearm_only_queues_and_preserves_raw_failure_result(command, result):
    h, messages = command_harness(result=result)
    before = bytes(h.uc.mem_read(0x300800, 48 * 3))
    assert h.call(0x108E0, 0x300830, command, 77, 0, 0) == result
    assert len(messages) == 1
    regs, message = messages[0]
    assert message == (command, 77, 0x300830)
    assert regs[0] == 0x300B00 and regs[2:] == (0, 0)
    assert bytes(h.uc.mem_read(0x300800, 48 * 3)) == before and not h.writes


@pytest.mark.parametrize("command", [1, 2, 4])
def test_native_rearm_command_does_not_check_live_allocation_bit(command):
    h, messages = command_harness(used=0)
    assert h.call(0x108E0, 0x300830, command, 77, 0, 0) == 1
    assert len(messages) == 1 and not h.writes
    # The caller must prove lifetime/identity; native API acceptance is not proof.


TIMER, QUEUE = 0x300800, 0x300B00
ACTIVE_LIST, OVERFLOW_LIST = 0x300C00, 0x300C40
CALLBACK = 0x48000  # Explicit synthetic boundary; not a captured callback body.


def daemon(command, value, *, now=100, linked=False, flags=0xA6):
    h = ROMHarness(CAPTURE)
    for low, high in ((0x108AC, 0x108E0), (0x1099E, 0x109D8),
                      (0x109E4, 0x10A32), (0x10A3E, 0x10A6A),
                      (0x10A82, 0x10A96), (0x10E2A, 0x10E4E)):
        h.select(low, high)
    state = bytearray(40)
    struct.pack_into("<I", state, 4, QUEUE)
    struct.pack_into("<III", state, 28, now, ACTIVE_LIST, OVERFLOW_LIST)
    h.fixture(0x201474, state)
    h.fixture(0x201490, struct.pack("<I", now), writable=True)
    timer = bytearray(48)
    struct.pack_into("<IIII", timer, 0x14, ACTIVE_LIST if linked else 0,
                     17, 0x1234ABCD, CALLBACK | 1)
    timer[0x28] = flags
    h.fixture(TIMER, timer, writable=True)
    pending = [struct.pack("<4I", command, value, TIMER, 0)]
    observations = []

    def receive(cpu, regs):
        assert regs[0] == QUEUE and regs[2] == 0
        if pending:
            cpu.uc.mem_write(regs[1], pending.pop(0))
            cpu.return_value(1)
        else:
            cpu.return_value(0)

    def switch(cpu, regs):
        assert regs[3] == command
        table = bytes(cpu.uc.mem_read(0x109D8, 12))
        assert table == bytes.fromhex("0a0606062d334906062d3355")
        target = (0x109D9 + 2 * table[command + 1]) & ~1
        assert target == (0x10A3E if command == 4 else 0x109E4)
        cpu.uc.reg_write(cpu.a.UC_ARM_REG_PC, target | 1)

    def insert(cpu, regs):
        assert regs[0] in (ACTIVE_LIST, OVERFLOW_LIST) and regs[1] == TIMER + 4
        observations.append(("insert", regs[0], cpu.word(TIMER + 4)))
        cpu.return_value()

    def remove(cpu, regs):
        assert regs[0] == TIMER + 4
        observations.append(("remove", regs[0]))
        cpu.return_value()

    def callback(cpu, regs):
        assert regs[0] == TIMER
        observations.append(("callback", cpu.word(TIMER + 0x1C), cpu.word(TIMER + 0x20)))
        cpu.return_value()

    h.mock(0xEFAE, "unread queue receive", receive)
    h.mock(0xFCFC, "unread tick count", lambda cpu, regs: cpu.return_value(now))
    h.mock(0x40A94, "unread compiler switch helper", switch)
    h.mock(0xE8B8, "unread sorted-list insertion", insert)
    h.mock(0xE8E8, "unread list removal", remove)
    h.mock(CALLBACK, "synthetic callback observer", callback)
    return h, observations, timer


@pytest.mark.parametrize("period,now", [(1, 100), (25, 100), (1000, 100),
                                        (25, 0xFFFFFFF0), (0xFFFFFFFF, 100)])
@pytest.mark.parametrize("linked", [False, True])
def test_change_period_rearms_from_daemon_now_without_changing_callback_or_job_id(period, now, linked):
    h, seen, original = daemon(4, period, now=now, linked=linked)
    h.call(0x1099E)
    expiry = (now + period) & 0xFFFFFFFF
    target_list = OVERFLOW_LIST if expiry <= now else ACTIVE_LIST
    expected = ([("remove", TIMER + 4)] if linked else []) + [("insert", target_list, expiry)]
    assert seen == expected
    updated = bytearray(original)
    struct.pack_into("<I", updated, 4, expiry)
    struct.pack_into("<I", updated, 0x10, TIMER)
    struct.pack_into("<I", updated, 0x18, period)
    updated[0x28] |= 1
    assert bytes(h.uc.mem_read(TIMER, 48)) == bytes(updated)
    assert h.word(TIMER + 0x1C) == 0x1234ABCD and h.word(TIMER + 0x20) == CALLBACK | 1
    # Linked-list bodies were not executed; no list integrity or tick-rate claim.


def test_zero_change_period_asserts_after_partial_timer_mutation():
    h, seen, _ = daemon(4, 0, linked=True)
    with pytest.raises(ROMAssertion):
        h.call(0x1099E)
    assert seen == [("remove", TIMER + 4)]
    assert bytes(h.uc.mem_read(TIMER + 0x28, 1)) == b"\xa7"
    assert h.word(TIMER + 0x18) == 0
    assert h.word(TIMER + 0x1C) == 0x1234ABCD
    # This native kernel edge is not evidence that vendor wrappers allow zero.


@pytest.mark.parametrize("command", [1, 2])
@pytest.mark.parametrize("issued", [50, 100])
def test_start_reset_can_invoke_old_callback_immediately_if_command_time_is_stale(command, issued):
    h, seen, original = daemon(command, issued, flags=0xA2)  # single-shot fixture
    h.call(0x1099E)
    if issued == 50:
        assert seen == [("callback", 0x1234ABCD, CALLBACK | 1)]
    else:
        assert seen == [("insert", ACTIVE_LIST, 117)]
    assert h.word(TIMER + 0x18) == 17  # old period, not a fresh-job configuration
    assert h.word(TIMER + 0x1C) == 0x1234ABCD and h.word(TIMER + 0x20) == CALLBACK | 1
    assert original[0x28] == 0xA2
    # An enqueue/daemon barrier can occur AFTER this callback. It cannot turn
    # an old callback into a new acquisition or establish Health provenance.
