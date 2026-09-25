"""Checked C cancellation through captured ROM; synthetic RTOS/RAM only.

These tests do not supply the required production serialization or install any
hook. Kernel queue, divide, tick/list/switch boundaries remain explicit mocks.
"""
import struct

import pytest

from whip.fwrom_execution import ROMFenceHarness
from whip.fwthumb import ThumbProofError
from whip.fwhealth_adapter import SCHEDULED_JOBS
from tests.test_fwstock_link import linked, STOCK, DESCRIPTOR  # noqa: F401
from tests.test_fwrom_execution import CAPTURE
from whip.fwcontinuity import BIAS
from whip.fwstock_binding import StockBindingHarness

# Independent pinned-stock oracle, not parsed from the C table under test.
# Remaining seven slots are witnessed by exact stock paths below and existing
# stock producer tests. No claim that this is the entire producer inventory.
REVIEWED_SLOTS = tuple(j.timer for j in SCHEDULED_JOBS) + (
    0x209D40, 0x209D44, 0x20C018, 0x20BC54, 0x209CC0, 0x209D14, 0x209D10,
)


class HealthTimerHarness(ROMFenceHarness):
    POOL, MASK = 0x204000, 0x207000
    QUEUE = 0x207040
    COUNT = 65

    def __init__(self, elf):
        self.ram_reads, self.timer_stores, self.command_calls, self.mock_calls = [], [], [], []
        super().__init__(elf, STOCK, DESCRIPTOR, CAPTURE)
        self.uc.mem_map(0x200000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_map(0x202000, 0x16000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.fixture(0x20037B, bytes([self.COUNT]))
        state = bytearray(32)
        struct.pack_into("<HHI", state, 0, 70, 5, self.QUEUE)
        struct.pack_into("<III", state, 20, self.POOL, self.MASK, 99)
        self.fixture(0x201474, state)
        timers = bytearray(48 * self.COUNT)
        for index in range(self.COUNT):
            struct.pack_into("<I", timers, index * 48 + 0x24, index)
            timers[index * 48 + 0x28] = 0xA7
        self.fixture(self.POOL, timers)
        self.fixture(self.MASK, b"\xff" * 12)
        for index, slot in enumerate(REVIEWED_SLOTS):
            self.fixture(slot, struct.pack("<I", self.POOL + 48 * index))
        self.executable.extend(((0x108E0, 0x1099E), (0x109BA, 0x109D8),
                                (0x10A32, 0x10A3E), (0x10E2A, 0x10E4E)))

    def fixture(self, address, data):
        self.uc.mem_write(address, bytes(data))
        self.ram_reads.append((address, address + len(data)))

    def put_word(self, address, value):
        self.uc.mem_write(address, struct.pack("<I", value))

    def _read(self, uc, access, address, size, value, opaque):
        if any(lo <= address and address + size <= hi for lo, hi in self.ram_reads): return
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        pc = uc.reg_read(self.a.UC_ARM_REG_PC)
        allowed = (pc == 0x10E4A and address == 0x201490 and size == 4) or (
            pc == 0x10A3A and size == 1 and self.POOL <= address < self.POOL + 48 * self.COUNT
            and (address - self.POOL) % 48 == 0x28)
        if allowed:
            self.timer_stores.append((address, size, value & ((1 << (8 * size)) - 1)))
            return
        super()._write(uc, access, address, size, value, opaque)

    def _code(self, uc, pc, size, opaque):
        a = self.a
        regs = tuple(uc.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                                             a.UC_ARM_REG_R2, a.UC_ARM_REG_R3))
        if pc == 0x108E0:
            fifth = struct.unpack("<I", uc.mem_read(uc.reg_read(a.UC_ARM_REG_SP), 4))[0]
            assert regs[1:] == (3, 0, 0) and fifth == 0
            assert uc.reg_read(a.UC_ARM_REG_PRIMASK) == 0
            self.command_calls.append(regs)
        if pc in (0x3F97A, 0x10100, 0xFCFC, 0x40A94, 0xE8E8):
            self.mock_calls.append((pc, regs))
            if pc == 0x3F97A:
                q, rem = divmod(regs[0], regs[1])
                self._kernel_return(q)
                uc.reg_write(a.UC_ARM_REG_R1, rem)
            elif pc == 0x10100: self._kernel_return(2)
            elif pc == 0xFCFC: self._kernel_return(100)
            elif pc == 0x40A94:
                assert regs[3] == 3
                table = bytes(uc.mem_read(0x109D8, 12))
                target = (0x109D9 + 2 * table[4]) & ~1
                assert target == 0x10A32
                uc.reg_write(a.UC_ARM_REG_PC, target | 1)
            else: self._kernel_return(0)
            return
        if pc == 0xEAB2:
            handle, message, wait, position = regs
            if not self.STACK - 0x1000 <= message <= self.STACK - 16:
                raise ThumbProofError("message outside fixture stack")
            packet = bytes(uc.mem_read(message, 16))
            command, value, timer, _ = struct.unpack("<4I", packet)
            if command == 3:
                assert (handle, wait, position) == (self.QUEUE, 0, 0) and value == 0
                assert uc.reg_read(a.UC_ARM_REG_PRIMASK) == 0
                self.boundaries.append((pc, regs))
                if self.send_result == 1: self.messages.append(packet)
                self._kernel_return(self.send_result)
                return
        super()._code(uc, pc, size, opaque)


@pytest.mark.parametrize("job", range(5))
@pytest.mark.parametrize("result", [0, 1, 2, 0xFFFFFFFF])
def test_compiled_stop_uses_reviewed_slot_and_actual_rom_without_clearing_health_state(linked, job, result):
    h = HealthTimerHarness(linked)
    before = bytes(h.uc.mem_read(0x200000, 0x18000))
    h.send_result = result
    assert h.call("wht_stop_scheduled", job) == (1 if result == 1 else 3)
    assert h.command_calls == [(h.POOL + 48 * job, 3, 0, 0)]
    assert len(h.messages) == (1 if result == 1 else 0)
    assert not h.timer_stores
    assert bytes(h.uc.mem_read(0x200000, 0x18000)) == before
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


def test_five_queued_stops_precede_compiled_barrier_ack_under_synthetic_fifo(linked):
    h = HealthTimerHarness(linked)
    for job in range(5): assert h.call("wht_stop_scheduled", job) == 1
    assert h.invoke("wf_request", 77)
    assert not h.invoke("wf_complete", 77)
    assert len(h.messages) == 6
    h.dispatch(limit=5)
    assert [address for address, size, _ in h.timer_stores if size == 1] == [
        h.POOL + 48 * job + 0x28 for job in range(5)]
    assert not h.invoke("wf_complete", 77) and not h.callbacks
    h.dispatch()
    assert h.invoke("wf_complete", 77)
    for job in range(5):
        assert bytes(h.uc.mem_read(h.POOL + 48 * job + 0x28, 1)) == b"\xa6"
        assert struct.unpack("<I", h.uc.mem_read(SCHEDULED_JOBS[job].timer, 4))[0] == h.POOL + 48 * job
    # No physical STOP or wh_cancelled/fenced/stopped receipt follows from this.


@pytest.mark.parametrize("job", range(5))
def test_empty_slot_does_not_call_rom_or_claim_callback_drain(linked, job):
    h = HealthTimerHarness(linked)
    h.put_word(SCHEDULED_JOBS[job].timer, 0)
    assert h.call("wht_stop_scheduled", job) == 0
    assert not h.command_calls and not h.messages and not h.timer_stores


@pytest.mark.parametrize("case", ["bad_job", "wrapped_job", "isr", "masked", "queue_zero", "queue_outside", "queue_unaligned", "count_zero",
    "pool_zero", "pool_unaligned", "pool_wrap", "pool_truncated", "mask_zero", "mask_unaligned",
    "mask_wrap", "mask_truncated", "below_pool", "past_pool", "unaligned_handle", "wrong_number", "free_entry"])
def test_invalid_or_unallocated_timer_is_refused_before_faulting_rom_api(linked, case):
    h = HealthTimerHarness(linked)
    job = 0
    if case == "bad_job": job = 5
    elif case == "wrapped_job": job = 0xFFFFFFFF
    elif case == "isr": h.uc.reg_write(h.a.UC_ARM_REG_IPSR, 3)
    elif case == "masked": h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, 1)
    elif case == "count_zero": h.uc.mem_write(0x20037B, b"\x00")
    else:
        address, value = {
            "queue_zero": (h.QUEUE_SLOT, 0), "queue_outside": (h.QUEUE_SLOT, 0x40015000),
            "queue_unaligned": (h.QUEUE_SLOT, h.QUEUE + 1), "pool_zero": (0x201488, 0),
            "pool_unaligned": (0x201488, h.POOL + 1), "pool_wrap": (0x201488, 0xFFFFFFF0),
            "pool_truncated": (0x201488, 0x217FF0), "mask_zero": (0x20148C, 0),
            "mask_unaligned": (0x20148C, h.MASK + 1), "mask_wrap": (0x20148C, 0xFFFFFFFC),
            "mask_truncated": (0x20148C, 0x217FFC),
            "below_pool": (SCHEDULED_JOBS[0].timer, h.POOL - 4),
            "past_pool": (SCHEDULED_JOBS[0].timer, h.POOL + h.COUNT * 48),
            "unaligned_handle": (SCHEDULED_JOBS[0].timer, h.POOL + 4),
            "wrong_number": (h.POOL + 0x24, 1), "free_entry": (h.MASK, 0xFFFFFFFE)
        }[case]
        h.put_word(address, value)
    assert h.call("wht_stop_scheduled", job) == 2
    assert not h.command_calls and not h.messages and not h.timer_stores
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == (1 if case == "masked" else 0)


