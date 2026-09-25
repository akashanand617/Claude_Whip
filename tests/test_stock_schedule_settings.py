"""Compiled STOCK-only snapshot + unchanged stock scheduling, off-ring.

No physical time, RTOS, STOP/resume, persistence, steps or sleep assertion.
"""
import struct

import pytest

from tests.test_fwstock_link import linked, STOCK, DESCRIPTOR  # noqa: F401
from whip.fwstock_link import StockAppendThumb
from whip.fwthumb import ThumbProofError
from whip.fwhealth_schedule import (
    StockScheduleHarness, GETTERS, SETTERS, ENABLES,
    PENDING_SECONDS, SCHEDULER_SECONDS,
)
from whip.fwhealth_adapter import SCHEDULED_JOBS


class SettingsThumb(StockAppendThumb):
    # Independent fixture addresses, not extracted from C or imported mapping.
    FIELDS = (0x208AAC, 0x208AAD, 0x208C44, 0x208C46)

    def __init__(self, elf, values):
        self.settings_reads = []
        super().__init__(elf, STOCK, DESCRIPTOR)
        self.uc.mem_map(0x208000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_write(0x208000, b"\xa5" * 0x1000)
        for address, value in zip(self.FIELDS, values, strict=True):
            self.uc.mem_write(address, bytes([value]))

    def _read(self, uc, access, address, size, value, opaque):
        if address in self.FIELDS and size == 1:
            if uc.reg_read(self.a.UC_ARM_REG_PRIMASK) != 1:
                raise ThumbProofError("settings load outside bounded interrupt exclusion")
            self.settings_reads.append(address)
            return
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        if 0x208000 <= address < 0x209000:
            raise ThumbProofError("read primitive attempted a stock RAM write")
        super()._write(uc, access, address, size, value, opaque)


@pytest.mark.parametrize("values", [
    (5, 0x1F, 3, 1), (60, 0, 3, 1), (1, 0xE0, 0, 0),
    (0, 0, 0, 0), (255, 255, 255, 255), (17, 0xA5, 2, 2),
])
@pytest.mark.parametrize("primask", [0, 1])
def test_actual_compiled_snapshot_reads_only_four_stock_bytes_and_restores_mask(linked, values, primask):
    h = SettingsThumb(linked, values)
    before = bytes(h.uc.mem_read(0x208000, 0x1000))
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, primask)
    assert h.call("wss_read_controls") == int.from_bytes(bytes(values), "little")
    assert h.settings_reads == list(h.FIELDS)
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == primask
    assert bytes(h.uc.mem_read(0x208000, 0x1000)) == before
    assert h.stack_low >= h.STACK - 16  # local frame, NOT ring task headroom


def test_all_256_enable_bytes_match_real_stock_getters_and_compiled_snapshot(linked):
    native = SettingsThumb(linked, (5, 0, 3, 1))
    stock = StockScheduleHarness(STOCK)
    for enables in range(256):
        stock.set_controls(enables=enables)
        native.uc.mem_write(0x208AAD, bytes([enables]))
        before = bytes(stock.uc.mem_read(0x2084B0, 0x6284))
        raw = native.call("wss_read_controls")
        assert (raw >> 8) & 255 == enables  # preserve unknown upper bits too
        assert [stock.call(getter) for getter in GETTERS] == [
            (enables >> bit) & 1 for bit in range(5)]
        assert bytes(stock.uc.mem_read(0x2084B0, 0x6284)) == before
    assert set(GETTERS).issubset(stock.executed)


