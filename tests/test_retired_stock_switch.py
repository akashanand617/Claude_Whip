"""Pinned scattered C + retired stock roots in ONE persistent ARM context.

OFF-RING, UNOWNED, NOT INSTALLABLE. The loader is deliberately separate from
the production/append-only loader. Existing coordinator, I/O, notification and
motion oracles are reused; no production verifier is weakened. Hardware,
producer drain, source time and current-settings preparation remain fixtures.
"""
from io import BytesIO
import struct

from elftools.elf.elffile import ELFFile
import pytest

from tests.test_stock_coordinator import (
    CoordinatorThumb, coordinator_build, OWNER, STOP_RECEIPT, REVISION,
    PREPARED, HEALTH_MODE, ENTERING, GESTURE, RETURNING, FAULT,
    QUIESCE, HOLD, START, STOP, RELEASE, RESUME,
)
from tests.test_stock_switch import SCRATCH, TX_FRAME
from tests.test_stock_optical_work import HEALTH, TICKET, BUFFER, STATUS, REJECTED
from tests.test_stock_retirement import combined, RETIRED_CODE, DESCRIPTOR, SOURCE
from tests.test_raw_retirement import STOCK, RAW_FLAG, RAW_TIMER, RawMotion, optical_window
from tests.test_unified_wire import BOOT, frames, request
from whip.fwcontinuity import BIAS, FIFO_DRAIN, StockMotionHarness, ProofError
from whip.fwoptical_samples import StockOpticalSamplesHarness
from whip.fwoptical_io import SITES, SIGNATURE, CallEdit, _bl
from whip.fwhealth_lifecycle import OPTICAL_CONFIG
from whip.fwstock_binding import MOCK_TIMER
from whip.fwthumb import RuntimeThumb
from whip import fwretirement as retirement

PACKET, COUNT = SCRATCH + 1024, SCRATCH + 1056


@pytest.fixture(scope="module")
def abi(coordinator_build):
    # Separate compiled witnesses, never loaded into the persistent context.
    h = RuntimeThumb(coordinator_build["elf"])
    layout = tuple(h.call("proof_switch_layout", i) for i in range(6))
    sizes = tuple(h.call(name) for name in (
        "proof_wc_owner_size", "proof_wc_stop_size", "proof_wc_resume_size"))
    assert layout == (408, 60, 288, 31, 223, 24)
    assert sizes == (28, 28, 20)
    return layout, sizes


