"""Two-entry raw retirement in emulator memory only; never a firmware patch.

Real selected STOCK Thumb executes against named I2C/RTOS/algorithm fixtures.
Equality covers the exercised routes, not whole-program entry closure, physical
Health, timer draining, recovery, reclaimed capacity or production admission.
"""
from pathlib import Path
import hashlib
import struct

import pytest

pytest.importorskip("unicorn", reason="requires requirements-firmware-proof.txt")

from whip.fwcontinuity import (  # noqa: E402
    BIAS, BUFFER_BYTES, FIFO_DRAIN, HEALTH_CONSUME, HEALTH_FEED, ProofError,
)
from whip.fwhealth_lifecycle import (  # noqa: E402
    OPTICAL_CONFIG, OPTICAL_DISABLE, OPTICAL_ENABLE, StockFeedHarness,
)
from whip.fwhealth_schedule import StockScheduleHarness  # noqa: E402
from whip.fwstock_binding import MOCK_TIMER, StockBindingHarness  # noqa: E402
from whip.fwunified import STOCK_SHA256  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STOCK_PATH = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
STOCK = STOCK_PATH.read_bytes()
ENTRIES = (0x1E4A, 0x2104)
CORE = ((0x1E4A, 0x1F42), (0x1F70, 0x2104), (0x2104, 0x2348))
RETURN_ZERO = bytes.fromhex("00207047")
RAW_FLAG, RAW_MODE, RAW_AUX, RAW_TIMER = 0x209CB0, 0x209CB1, 0x209CB2, 0x209CC0
PACKET, COUNT = 0x221800, 0x221900
IDLE_CALLBACKS = (0x30020, 0x30024)  # named fixture calls, not real ROM routines


@pytest.fixture(scope="module", autouse=True)
def stock_file_is_never_modified():
    assert hashlib.sha256(STOCK).hexdigest() == STOCK_SHA256
    yield
    assert STOCK_PATH.read_bytes() == STOCK


class RawRetirement:
    """Common exact-byte experiment and differential memory/ABI guards.

    The stock data/BSS interval is fixture state, not approved writable memory
    for a new firmware. All direct reads/writes are bounded; full fixture RAM
    and ordered writes are compared between baseline and experiment. Parent
    mocks validate their own ABI; host-side mocked writes also enter the final
    RAM comparison. No retired body is erased or repurposed.
    """

    def __init__(self, retired):
        self.retired = retired
        self.direct_writes = []
        self.direct_reads = []
        self.extra_calls = []
        super().__init__(STOCK)
        for entry in ENTRIES:
            assert STOCK[entry:entry + 4] == bytes.fromhex("f0b589b0")
            if retired:
                self.uc.mem_write(BIAS + entry, RETURN_ZERO)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ, self._bounded_read)
        self.uc.hook_add(self.u.UC_HOOK_MEM_WRITE, self._bounded_write)
        for number in range(4, 12):
            self.uc.reg_write(getattr(self.a, f"UC_ARM_REG_R{number}"), 0xA5500000 + number)

    def _writable(self, address, size):
        return size >= 0 and any(lo <= address <= address + size <= hi for lo, hi in (
            (0x2084B0, 0x20E734),  # original initialized data/BSS fixture
            (0x220000, 0x224000),  # explicit mock heap, buffers and input records
            (self.STACK - 2048, self.STACK + 16),
        ))

    def _ram_span(self, address, length):
        if not self._writable(address, length):
            raise ProofError("raw experiment mock escaped bounded fixture RAM")

    def _bounded_read(self, uc, access, address, size, value, opaque):
        self.direct_reads.append((address, size))
        if self._writable(address, size):
            return
        if BIAS <= address < address + size <= BIAS + len(STOCK):
            return
        if address == 0x20011C and size == 4:  # stock delay-pointer fixture
            return
        raise ProofError(f"raw experiment unreviewed data read {address:#x}/{size}")

    def _bounded_write(self, uc, access, address, size, value, opaque):
        if not self._writable(address, size):
            raise ProofError(f"raw experiment unreviewed data write {address:#x}/{size}")
        self.direct_writes.append((uc.reg_read(self.a.UC_ARM_REG_PC) - BIAS,
                                   address, size, value))

    def _extra_code(self, uc, address, size, opaque):
        return False

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if self.retired and any(lo <= offset < hi for lo, hi in CORE):
            if not any(entry <= offset < offset + size <= entry + 4 for entry in ENTRIES):
                raise ProofError("execution bypassed a retired raw entry")
            self.executed.add(offset)
            return
        if self._extra_code(uc, address, size, opaque):
            return
        super()._code(uc, address, size, opaque)

    def call(self, offset, *args, **kwargs):
        saved = [getattr(self.a, f"UC_ARM_REG_R{number}") for number in range(4, 12)]
        before = [self.uc.reg_read(reg) for reg in saved]
        mask = self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
        result = super().call(offset, *args, **kwargs)
        assert [self.uc.reg_read(reg) for reg in saved] == before
        assert self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == mask
        return result

    def observations(self):
        names = ("extra_calls", "direct_writes", "direct_reads", "notifications", "timer_calls",
                 "messages", "post_attempts", "timer_starts", "optical_starts", "transfers",
                 "mutex_events", "stk_writes", "mock_calls", "i2c_calls", "fifo",
                 "health_inputs", "filtered_magnitudes", "aggregate_calls", "bookkeeping",
                 "clock_calls")
        return (bytes(self.uc.mem_read(0x200000, 0x30000)),
                {name: list(getattr(self, name)) for name in names if hasattr(self, name)})


