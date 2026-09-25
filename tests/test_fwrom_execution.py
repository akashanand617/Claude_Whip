"""Captured ROM instructions, explicit unread-kernel/peripheral boundaries."""
from pathlib import Path
import struct

import pytest

from whip.fwrom_execution import captured_windows, ROMHarness, ROMBoundaryError, ROMAssertion

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = (ROOT / "firmware/research/2026-09-23/rom-integration/rom-integration.json").read_bytes()


def test_capture_and_unpopulated_boundaries_are_not_zero_filled_evidence():
    with pytest.raises(ValueError): captured_windows(CAPTURE + b"\n")
    h = ROMHarness(CAPTURE)
    with pytest.raises(ValueError): h.select(0xEAB2, 0xEAB4)
    h.select(0x10D5E, 0x10D98)
    with pytest.raises(ROMBoundaryError, match="read outside"):
        h.call(0x10D5E, 0x300101, 0x300200, 1, 0)  # Queue word deliberately absent.


@pytest.mark.parametrize("cache,value", [(0, 0x82F70000), (4096, 0x2F2D0002), (8192, 0xA2AA0003),
                                       (1, 0x82F70000), (0xFFFFFFFF, 0x82F70000)])
def test_captured_ram_layout_writes_configuration_only(cache, value):
    h = ROMHarness(CAPTURE)
    h.select(0x4A78, 0x4A9E)
    h.fixture(0x200380, b"\xA5" * 16, writable=True)
    h.fixture(0x2003CC, b"\xA5" * 4, writable=True)
    h.call(0x4A78, 0x7000, 0x7400, cache)
    assert h.writes == [(0x200388, 4, 0x7400), (0x200384, 4, 0x7000), (0x2003CC, 4, value)]
    assert h.word(0x200380) == h.word(0x20038C) == 0xA5A5A5A5
    assert not h.calls  # No heap setup or bounds check in this selected function.


@pytest.mark.parametrize("image_id", [0, 0x278C, *range(0x278D, 0x279B), 0x279B, 0xFFFFFFFF])
def test_captured_boot_error_helper_only_sets_a_bounded_status_byte(image_id):
    h = ROMHarness(CAPTURE)
    h.select(0x4C7A, 0x4C90)
    h.fixture(0x200050, b"\xA5" * 32, writable=True)
    h.call(0x4C7A, image_id, 0x116)
    assert h.writes == ([(0x20005D + image_id - 0x278D, 1, 0x16)] if 0x278D <= image_id < 0x279B else [])
    expected = bytearray(b"\xA5" * 32)
    if 0x278D <= image_id < 0x279B: expected[13 + image_id - 0x278D] = 0x16
    assert bytes(h.uc.mem_read(0x200050, 32)) == bytes(expected)
    assert not h.calls  # No reset/copy/recovery operation in THIS helper.


@pytest.mark.parametrize("result", [0, 1, 2, 0xFFFFFFFF])
@pytest.mark.parametrize("wait", [0, 7, 0xFFFFFFFF])
def test_actual_timer_pend_wrapper_marshals_message_and_propagates_queue_return(result, wait):
    h = ROMHarness(CAPTURE)
    h.select(0x10D5E, 0x10D98)
    h.fixture(0x201478, struct.pack("<I", 0x300800))
    messages = []

    def queue(cpu, regs):
        handle, message, ticks, position = regs
        assert (handle, ticks, position) == (0x300800, wait, 0)
        assert cpu.STACK - 64 <= message <= cpu.STACK - 16
        messages.append(struct.unpack("<4I", cpu.uc.mem_read(message, 16)))
        cpu.return_value(result)

    h.mock(0xEAB2, "unread xQueueGenericSend", queue)
    assert h.call(0x10D5E, 0x300101, 0x300200, 0x12345678, wait) == result
    assert messages == [(0xFFFFFFFF, 0x300101, 0x300200, 0x12345678)]
    assert len(h.calls) == 1 and not h.writes