class RetiredSwitch(CoordinatorThumb):
    """Existing operations with a narrowly pinned, emulator-only loader.

    This small initializer replaces the existing artificial/append-only
    loaders. Transitions from outside candidate code must enter through an
    explicit named call, the three exact reviewed stock BLs, or a recorded C
    return. C-to-C execution remains the flow of the exact pinned code.
    An old stock interior is never admitted merely by overlapping new C.
    """
    def __init__(self, raw, plan, abi, *, inventory=True):
        assert plan == retirement.retirement_plan(
            STOCK, raw, DESCRIPTOR, policy_source=SOURCE.read_bytes())
        layout, sizes = abi
        self.functions, self.spans, self.c_spans, self.loads = {}, [], [], []
        self.active = self.pause_bytes = self.returned_mask = None
        self._retire_return = None
        self.retirements = 0
        self.mask_trace, self.guarded_writes = [], []
        self.io_calls, self.release_results, self.take_results = [], {}, {}
        self.gives = self.takes = 0
        self.fixtures, self.observation_stack = [], []
        self.gatt_result, self.gatt_wrappers, self.gatt_sends = 1, 0, []
        self.uart_active, self.dispatches = False, []
        self.call_entry = self.previous_pc = None
        self.c_returns = []
        self.c_executed, self.direct_writes = set(), []
        StockOpticalSamplesHarness.__init__(self, STOCK)
        image = ELFFile(BytesIO(raw))
        for segment in image.iter_segments():
            if segment["p_type"] != "PT_LOAD":
                continue
            lo, size = segment["p_vaddr"], segment["p_memsz"]
            assert segment["p_filesz"] == size and not segment["p_flags"] & 2
            self.uc.mem_write(lo, segment.data())
            assert bytes(self.uc.mem_read(lo, size)) == segment.data()
            self.loads.append((lo, lo + size))
        for symbol in image.get_section_by_name(".symtab").iter_symbols():
            if symbol["st_info"]["type"] == "STT_FUNC" and symbol["st_size"]:
                lo = symbol["st_value"] & ~1
                assert symbol["st_value"] & 1
                assert any(a <= lo < lo + symbol["st_size"] <= b for a, b in self.loads)
                self.functions[symbol.name] = symbol["st_value"]
                self.c_spans.append((lo, lo + symbol["st_size"]))
        assert len(self.c_spans) == 130
        self.spans = self.c_spans + [(BIAS + 0x158EE, BIAS + 0x15918),
                                     (BIAS + 0x1584C, BIAS + 0x15850)]
        self.retirement_plan = plan
        assert STOCK[0x11A76:0x11A9A] == SIGNATURE
        target = self.functions["woi_samples_io"]
        self.io_plan = tuple(CallEdit(site, before, _bl(BIAS + site, target), target)
                             for site, before in SITES)
        edits = (*plan.edits, *self.io_plan)
        assert len(edits) == 18 and len({e.file_offset for e in edits}) == 18
        for edit in edits:
            assert bytes(self.uc.mem_read(BIAS + edit.file_offset, 4)) == edit.before
            self.uc.mem_write(BIAS + edit.file_offset, edit.after)
        self.stock_calls = {BIAS + edit.file_offset: edit.target & ~1 for edit in self.io_plan}
        self.stock_calls[BIAS + retirement.UART_SITE] = self.functions["wlg_receive"] & ~1
        expected = bytearray(STOCK)
        for segment in image.iter_segments():
            if segment["p_type"] != "PT_LOAD":
                continue
            lo, hi = segment["p_vaddr"], segment["p_vaddr"] + segment["p_memsz"]
            start, end = max(lo, BIAS), min(hi, BIAS + len(STOCK))
            if start < end:
                expected[start - BIAS:end - BIAS] = segment.data()[start - lo:end - lo]
        for edit in edits:
            expected[edit.file_offset:edit.file_offset + 4] = edit.after
        assert bytes(self.uc.mem_read(BIAS, len(STOCK))) == expected
        self.uc.hook_add(self.u.UC_HOOK_MEM_WRITE, self._work_write)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ, self._work_read)
        self.uc.hook_add(self.u.UC_HOOK_MEM_WRITE, self._bounded_write)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ, self._bounded_read)
        self.base = HEALTH - layout[0]
        self.owner_size, self.stop_size, self.resume_size = sizes
        self.adapter("wd_init", 1, int(inventory), BOOT & 0xFFFFFFFF, BOOT >> 32)
        profile = struct.pack("<II32sIIHH6B2x", 1, 2, b"\xee" + bytes(31),
                              101, 2000, 20, 20, 0, 0x23, 5, 15, 0x74, 0xC8)
        self.uc.mem_write(SCRATCH, profile)
        self.fixture("inventory and physical profile", inventory)
        assert self.adapter("wa_prepare", SCRATCH)
        assert self.adapter("wd_open", 7, 0, 0)
        self.original = self.new_job() if inventory else None
        self.set_controls((5, 0x1F, 3, 1))
        self.payloads[0xFF] = b"\x12\x34\xab\xcd" + bytes(124)
        for pointer, size in ((OWNER, self.owner_size), (STOP_RECEIPT, self.stop_size)):
            self.uc.mem_write(pointer - 8, b"\xa5" * (size + 16))
        for pointer, size in ((BUFFER, 0x540), (STATUS, 32)):
            self.uc.mem_write(pointer - 8, b"\xa5" * 8)
            self.uc.mem_write(pointer + size, b"\xa5" * 8)
        self.uc.mem_write(REVISION, struct.pack("<I", 17))
        self.function("wc_init", OWNER, self.base)
        self.fixture("serialized task and fixture-only RAM/stack ownership", True)

    def _writable(self, address, size):
        spans = ((0x2084B0, 0x20E734), (BUFFER - 8, BUFFER + 0x548),
                 (STATUS - 8, STATUS + 40), (0x221900, 0x221910),
                 (0x221940, 0x221950), (0x221980, 0x221990), (0x221A00, 0x221A20),
                 (HEALTH - 408, HEALTH - 408 + 796), (TICKET, TICKET + 12),
                 (SCRATCH, SCRATCH + 288), (TX_FRAME, TX_FRAME + 20),
                 (PACKET, PACKET + 16), (COUNT - 4, COUNT + 6),
                 (OWNER - 8, OWNER + 36), (STOP_RECEIPT - 8, STOP_RECEIPT + 36),
                 (REVISION, REVISION + 4), (PREPARED, PREPARED + 28),
                 (self.STACK - 2048, self.STACK + 16))
        return size >= 0 and any(lo <= address <= address + size <= hi for lo, hi in spans)

    def _ram_span(self, address, length):
        if not self._writable(address, length):
            raise ProofError("integration mock escaped bounded fixture RAM")

    def _bounded_write(self, uc, access, address, size, value, opaque):
        if not self._writable(address, size):
            raise ProofError(f"integration unreviewed data write {address:#x}/{size}")
        if self.uart_active and not self.STACK - 128 <= address < address + size <= self.STACK:
            raise ProofError("legacy ingress wrote outside its bounded stack")
        self.direct_writes.append((uc.reg_read(self.a.UC_ARM_REG_PC), address, size, value))

    def _bounded_read(self, uc, access, address, size, value, opaque):
        if self._writable(address, size) or BIAS <= address < address + size <= BIAS + len(STOCK):
            return
        if any(lo <= address < address + size <= hi for lo, hi in self.loads):
            return
        if (address, size) == (0x20011C, 4):
            return
        raise ProofError(f"integration unreviewed data read {address:#x}/{size}")

    def function(self, name, *args):
        self.call_entry = self.functions[name] & ~1
        try:
            return super().function(name, *args)
        finally:
            self.call_entry = None

    def call(self, offset, *args, **kwargs):
        self.previous_pc, self.c_returns = None, []
        result = super().call(offset, *args, **kwargs)
        assert not self.c_returns, "compiled-to-stock continuation was not consumed"
        return result

    def _code(self, uc, address, size, opaque):
        previous = self.previous_pc
        self.previous_pc = address
        candidate = any(lo <= address < address + size <= hi for lo, hi in self.c_spans)
        from_candidate = previous is not None and any(lo <= previous < hi for lo, hi in self.c_spans)
        if candidate and not from_candidate:
            if previous is None and address == self.call_entry:
                pass
            elif previous in self.stock_calls and self.stock_calls[previous] == address:
                pass
            elif self.c_returns and self.c_returns[-1] == address:
                self.c_returns.pop()
            else:
                raise ProofError(f"old stock interior entered relocated C without an admitted edge: "
                                 f"{previous!r} -> {address:#x}, returns={self.c_returns!r}")
        elif from_candidate and not candidate:
            first, second = struct.unpack("<HH", uc.mem_read(previous, 4))
            continuation = None
            if first & 0xF800 == 0xF000 and second & 0xD000 == 0xD000:
                continuation = previous + 4  # actual Thumb BL
            elif first & 0xFF87 == 0x4780:
                continuation = previous + 2  # actual Thumb BLX register
            if continuation is not None:
                assert uc.reg_read(self.a.UC_ARM_REG_LR) & ~1 == continuation
                self.c_returns.append(continuation)
        if candidate:
            self.c_executed.add(address)
        offset = address - BIAS
        if not candidate:
            if any(e.file_offset <= offset < offset + size <= e.file_offset + 4
                   for e in self.retirement_plan.edits if e.file_offset != retirement.UART_SITE):
                self.executed.add(offset)
                return
            if any(lo <= offset < hi for lo, hi in RETIRED_CODE):
                raise ProofError("execution bypassed retired entry into old interior")
        if self.uart_active and offset == 0x5882:
            self.dispatches.append(tuple(uc.reg_read(r) for r in self.registers[:2]))
            self._return(0xD00DFEED)  # recorded dispatch boundary, never Health success
            return
        if self.uart_active and address == 0x5AA8:
            self._return()
            return
        ranges = ((0x657C, 0x66B6), (0x5990, 0x5992), (0x613A, 0x613C))
        if self.uart_active:
            ranges += ((0x7ACE, 0x7B22), (0x5C22, 0x5C32))
        if offset == 0xEE50 and uc.reg_read(self.registers[1]) != 0:
            raise ProofError("only optical motion request=0 is admitted")
        ranges += ((0xEE50, 0xEF0C), (0xEF3C, 0xEF44))
        if not candidate and any(lo <= offset < offset + size <= hi for lo, hi in ranges):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def retired_roots(self):
        """Seeded RTOS queue and stored pointers, not a callback-drain receipt."""
        self.fixture("seeded legacy queue and stored-callback invocations", True)
        queue = 0x209D50
        self.uc.mem_write(queue, struct.pack("<HH", 9, 1))
        for index in (9, 0):
            self.uc.mem_write(queue + 4 + index * 16, b"\xa1\x04" + bytes(14))
        self.uc.mem_write(RAW_FLAG, b"\x01\x04\x01")
        self.uc.mem_write(RAW_TIMER, struct.pack("<I", MOCK_TIMER))
        before = bytes(self.uc.mem_read(RAW_FLAG, 20))
        effects = (len(self.transfers), len(self.receives), len(self.gatt_sends),
                   len(self.messages), len(self.timer_calls), tuple(self.fifo))
        self.call(0x657C)
        assert struct.unpack("<HH", self.uc.mem_read(queue, 4)) == (1, 1)
        assert {0x6688, 0x2104, 0x2106, 0x66A2} <= self.executed
        for literal, entry in ((0x239C, 0x1E4A), (0x3DF0, 0x3AC4), (0x3DF8, 0x3B7A)):
            pointer = struct.unpack("<I", self.uc.mem_read(BIAS + literal, 4))[0]
            assert pointer == BIAS + entry + 1
            assert self.call((pointer & ~1) - BIAS, MOCK_TIMER) == 0
        assert bytes(self.uc.mem_read(RAW_FLAG, 20)) == before
        assert effects == (len(self.transfers), len(self.receives), len(self.gatt_sends),
                           len(self.messages), len(self.timer_calls), tuple(self.fifo))

    def legacy(self, opcode):
        self.uc.mem_write(PACKET, bytes([opcode]) + bytes(15))
        self.uc.mem_write(self.STACK, struct.pack("<4I", 16, PACKET, 0, 0))
        before = bytes(self.uc.mem_read(0x2084B0, 0x6284))
        self.uart_active = True
        try:
            assert self.call(0x7ACE, PACKET, 16, 2, 0) == 0
        finally:
            self.uart_active = False
        assert bytes(self.uc.mem_read(0x2084B0, 0x6284)) == before