class RawStock(RawRetirement, StockBindingHarness):
    """Actual raw/retained commands with transport, reset and idle fixtures.

    A0 getters/checksum and 9C command/timer-wrapper instructions execute.
    Notification delivery, 9C reset subsystems, charging-tail subsystem calls
    and idle callbacks are explicit recorded substitutes, never Health proofs.
    """

    RANGES = CORE + (
        (0x1CB4, 0x1CFA), (0x1DCA, 0x1E4A),  # 9C, A0, raw mode getter
        (0x2C36, 0x2C44), (0x2C54, 0x2C5E), (0x2DAE, 0x2DBA),
        (0x3282, 0x3288), (0x34EE, 0x34FE),  # charging tail only, not whole handler
        (0x3FE8, 0x4002), (0xA762, 0xA798), (0xC8B6, 0xC8BE),
        (0xDF40, 0xDF68), (0xDFCE, 0xDFDC),
        (0xF80E, 0xF812), (0xF92E, 0xF934), (0x14900, 0x14902),
    )
    RESET_FIXTURES = (0x3768, 0xE4F2, 0xB85A, 0xB086, 0x1A7C, 0xF762, 0x162A)

    def __init__(self, retired):
        self.notifications = []
        self.idle_results = (1, 1)
        super().__init__(retired)

    def _extra_code(self, uc, address, size, opaque):
        offset = address - BIAS
        args = tuple(uc.reg_read(reg) for reg in self.registers)
        if offset == 0x7E30:
            self._ram_span(args[0], 16)
            packet = bytes(uc.mem_read(args[0], 16))
            if packet[0] not in (0xA0, 0xA1, 0x9C) or packet[15] != sum(packet[:15]) % 256:
                raise ProofError("unreviewed raw/retained notification ABI")
            self.notifications.append(packet)
            self._return()
            return True
        if offset in self.RESET_FIXTURES or offset in (0x3328, 0x6AB6):
            if offset == 0x3328 and args[0] != 1:
                raise ProofError("charging-tail fixture expects charging=1")
            self.extra_calls.append((offset, args))
            self._return()
            return True
        if address in IDLE_CALLBACKS:
            if uc.reg_read(self.a.UC_ARM_REG_LR) != BIAS + 0xA787:
                raise ProofError("idle fixture entered outside exact table-call site")
            index = IDLE_CALLBACKS.index(address)
            self.extra_calls.append(("idle", index))
            self._return(self.idle_results[index])
            return True
        if any(lo <= offset < offset + size <= hi for lo, hi in self.RANGES):
            self.executed.add(offset)
            return True
        return False

    def charging_tail(self):
        """Execute 34ee..34fc with the original caller's six-word frame.

        This is a named in-function entry fixture, NOT a full charging event.
        R5=0 is the value established at3444; R6 names the original state block.
        """
        a, uc = self.a, self.uc
        saved = [getattr(a, f"UC_ARM_REG_R{number}") for number in range(3, 8)]
        original = [uc.reg_read(reg) for reg in saved]
        uc.mem_write(self.STACK - 24, struct.pack("<6I", *original, self.STOP | 1))
        uc.reg_write(a.UC_ARM_REG_SP, self.STACK - 24)
        uc.reg_write(a.UC_ARM_REG_R5, 0)
        uc.reg_write(a.UC_ARM_REG_R6, 0x209CF8)
        uc.reg_write(a.UC_ARM_REG_LR, self.STOP | 1)
        mask = uc.reg_read(a.UC_ARM_REG_PRIMASK)
        self.returned = False
        uc.emu_start(BIAS + 0x34EF, 0xFFFFFFFF, count=100)
        assert self.returned and uc.reg_read(a.UC_ARM_REG_SP) == self.STACK
        assert [uc.reg_read(reg) for reg in saved] == original
        assert uc.reg_read(a.UC_ARM_REG_PRIMASK) == mask