def test_timer_pend_null_queue_asserts_instead_of_returning_failure():
    h = ROMHarness(CAPTURE)
    h.select(0x10D5E, 0x10D98)
    h.fixture(0x201478, bytes(4))
    with pytest.raises(ROMAssertion): h.call(0x10D5E, 0x300101, 0x300200, 1, 0)


@pytest.mark.parametrize("image,header,expected", [(0, None, 0), (0x2793, b"\x05" + bytes(51), 0x11),
    (0x2793, b"\x0c\x00\x80" + bytes(49), 0x13),
    (0x2793, b"\x0c\x00\x00\x00\x92\x27" + bytes(46), 0x14)])
def test_header_early_rejections_execute_without_inventing_unread_literal_pool(image, header, expected):
    h = ROMHarness(CAPTURE)
    h.select(0x8A82, 0x8AE2)
    h.select(0x4C7A, 0x4C90)
    h.fixture(0x200050, b"\xA5" * 32, writable=True)
    if header is not None: h.fixture(0x300000, header)
    assert h.call(0x8A82, 0x300000 if header else 0, image) == 0
    assert h.writes == ([(0x200063, 1, expected)] if header else [])
    assert not h.calls


def test_valid_looking_header_stops_at_uncaptured_shared_literal_not_a_fabricated_success():
    h = ROMHarness(CAPTURE)
    h.select(0x8A82, 0x8AE2)
    h.fixture(0x300000, b"\x0c\x00\x00\x00\x93\x27" + bytes(46))
    with pytest.raises(ROMBoundaryError, match="0x8cbc"):
        h.call(0x8A82, 0x300000, 0x2793)


def command_harness(*, queue=0x300B00, used=7, scheduler=2, result=1):
    """Synthetic three-object timer pool; unread kernel/divide/log callees named."""
    h = ROMHarness(CAPTURE)
    h.select(0x108E0, 0x1099E)
    state = bytearray(32)
    struct.pack_into("<HHI", state, 0, 4, 1, queue)
    struct.pack_into("<II", state, 20, 0x300800, 0x300C00)
    h.fixture(0x201474, state)
    h.fixture(0x20037B, b"\x03")
    pool = bytearray(3 * 48)
    for index in range(3): struct.pack_into("<I", pool, index * 48 + 0x24, index)
    h.fixture(0x300800, pool)
    h.fixture(0x300C00, struct.pack("<I", used))
    messages = []

    def divide(cpu, regs):
        quotient, remainder = divmod(regs[0], regs[1])
        cpu.return_value(quotient)
        cpu.uc.reg_write(cpu.a.UC_ARM_REG_R1, remainder)

    def send(cpu, regs):
        messages.append((regs, struct.unpack("<3I", cpu.uc.mem_read(regs[1], 12))))
        cpu.return_value(result)

    h.mock(0x3F97A, "unread unsigned divide", divide)
    h.mock(0x5AA8, "unread diagnostic log", lambda cpu, regs: cpu.return_value())
    h.mock(0x10100, "unread scheduler-state query", lambda cpu, regs: cpu.return_value(scheduler))
    h.mock(0xEAB2, "unread task queue send", send)
    h.mock(0xEE5E, "unread ISR queue send", send)
    return h, messages


@pytest.mark.parametrize("command", [3, 5, 8])
@pytest.mark.parametrize("result", [0, 1, 0xFFFFFFFF])
@pytest.mark.parametrize("scheduler", [0, 2])
def test_generic_timer_stop_delete_only_enqueue_and_propagate_raw_result(command, result, scheduler):
    h, messages = command_harness(scheduler=scheduler, result=result)
    assert h.call(0x108E0, 0x300830, command, 0x1234, 0x300D00, 7) == result
    assert len(messages) == 1
    regs, message = messages[0]
    assert message == (command, 0x1234, 0x300830)
    assert regs[0] == 0x300B00 and regs[3] == 0
    assert regs[2] == (0x300D00 if command >= 6 else (7 if scheduler == 2 else 0))
    assert h.calls[-1].address == (0xEE5E if command >= 6 else 0xEAB2)
    assert not h.writes  # No timer inactive bit or callback fence is committed.