def test_persistent_retired_layout_runs_compiled_switch_and_original_health(combined, abi):
    h = RetiredSwitch(*combined, abi)
    baseline = StockMotionHarness(STOCK)
    phases = []

    def feed(label):
        n = len(phases) + 1
        sample = [(n, -n, 8005)]
        baseline.fifo.extend(sample)
        baseline.call(FIFO_DRAIN)
        assert h.drain_motion(sample) == baseline.consume_health()
        assert h.health_inputs == baseline.health_inputs
        h.retired_roots()
        for opcode in retirement.DENIED:
            h.legacy(opcode)
        assert not h.dispatches
        phases.append((label, h.mode(), h.mode(4)))

    assert h.mode() == HEALTH_MODE and h.read() == 0 and h.commit(h.original)
    feed("Health")
    # Both fragments are executed and the first cannot start switching.
    packets = frames(1, 1, request(3))
    for index, packet in enumerate(packets):
        h.uc.mem_write(SCRATCH, packet)
        assert h.adapter("wd_receive", SCRATCH, len(packet), 7, 1)
        if index == 0:
            assert h.mode() == HEALTH_MODE
    assert len(packets) == 2 and (h.mode(), h.mode(4)) == (ENTERING, QUIESCE)
    feed("quiesce")
    assert not h.adapter("wd_reply_next", 7, SCRATCH, 1)
    h.quiet_with_fixtures(1)
    assert h.retirements == 1
    feed("retired/HOLD")
    assert h.physical(h.fixture("held/preserved/configured/serialized source", 0x0F), 1)
    assert h.mode(4) == START
    feed("START pending")
    assert not h.adapter("wd_reply_next", 7, SCRATCH, 1)
    assert h.observe((1, 2, 8005)) == 2 and h.mode() == GESTURE
    h.reply(3, 1, 1)
    assert h.submit_motion(1)[3]
    gesture_session = h.session
    before_reads = len(h.receives)
    assert h.read(ticket=h.original) == REJECTED and not h.commit(h.original)
    assert len(h.receives) == before_reads
    feed("Gesture")
    h.command(2, 2, 2)
    feed("STOP pending")
    assert h.physical(h.fixture("source/callback/transport drained", 0x70), 2)
    assert h.mode(4) == RELEASE
    feed("RELEASE pending")
    assert h.physical(h.fixture("accel released without disturbing Health", 0x82), 2)
    assert h.mode(4) == RESUME
    h.uc.mem_write(REVISION, struct.pack("<I", 18))
    h.set_controls((60, 4, 3, 1))
    h.fixture("serialized monotonic settings revision", 18)
    assert h.pump(2) == 5  # WC_WAIT_RESUME precedes fresh preparation
    feed("fresh preparation pending")
    assert not h.adapter("wd_reply_next", 7, SCRATCH, 2)
    assert h.prepare_resume(revision=18) and h.mode() == HEALTH_MODE
    h.reply(2, 2, 2)
    feed("restored Health")
    assert h.observe((1, 2, 8005), now=2, session=gesture_session, transaction=2) == 0
    assert h.mode() == HEALTH_MODE
    assert not h.commit(h.original) and h.read(ticket=h.original) == REJECTED
    new = h.new_job()
    h.configure_samples()
    h.fixture("fresh optical acquisition setup", True)
    assert h.read(ticket=new) == 0 and h.commit(new)
    assert h.controls() == int.from_bytes(bytes((60, 4, 3, 1)), "little")
    assert len(phases) == 9 and len(h.gatt_sends) == h.gatt_wrappers == 5
    assert not h.allocations and not h.timer_calls
    assert {h.functions[name] & ~1 for name in (
        "wc_pump", "wc_optics_stopped", "wc_resume_prepared", "wc_physical_done",
        "wsc_commit_health", "wop_retire", "woi_samples_io", "wlg_receive")} <= h.c_executed
    # Retained optical helper and shared raw/Health reader also execute here.
    legacy = RawMotion(False)
    samples, count, arrays = optical_window(legacy)
    h.set_cursors(480, 480)
    h.fifo.extend(samples)
    h.uc.mem_write(OPTICAL_CONFIG, struct.pack("<H", 80))
    h.uc.mem_write(COUNT - 4, b"\xa5" * 10)
    h.call(0xEE50, COUNT, 0)
    assert struct.unpack("<H", h.uc.mem_read(COUNT, 2))[0] == count
    assert [struct.unpack("<2h", h.uc.mem_read(0x20C11C + offset, 4))
            for offset in (0, 0x50, 0xA0)] == arrays
    assert h.consume_health() == legacy.consume_health()
    assert h.uc.mem_read(COUNT - 4, 4) == b"\xa5" * 4
    assert h.uc.mem_read(COUNT + 2, 4) == b"\xa5" * 4