class RawMotion(RawRetirement, StockFeedHarness):
    """Real optical motion helper -> reader/FIFO -> actual Health front-end.

    Only optical helper's request=0 branch is admitted. I2C bytes, downstream
    step algorithm and aggregate remain the parent's named fixtures.
    """

    def _extra_code(self, uc, address, size, opaque):
        offset = address - BIAS
        if offset == 0xEE50 and uc.reg_read(self.registers[1]) != 0:
            raise ProofError("only optical request=0 is in the raw retirement witness")
        if 0xEE50 <= offset < offset + size <= 0xEF0C or 0xEF3C <= offset < offset + size <= 0xEF44:
            self.executed.add(offset)
            return True
        return False


class RawSchedule(RawRetirement, StockScheduleHarness):
    """Actual schedule selection; time/wear/charge/RTOS/bookkeeping fixtures."""


def seed_a0(h):
    h.uc.mem_write(0x209CEA, struct.pack("<H", 4000))
    h.uc.mem_write(0x209CF4, bytes([77]))
    h.uc.mem_write(0x209CF8, bytes([1]))
    h.uc.mem_write(0x2089EC, struct.pack("<I", 0x1234))
    h.uc.mem_write(0x2089DE, struct.pack("<H", 0x4567))
    prefix = bytes.fromhex("a00123214d0fa0344567") + bytes(5)
    return prefix + bytes([sum(prefix) % 256])


def optical_window(h, *, assert_values=True):
    samples = [(32, -64, 8000), (128, -256, 8032), (160, -288, 8064)]
    h.set_cursors(480, 480)
    h.fifo.extend(samples)
    h.uc.mem_write(OPTICAL_CONFIG, struct.pack("<H", 80))  # 80/40: two latest samples
    h.uc.mem_write(COUNT - 4, b"\xa5" * 10)
    h.call(0xEE50, COUNT, 0)
    count = struct.unpack("<H", h.uc.mem_read(COUNT, 2))[0]
    arrays = [struct.unpack("<2h", h.uc.mem_read(0x20C11C + offset, 4))
              for offset in (0, 0x50, 0xA0)]
    if assert_values:
        assert count == 2
        assert arrays == [(4, 5), (-8, -9), (251, 252)]
    assert bytes(h.uc.mem_read(COUNT - 4, 4)) == b"\xa5" * 4
    assert bytes(h.uc.mem_read(COUNT + 2, 4)) == b"\xa5" * 4
    return samples, count, arrays


def test_exactly_two_entries_change_and_all_pools_neighbors_dfu_and_overlay_remain():
    h = RawStock(True)
    expected = bytearray(STOCK)
    for entry in ENTRIES:
        expected[entry:entry + 4] = RETURN_ZERO
    assert bytes(h.uc.mem_read(BIAS, len(STOCK))) == expected
    assert STOCK_PATH.read_bytes() == STOCK


@pytest.mark.parametrize("entry", ENTRIES)
def test_retired_entries_preserve_dirty_state_and_do_not_claim_timer_shutdown(entry):
    for mask in (0, 1):
        h = RawStock(True)
        h.uc.mem_write(RAW_FLAG, b"\x01\x04\x01")
        h.uc.mem_write(RAW_TIMER, struct.pack("<I", MOCK_TIMER))
        h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
        before = h.observations()
        assert h.call(entry, PACKET, 0x55, 0xAA, 0x1234) == 0
        assert [h.uc.reg_read(reg) for reg in h.registers[1:]] == [0x55, 0xAA, 0x1234]
        assert h.observations() == before
        assert h.executed == {entry, entry + 2}
        assert not h.timer_calls and not h.notifications and not h.messages


def test_retired_interior_shared_epilogue_and_unreviewed_memory_are_rejected():
    for offset in (0x1E4E, 0x1F70, 0x202A, 0x2108):
        with pytest.raises(ProofError, match="bypassed"):
            RawStock(True).call(offset)
    h = RawStock(True)
    h.uc.mem_write(BIAS + ENTRIES[0], bytes.fromhex("08607047"))  # STR r0,[r1]; BX LR mutant
    with pytest.raises(ProofError, match="unreviewed data write"):
        h.call(ENTRIES[0], 1, 0x22D000)  # mapped, but not admitted fixture storage