@pytest.mark.parametrize("index", range(5))
def test_actual_stock_setter_changes_only_its_bit_in_the_stock_not_v2_map(index):
    h = StockScheduleHarness(STOCK)
    for flags in range(256):
        for enabled in (0, 1):
            h.uc.mem_write(0x208AAC, bytes([73, flags, 0xA5, 0x5A]))
            h.uc.mem_write(0x208AB1, b"\xee")  # other firmware's field is a sentinel
            h.call(SETTERS[index], enabled)
            assert bytes(h.uc.mem_read(0x208AAC, 4)) == bytes([
                73, (flags & ~(1 << index)) | (enabled << index), 0xA5, 0x5A])
            assert bytes(h.uc.mem_read(0x208AB1, 1)) == b"\xee"


def test_changed_controls_are_read_fresh_not_cached_or_overwritten(linked):
    h = SettingsThumb(linked, (5, 0x1F, 3, 1))
    original = h.call("wss_read_controls")
    for address in h.FIELDS:
        old = bytes(h.uc.mem_read(address, 1))
        h.uc.mem_write(address, bytes([old[0] ^ 0x80]))
        changed = h.call("wss_read_controls")
        assert changed != original
        h.uc.mem_write(address, old)
        assert h.call("wss_read_controls") == original
    # Returning to identical values returns identical bits: deliberately NOT a
    # monotonic revision/ABA detector, nor an admission or resume receipt.


def test_real_start_paths_use_real_current_enable_bits_not_boolean_fixtures():
    h = StockScheduleHarness(STOCK)
    h.settings_enabled_fixture = False
    for flags in range(32):
        h.set_controls(enables=flags)
        for index, job in enumerate(SCHEDULED_JOBS):
            h.messages.clear()
            h.timer_starts.clear()
            h.call(job.start)
            assert h.messages == ([(3, 1, job.mask)] if flags & (1 << index) else [])
            assert bool(h.timer_starts) == bool(flags & (1 << index))
    assert set(GETTERS).issubset(h.executed)


@pytest.mark.parametrize("interval", [0, 1, 5, 60, 255])
def test_original_minute_scheduler_respects_all_32_enable_combinations(interval):
    h = StockScheduleHarness(STOCK)
    for flags in range(32):
        h.set_controls(interval=interval, enables=flags)
        for minute in range(60):
            h.messages.clear()
            h.timer_starts.clear()
            seconds = 3600 + minute * 60
            h.tick(seconds)
            # Expected stock call order is HR, SpO2/owner100, owner200, owner1000.
            expected = []
            if flags & 1 and interval and seconds % (interval * 60) == 0:
                expected.append(0x10)
            if flags & 2 and minute == 32: expected.append(0x80)
            if flags & 8 and minute == 0: expected.append(0x100)
            if flags & 4 and minute % 30 == 0: expected.append(0x200)
            if flags & 16 and minute % 30 == 0: expected.append(0x1000)
            assert h.messages == [(3, 1, mask) for mask in expected]
            assert len(h.timer_starts) == len(expected)
            assert struct.unpack("<I", h.uc.mem_read(PENDING_SECONDS, 4))[0] == 0
            assert struct.unpack("<I", h.uc.mem_read(SCHEDULER_SECONDS, 4))[0] == seconds
    if not interval:
        # Stock's real zero-divisor helper returns quotient 0, remainder equal
        # to its input. At these nonzero seconds HR is not selected. No default
        # interval or error receipt is invented by the new read primitive.
        assert {0x17E5A, 0x17F18, 0x17F20}.issubset(h.executed)


@pytest.mark.parametrize("mode,time_set", [(0, 1), (1, 1), (2, 1), (4, 1), (3, 0), (3, 2)])
def test_global_stock_scheduler_guards_remain_effective(mode, time_set):
    h = StockScheduleHarness(STOCK)
    h.set_controls(mode=mode, time_set=time_set)
    h.tick(3600)
    assert not h.messages and not h.timer_starts


@pytest.mark.parametrize("wear,busy", [(1, 0), (0, 1), (1, 1)])
def test_due_time_and_enabled_settings_do_not_override_wear_or_charge_guards(wear, busy):
    h = StockScheduleHarness(STOCK)
    h.set_controls()
    h.wear_fixture, h.busy_fixture = wear, busy
    h.tick(3600)
    assert not h.messages and not h.timer_starts