@pytest.mark.parametrize("index", [0, 1, 31, 32, 63, 64])
@pytest.mark.parametrize("allocated", [False, True])
def test_pool_index_and_bitmap_word_boundaries_are_checked(linked, index, allocated):
    h = HealthTimerHarness(linked)
    h.put_word(SCHEDULED_JOBS[0].timer, h.POOL + index * 48)
    if not allocated: h.put_word(h.MASK + (index // 32) * 4, 0xFFFFFFFF ^ (1 << (index % 32)))
    assert h.call("wht_stop_scheduled", 0) == (1 if allocated else 2)
    assert len(h.command_calls) == int(allocated)


def test_no_general_health_ram_write_permission_is_added(linked):
    h = HealthTimerHarness(linked)
    with pytest.raises(ThumbProofError):
        h._write(h.uc, h.u.UC_MEM_WRITE, SCHEDULED_JOBS[0].timer, 4, 0, None)


@pytest.mark.parametrize("job", range(len(REVIEWED_SLOTS)))
@pytest.mark.parametrize("result", [0, 1, 2, 0xFFFFFFFF])
def test_all_reviewed_timers_use_exact_slots_and_propagate_each_queue_result(linked, job, result):
    h = HealthTimerHarness(linked)
    before = bytes(h.uc.mem_read(0x200000, 0x18000))
    h.send_result = result
    assert h.call("wht_stop_reviewed", job) == (1 if result == 1 else 3)
    assert h.command_calls == [(h.POOL + 48 * job, 3, 0, 0)]
    assert len(h.messages) == int(result == 1)
    assert bytes(h.uc.mem_read(0x200000, 0x18000)) == before
    assert not h.timer_stores and h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


@pytest.mark.parametrize("job", range(len(REVIEWED_SLOTS)))
def test_each_reviewed_empty_or_free_timer_is_not_sent_to_rom(linked, job):
    h = HealthTimerHarness(linked)
    h.put_word(REVIEWED_SLOTS[job], 0)
    assert h.call("wht_stop_reviewed", job) == 0
    h.put_word(REVIEWED_SLOTS[job], h.POOL + 48 * job)
    h.put_word(h.MASK, 0xFFFFFFFF ^ (1 << job))
    assert h.call("wht_stop_reviewed", job) == 2
    assert not h.command_calls and not h.messages and not h.timer_stores


@pytest.mark.parametrize("entry,job", [
    ("wht_stop_scheduled", j) for j in range(5, 13)
] + [("wht_stop_reviewed", 12), ("wht_stop_reviewed", 0xFFFFFFFF)])
def test_entrypoints_keep_their_distinct_reviewed_bounds(linked, entry, job):
    h = HealthTimerHarness(linked)
    before = bytes(h.uc.mem_read(0x200000, 0x18000))
    assert h.call(entry, job) == 2
    assert not h.command_calls and not h.messages and not h.timer_stores
    assert bytes(h.uc.mem_read(0x200000, 0x18000)) == before


def test_all_reviewed_stop_messages_precede_fence_without_changing_other_timers(linked):
    h = HealthTimerHarness(linked)
    count = len(REVIEWED_SLOTS)
    before = bytes(h.uc.mem_read(h.POOL + 48 * count, 48 * (h.COUNT - count)))
    for job in range(count):
        assert h.call("wht_stop_reviewed", job) == 1
    assert h.invoke("wf_request", 88)
    for job in range(count):
        h.dispatch(limit=1)
        assert not h.invoke("wf_complete", 88)
        assert not h.callbacks
        assert bytes(h.uc.mem_read(h.POOL + 48 * job + 0x28, 1)) == b"\xa6"
        assert struct.unpack("<I", h.uc.mem_read(REVIEWED_SLOTS[job], 4))[0] == h.POOL + 48 * job
    h.dispatch()
    assert h.invoke("wf_complete", 88)
    assert bytes(h.uc.mem_read(h.POOL + 48 * count, len(before))) == before
    assert [address for address, size, _ in h.timer_stores if size == 1] == [
        h.POOL + 48 * job + 0x28 for job in range(count)]


@pytest.mark.parametrize("job", range(len(REVIEWED_SLOTS)))
def test_failed_cancel_can_leave_one_timer_active_despite_later_fence(linked, job):
    # Negative witness: a timer-queue fence cannot repair an earlier failed
    # submission and must never be used as a blanket wh_cancelled receipt.
    h = HealthTimerHarness(linked)
    for index in range(len(REVIEWED_SLOTS)):
        h.send_result = 0 if index == job else 1
        assert h.call("wht_stop_reviewed", index) == (3 if index == job else 1)
    h.send_result = 1
    assert h.invoke("wf_request", 99)
    h.dispatch()
    assert h.invoke("wf_complete", 99)
    assert bytes(h.uc.mem_read(h.POOL + 48 * job + 0x28, 1)) == b"\xa7"


class RawTimerWitness(StockBindingHarness):
    """Only raw 04/05 control, not raw acquisitions or other A1 modes.

    Stock timer wrappers execute to existing explicit ROM mocks. The immediate
    raw callback is intercepted, never executed or presented as sensor proof.
    No fixture grants execution to the broader raw/debug code region.
    """
    RANGES = ((0x2104, 0x213A), (0x2220, 0x224E), (0x2298, 0x22AA),
              (0x2340, 0x2348), (0x202A, 0x202E))

    def __init__(self):
        self.immediate_reports = []
        super().__init__(STOCK)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if offset == 0x2DAE:
            self.mock_calls.append(offset)
            self._return(0)  # explicit not-busy fixture
            return
        if offset == 0x1E4A:
            self.immediate_reports.append(uc.reg_read(self.registers[0]))
            self._return()
            return
        if any(lo <= offset and offset + size <= hi for lo, hi in self.RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)


def test_reviewed_raw_slot_is_executed_stock_start_stop_argument_not_guessed_padding():
    h = RawTimerWitness()
    pointer = 0x220C00
    h.uc.mem_write(pointer, b"\xa1\x04" + bytes(14))
    h.call(0x2104, pointer)
    slot = REVIEWED_SLOTS[9]
    assert h.timer_calls == [("create", slot, 1, 1000, 1, BIAS + 0x1E4B), ("start", slot)]
    assert h.immediate_reports == [0]
    h.uc.mem_write(pointer + 1, b"\x05")
    h.call(0x2104, pointer)
    assert h.timer_calls[-2:] == [("stop", slot), ("delete", slot)]
    assert not h.i2c_calls  # raw acquisition remained an explicit boundary mock


def test_reviewed_brightness_slot_and_callback_match_executed_stock_entry():
    h = StockBindingHarness(STOCK)
    h.call(0x3B1A, 4)
    slot = REVIEWED_SLOTS[10]
    assert h.timer_calls == [("create", slot, 1, 100, 1, BIAS + 0x3AC5), ("start", slot)]
    assert not h.indicator_requests  # deferred callback has not executed