def test_actual_a1_start_root_is_suppressed_without_silently_simulating_cancellation():
    states = []
    for retired in (False, True):
        h = RawStock(retired)
        h.uc.mem_write(PACKET, b"\xa1\x04" + bytes(14))
        h.fifo.append((100, 200, 8000))
        h.call(0x2104, PACKET)
        states.append(h)
    stock, retired = states
    assert stock.messages == [(3, 2, 0xFFFF), (3, 1, 0x800)]
    assert stock.timer_calls == [("create", RAW_TIMER, 1, 1000, 1, BIAS + 0x1E4B),
                                 ("start", RAW_TIMER)]
    assert [packet[1] for packet in stock.notifications] == [1, 2, 3, 5]
    assert {0x22A4, 0x2342, 0x1F14}.issubset(stock.executed)
    assert not retired.messages and not retired.timer_calls and not retired.notifications
    assert retired.fifo == [(100, 200, 8000)]


def test_mode_zero_does_not_prevent_original_late_raw_callback_notifications():
    outcomes = []
    for retired in (False, True):
        h = RawStock(retired)
        h.uc.mem_write(RAW_TIMER, struct.pack("<I", MOCK_TIMER))
        h.fifo.append((100, 200, 8000))
        callback = struct.unpack("<I", h.uc.mem_read(BIAS + 0x239C, 4))[0]
        assert callback == BIAS + 0x1E4B
        h.call((callback & ~1) - BIAS, MOCK_TIMER)
        assert bytes(h.uc.mem_read(RAW_MODE, 1)) == b"\0"
        assert bytes(h.uc.mem_read(RAW_TIMER, 4)) == struct.pack("<I", MOCK_TIMER)
        assert not h.timer_calls  # neither run proves that a retained timer stopped
        outcomes.append([packet[1] for packet in h.notifications])
    assert outcomes == [[1, 2, 3, 5], []]


def test_a0_actual_getters_checksum_and_packet_match_original_stock():
    observations = []
    for retired in (False, True):
        h = RawStock(retired)
        expected = seed_a0(h)
        h.call(0x1DCA)
        assert h.notifications == [expected]
        assert {0x2C54, 0x3282, 0xC8B6, 0xF80E, 0x2C36, 0x3FE8}.issubset(h.executed)
        observations.append(h.observations())
    assert observations[0] == observations[1]


@pytest.mark.parametrize("subcommand", [0, 0x9C])
def test_9c_retains_same_raw_timer_stop_and_named_reset_boundaries(subcommand):
    for timer in (0, MOCK_TIMER):
        observations = []
        for retired in (False, True):
            h = RawStock(retired)
            h.uc.mem_write(PACKET, bytes([0x9C, subcommand]) + bytes(14))
            h.uc.mem_write(RAW_TIMER, struct.pack("<I", timer))
            h.call(0x1CB4, PACKET)
            assert h.notifications == [b"\x9c" + bytes(14) + b"\x9c"]
            assert h.timer_calls == ([("stop", RAW_TIMER), ("delete", RAW_TIMER)] if timer else [])
            assert [site for site, _ in h.extra_calls] == (
                [0x3768, 0xE4F2, 0xB85A, 0xB086, 0x1A7C] if subcommand == 0x9C else []
            ) + [0xF762, 0x162A]
            assert 0x1CD2 in h.executed and 0x3E30 in h.executed
            observations.append(h.observations())
        assert observations[0] == observations[1]


def test_actual_charging_predicate_and_raw_flag_clear_tail_match_with_named_subsystems():
    observations = []
    for retired in (False, True):
        h = RawStock(retired)
        for state in (0, 1, 0x80, 0xFF):
            h.uc.mem_write(0x209CE8, bytes([state]))
            assert h.call(0x2DAE) == state & 1
        h.uc.mem_write(RAW_FLAG, b"\x01")
        h.charging_tail()
        assert bytes(h.uc.mem_read(RAW_FLAG, 1)) == b"\0"
        assert [site for site, _ in h.extra_calls] == [0x3328, 0x6AB6]
        assert {0x34EE, 0x34F6, 0x34F8}.issubset(h.executed)
        observations.append(h.observations())
    assert observations[0] == observations[1]