@pytest.mark.parametrize("failure", ["take", "reset", "stop", "give", "physical", "retirement"])
def test_retired_layout_stop_failures_keep_gesture_closed(combined, abi, failure):
    h = RetiredSwitch(*combined, abi)
    h.command(3, 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.fixture("producer drain and IRQ/hub/RUN/publication fence", True)
    if failure == "take": h.take_results[0] = False
    elif failure == "give": h.release_results[0] = False
    elif failure in ("reset", "stop"):
        h.transfer_results.extend((1, 0) if failure == "reset" else (0, 1))
    h.pump()
    count = len(h.transfers)
    if failure == "retirement":
        h.uc.mem_write(0x2085A8, struct.pack("<I", STATUS + 4))
    assert not h.stopped(verified=h.fixture("physical STOP outcome", failure != "physical"))
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    assert not h.adapter("wa_health_allowed", 0) and not h.physical(0x0F, 1)
    h.pump()
    assert len(h.transfers) == count
    h.retired_roots()
    assert h.drain_motion([(7, 8, 8005)]) == [(8, 7, 8005)]


@pytest.mark.parametrize("change", ["new_revision", "aba", "unversioned_controls"])
def test_retired_layout_resume_rejects_stale_settings(combined, abi, change):
    h = RetiredSwitch(*combined, abi)
    h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.to_resume()
    assert h.pump(2) == 5
    controls = h.controls()
    h.set_controls((60, 4, 3, 1))
    if change != "unversioned_controls":
        h.uc.mem_write(REVISION, struct.pack("<I", 18))
    if change == "aba":
        h.set_controls((5, 0x1F, 3, 1))
        h.uc.mem_write(REVISION, struct.pack("<I", 19))
    h.fixture("serialized settings writer/revision behavior", change)
    h.retired_roots()
    assert not h.prepare_resume(controls=controls, revision=17)
    assert not h.adapter("wa_health_allowed", 0)
    if change == "unversioned_controls":
        assert h.mode() == FAULT
    else:
        assert h.mode() == RETURNING
        assert h.prepare_resume(revision=19 if change == "aba" else 18)
        assert h.mode() == HEALTH_MODE and not h.commit(h.original)


@pytest.mark.parametrize("trigger", ["disconnect", "charging", "timeout"])
def test_retired_layout_late_stop_receipt_never_advances_new_state(combined, abi, trigger):
    h = RetiredSwitch(*combined, abi)
    h.command(3, 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    if trigger == "disconnect": assert h.adapter("wd_close", 7, 2)
    elif trigger == "charging": assert h.adapter("wd_charging", 7, 1, 2)
    assert not h.stopped(3001 if trigger == "timeout" else 2)
    assert (h.mode(), h.mode(4)) == (RETURNING, STOP)
    h.retired_roots()
    assert not h.commit(h.original)


def test_retired_layout_keeps_code_and_data_boundaries_closed(combined, abi):
    for offset in (0x1E4E, 0x1F70, 0x202A, 0x2108, 0x3AC8, 0x4B08, 0x4C3C):
        with pytest.raises(ProofError, match="interior"):
            RetiredSwitch(*combined, abi).call(offset)
    h = RetiredSwitch(*combined, abi)
    h.uc.mem_write(BIAS + 0x1E4A, bytes.fromhex("08607047"))
    with pytest.raises(ProofError, match="unreviewed data write"):
        h.call(0x1E4A, 1, 0x22D000)
    h = RetiredSwitch(*combined, abi)
    h.uc.mem_write(BIAS + retirement.UART_SITE, retirement.UART_BEFORE)
    h.legacy(0xA1)
    assert h.dispatches == [(PACKET, 16)]  # missing filter is observable


def test_retired_layout_retirement_mask_mutant_is_detected(combined, abi):
    h = RetiredSwitch(*combined, abi)
    h.command(3, 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    start = h.functions["enter"] & ~1
    end = next(hi for lo, hi in h.c_spans if lo == start)
    body = bytes(h.uc.mem_read(start, end - start))
    assert body.count(b"\x72\xb6") == 1
    h.uc.mem_write(start + body.index(b"\x72\xb6"), b"\x00\xbf")
    with pytest.raises(AssertionError):
        h.stopped()


def test_unknown_inventory_stays_default_health_in_retired_layout(combined, abi):
    h = RetiredSwitch(*combined, abi, inventory=False)
    assert h.pump() == 0 and h.adapter("wa_health_passthrough")
    assert not h.adapter("wa_request", 1, 1)
    assert not h.transfers and not h.receives
    h.retired_roots()
    assert h.drain_motion([(1, 2, 8005)]) == [(2, 1, 8005)]