def test_whole_minute_dispatcher_is_stateful_not_a_resume_or_capability_probe():
    h = StockScheduleHarness(STOCK)
    h.set_controls()
    h.tick(3600)
    first = list(h.messages)
    assert first
    assert {0xE4DE, 0x373E, 0xB53E, 0x11C0}.issubset({p for p, _ in h.bookkeeping})
    assert bytes(h.uc.mem_read(PENDING_SECONDS, 4)) == bytes(4)
    h.messages.clear()
    h.bookkeeping.clear()
    h.call(0x1202)  # no pending tick: does NOT restart the just-started jobs
    assert not h.messages and not h.bookkeeping
    assert h.clock_calls[-1] == 0x1A3C


def test_stock_tick_does_not_replay_due_minutes_skipped_by_a_late_elapsed_delta():
    for seconds, pending in ((3601, 2), (3661, 121), (7201, 3602)):
        h = StockScheduleHarness(STOCK)
        h.set_controls()
        h.tick(seconds, pending)
        assert not h.messages and not h.bookkeeping
        assert bytes(h.uc.mem_read(PENDING_SECONDS, 4)) == bytes(4)
        assert struct.unpack("<I", h.uc.mem_read(SCHEDULER_SECONDS, 4))[0] == seconds
    # Suspending/replaying the whole tick is NOT a preserving pause policy.
    # Keep non-optical time/bookkeeping alive; bind optical admissions separately.


def test_changed_settings_at_next_natural_due_boundary_do_not_replay_old_hr():
    h = StockScheduleHarness(STOCK)
    h.set_controls(enables=1, interval=5)
    h.tick(60 * 65)
    assert h.messages == [(3, 1, 0x10)]
    h.messages.clear()
    h.call(SETTERS[0], 0)
    h.call(SETTERS[1], 1)
    h.tick(60 * 70)
    assert not h.messages  # old HR schedule was not replayed
    h.tick(60 * 92)
    assert h.messages == [(3, 1, 0x80)]
    assert bytes(h.uc.mem_read(ENABLES, 1)) == b"\x02"
    # These are unmodified scheduler calls with synthetic time, not an actual
    # Gesture pause, serialized commit or on-ring optical measurement.


@pytest.mark.parametrize("index,expected", [
    (0, [(0x20C0CC, 4, 0), (0x20C0D0, 4, 0), (0x20C0CC, 4, 259200),
         (0x20C0C0, 1, 1), (0x20C0C1, 1, 0)]),
    (1, [(0x20C0A9, 1, 0), (0x20C0A8, 1, 0), (0x20C0B0, 4, 259200)]),
    (2, [(0x20C0E4, 1, 0), (0x20C0E6, 1, 0), (0x20C0FA, 1, 30)]),
    (3, [(0x20C0FB, 1, 0), (0x20C0F9, 1, 0), (0x20C0FA, 1, 30)]),
    (4, [(0x20C100, 1, 0), (0x20C102, 1, 0)]),
])
def test_real_start_direct_writes_are_working_state_not_a_preserving_timer_resume(index, expected):
    h = StockScheduleHarness(STOCK)
    h.set_controls()
    h.uc.mem_write(0x20C0A8, b"\xa5" * 0x6C)
    writes = []
    h.uc.hook_add(h.u.UC_HOOK_MEM_WRITE,
                  lambda uc, access, address, size, value, opaque:
                  writes.append((address, size, value)), begin=0x200000, end=0x217FFF)
    h.call(SCHEDULED_JOBS[index].start)
    assert writes == expected
    # No real timer/queue/peripheral operation was delivered. These direct
    # stores do not prove downstream persistence or step/sleep preservation.
    # Notably jobs 2 and 3 share the write at 0x20c0fa: no independent-state claim.