def test_actual_idle_table_walk_and_raw_mode_veto_match_stock():
    for raw_mode, callbacks, expected in ((0, (1, 1), 1), (0, (1, 0), 0), (4, (1, 1), 0)):
        observations = []
        for retired in (False, True):
            h = RawStock(retired)
            h.idle_results = callbacks
            h.uc.mem_write(RAW_MODE, bytes([raw_mode]))
            h.uc.mem_write(0x20BC0C, bytes([2]))
            for index, callback in enumerate(IDLE_CALLBACKS):
                record = 0x220600 + index * 16
                h.uc.mem_write(0x20BC10 + index * 4, struct.pack("<I", record))
                h.uc.mem_write(record + 12, struct.pack("<I", callback | 1))
            assert h.call(0xA762) == expected
            assert h.extra_calls == ([] if raw_mode == 4 else [("idle", 0), ("idle", 1)])
            assert 0x1E42 in h.executed
            observations.append(h.observations())
        assert observations[0] == observations[1]


def test_actual_minute_selection_and_current_settings_preserve_named_bookkeeping():
    for seconds, busy, expected_masks in ((3600, 0, [0x10, 0x100, 0x200, 0x1000]),
                                          (5520, 0, [0x80]), (3600, 1, [])):
        observations = []
        for retired in (False, True):
            h = RawSchedule(retired)
            h.set_controls(interval=5, enables=0x1F)
            h.busy_fixture = busy
            h.tick(seconds)
            assert h.messages == [(3, 1, mask) for mask in expected_masks]
            assert len(h.timer_starts) == len(expected_masks)
            assert 0x1202 in h.executed
            if expected_masks:
                assert any(getter in h.executed for getter in (0x1726, 0x176A, 0x1880))
            assert h.bookkeeping  # recorded substitutes, not history/steps/sleep execution
            observations.append(h.observations())
        assert observations[0] == observations[1]


@pytest.mark.parametrize("probe_ok", [False, True])
def test_normal_optical_enable_disable_and_actual_tx_match_stock(probe_ok):
    observations = []
    for retired in (False, True):
        h = RawStock(retired)
        h.probe_ok = probe_ok
        h.call(OPTICAL_ENABLE, 0x10)
        assert bool(h.optical_starts) is probe_ok
        h.call(OPTICAL_DISABLE, 0x10)
        assert h.ownership() == 0
        assert h.transfers == [b"\x7b\xa5", b"\x7b\0"]
        assert h.mutex_events == ["take", "give", "take", "give"]
        assert {OPTICAL_ENABLE, OPTICAL_DISABLE, 0xEE12, 0xDBCA}.issubset(h.executed)
        observations.append(h.observations())
    assert observations[0] == observations[1]


def test_actual_optical_caller_keeps_shared_reader_fifo_and_health_frontend_inputs():
    observations = []
    for retired in (False, True):
        h = RawMotion(retired)
        samples, _, _ = optical_window(h)
        assert h.cursor() == (480 + 18) % BUFFER_BYTES and h.cursor(health=True) == 480
        assert h.consume_health() == [(y, x, z) for x, y, z in samples]
        assert h.filtered_magnitudes == [8000, 8022, 8051]
        assert {0xEE50, 0xEE86, 0xCC32, FIFO_DRAIN, HEALTH_CONSUME,
                HEALTH_FEED, 0x1D4CC}.issubset(h.executed)
        observations.append(h.observations())
    assert observations[0] == observations[1]


def test_stock_fifo_health_input_filter_and_failure_behavior_stay_identical():
    for data_ok in (True, False):
        observations = []
        for retired in (False, True):
            h = RawMotion(retired)
            samples = [(1, 2, 0), (-32000, 31000, -100), (4, 5, -1), (6, 7, 8000)]
            h.set_cursors(486, 486)
            h.fifo.extend(samples)
            h.fifo_data_ok = data_ok
            h.call(FIFO_DRAIN)
            expected = [(31000, -32000, -100), (7, 6, 8000)] if data_ok else []
            assert h.consume_health() == expected
            assert len(h.filtered_magnitudes) == len(expected)
            assert h.cursor() == (486 + 24) % BUFFER_BYTES
            observations.append(h.observations())
        assert observations[0] == observations[1]


def test_deleting_shared_reader_or_shared_a0_literal_is_detected_by_independent_oracles():
    motion = RawMotion(True)
    motion.uc.mem_write(BIAS + 0xCC32, RETURN_ZERO)  # forbidden overbroad retirement mutant
    with pytest.raises(AssertionError):
        optical_window(motion)
    command = RawStock(True)
    expected = seed_a0(command)
    command.uc.mem_write(BIAS + 0x1F48, struct.pack("<I", 0x209000))
    command.call(0x1DCA)
    with pytest.raises(AssertionError):
        assert command.notifications == [expected]