@pytest.mark.parametrize("handle", [0, 0x3007FF, 0x300801, 0x30082F, 0x300890])
def test_invalid_timer_handle_takes_deliberate_null_write_path(handle):
    h, messages = command_harness()
    with pytest.raises(ROMBoundaryError, match="protected ROM execution at 0x10956.*WRITE_PROT"):
        h.call(0x108E0, handle, 3, 0, 0, 0)
    assert h.uc.reg_read(h.a.UC_ARM_REG_R0) == 0  # Captured STR r0,[r0].
    assert h.calls[-1].address == 0x5AA8 and not messages


@pytest.mark.parametrize("command", [3, 5])
def test_null_timer_queue_returns_failure_for_generic_command_not_assertion(command):
    h, messages = command_harness(queue=0)
    assert h.call(0x108E0, 0x300830, command, 0, 0, 0) == 0
    assert not messages and not h.writes


def test_delete_of_unallocated_pool_entry_faults_but_stop_does_not_check_allocation_bit():
    h, messages = command_harness(used=0)
    with pytest.raises(ROMBoundaryError, match="protected ROM execution at 0x10956.*WRITE_PROT"):
        h.call(0x108E0, 0x300830, 5, 0, 0, 0)
    assert h.uc.reg_read(h.a.UC_ARM_REG_R0) == 0
    assert not messages
    h, messages = command_harness(used=0)
    assert h.call(0x108E0, 0x300830, 3, 0, 0, 0) == 1
    assert len(messages) == 1  # Acceptance is NOT proof of a live/owned timer.


@pytest.mark.parametrize("command", [3, 5, 8])
@pytest.mark.parametrize("linked", [False, True])
def test_captured_daemon_stop_and_static_delete_clear_active_bit_only(command, linked):
    h = ROMHarness(CAPTURE)
    for start, end in ((0x1099E, 0x109D8), (0x10A32, 0x10A3E),
                       (0x10A6A, 0x10A96), (0x10E2A, 0x10E4E)):
        h.select(start, end)
    h.fixture(0x201478, struct.pack("<I", 0x300B00))
    h.fixture(0x201490, struct.pack("<I", 99), writable=True)
    timer = bytearray(48)
    struct.pack_into("<I", timer, 0x14, 0x300C00 if linked else 0)
    timer[0x28] = 0xA7  # Active + static-storage bits; other bits must survive.
    h.fixture(0x300800, timer, writable=True)
    pending = [struct.pack("<4I", command, 0, 0x300800, 0)]

    def receive(cpu, regs):
        assert regs[:1] == (0x300B00,) and regs[2] == 0
        if pending:
            cpu.uc.mem_write(regs[1], pending.pop())
            cpu.return_value(1)
        else: cpu.return_value(0)

    def switch(cpu, regs):
        # Compiler helper itself is unread. This substitute reads the actual
        # captured table and supports ONLY these reviewed STOP/static-DELETE cases.
        assert regs[3] == command
        table = bytes(cpu.uc.mem_read(0x109D8, 12))
        assert table == bytes.fromhex("0a0606062d334906062d3355")
        target = (0x109D9 + 2 * table[command + 1]) & ~1
        assert target == (0x10A6A if command == 5 else 0x10A32)
        cpu.uc.reg_write(cpu.a.UC_ARM_REG_PC, target | 1)

    h.mock(0xEFAE, "unread queue receive", receive)
    h.mock(0xE8E8, "unread list removal", lambda cpu, regs: cpu.return_value())
    h.mock(0xFCFC, "unread tick count", lambda cpu, regs: cpu.return_value(100))
    h.mock(0x40A94, "unread compiler switch helper", switch)
    h.call(0x1099E)
    assert h.writes == [(0x201490, 4, 100), (0x300828, 1, 0xA6)]
    expected = bytearray(timer)
    expected[0x28] = 0xA6
    assert bytes(h.uc.mem_read(0x300800, 48)) == bytes(expected)
    assert [c.registers[0] for c in h.calls if c.address == 0xE8E8] == ([0x300804] if linked else [])
    # Static DELETE here does not free pool storage; list/queue kernel are mocks.
