"""Compiled actual-address HR commit + exact-stock store equivalence, OFFLINE.

Interrupt arrival/deferral is an explicit emulator schedule, not an RTOS/NMI
proof. Origin tickets and measured provenance still require real bindings.
"""
import struct

import pytest

from tests.test_fwstock_link import linked, STOCK, DESCRIPTOR  # noqa: F401
from whip.fwstock_link import StockAppendThumb
from whip.fwthumb import ThumbProofError
from whip.fwcontinuity import BIAS
from whip.fwoptical_dispatch import StockOpticalDispatchHarness, OPTICAL, CONTEXT

HEALTH_BYTES = 168  # verified by unchanged compiled wh_init/field accesses
FIELDS = ((0x20C020, 1), (0x20C01E, 1), (0x20C028, 1), (0x20C022, 2))


class CommitThumb(StockAppendThumb):
    def __init__(self, elf):
        self.active = False
        self.trace, self.cache_writes, self.adapter_reads = [], [], []
        self.interrupt_at = None
        self.pause_bytes = None
        self.pending_interrupt = False
        self.delivered_at = None
        super().__init__(elf, STOCK, DESCRIPTOR)
        self.uc.mem_map(0x20C000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_write(0x20C000, b"\xa5" * 0x1000)
        self.invoke("wh_init", 1, 1)
        assert self.invoke("wh_job_begin", 0, self.OUTPUT)
        self.original = struct.unpack("<IIB3x", self.uc.mem_read(self.OUTPUT, 12))
        self.initial_adapter = bytes(self.uc.mem_read(self.CONTEXT, HEALTH_BYTES))

    def _code(self, uc, address, size, opaque):
        if address == self.symbols["wrc_commit_hr"] & ~1:
            self.active = True
        if self.active:
            index = len(self.trace)
            if index == self.interrupt_at: self.pending_interrupt = True
            masked = uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
            if self.pending_interrupt and not masked:
                assert self.pause_bytes is not None
                # Precomputed by actual wh_begin_quiesce in another ARM runner.
                # Emulate its atomic state effect without nested CPU execution.
                uc.mem_write(self.CONTEXT, self.pause_bytes)
                self.pending_interrupt = False
                self.delivered_at = index
            self.trace.append((address, masked))
            if address != self.RETURN:
                allowed = ("wrc_commit_hr", "wh_result_allowed", "ticket_matches")
                starts = [self.symbols[name] & ~1 for name in allowed]
                spans = [(lo, hi) for lo, hi in self.executable if lo in starts]
                if not any(lo <= address and address + size <= hi for lo, hi in spans):
                    raise ThumbProofError("commit called outside bounded pure-C guard")
            else:
                self.active = False
        super()._code(uc, address, size, opaque)

    def _read(self, uc, access, address, size, value, opaque):
        if self.active and self.CONTEXT <= address < self.CONTEXT + self.context_size:
            if uc.reg_read(self.a.UC_ARM_REG_PRIMASK) != 1:
                raise ThumbProofError("ticket read outside critical section")
            self.adapter_reads.append((address, size))
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        if 0x20C000 <= address < 0x20D000:
            if (address, size) not in FIELDS or not self.active:
                raise ThumbProofError("unexpected stock cache write")
            if uc.reg_read(self.a.UC_ARM_REG_PRIMASK) != 1:
                raise ThumbProofError("cache store outside critical section")
            self.cache_writes.append((len(self.trace) - 1, address, size,
                                      value & ((1 << (8 * size)) - 1)))
            return
        if self.active and self.CONTEXT <= address < self.CONTEXT + self.context_size:
            raise ThumbProofError("result commit modified adapter state")
        super()._write(uc, access, address, size, value, opaque)

    def commit(self, *, ticket=None, measured=True, value=72, auxiliary=0x1234,
               primask=0, ipsr=0, null=False):
        self.trace.clear(); self.cache_writes.clear(); self.adapter_reads.clear()
        self.uc.reg_write(self.a.UC_ARM_REG_PRIMASK, primask)
        self.uc.reg_write(self.a.UC_ARM_REG_IPSR, ipsr)
        result = self.call("wrc_commit_hr", 0 if null else self.CONTEXT,
                           *(self.original if ticket is None else ticket), int(measured),
                           value & 0xFFFFFFFF, auxiliary)
        assert self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == primask
        assert self.uc.reg_read(self.a.UC_ARM_REG_IPSR) == ipsr
        assert len(self.trace) <= 96  # reviewed instruction bound, not clock cycles
        assert self.stack_low >= self.STACK - 56  # includes pure-C callees
        return result

    def cache(self):
        return bytes(self.uc.mem_read(OPTICAL, 16))


class OriginalPositiveStores(StockOpticalDispatchHarness):
    """Exact selected basic block, not a whole acquisition/provenance proof."""
    def _code(self, uc, address, size, opaque):
        if address == BIAS + 0xF464:
            self._return()
            return
        super()._code(uc, address, size, opaque)


def stock_stores(value, auxiliary):
    h = OriginalPositiveStores(STOCK)
    h.uc.mem_write(OPTICAL, b"\xa5" * 16)
    h.uc.mem_write(CONTEXT + 0x28, struct.pack("<H", auxiliary))
    h.uc.reg_write(h.a.UC_ARM_REG_R6, CONTEXT)
    h.call(0xF456, value)  # caller's positive-value branch is already selected
    return bytes(h.uc.mem_read(OPTICAL, 16))


@pytest.mark.parametrize("value", [1, 40, 72, 120, 255, 256, 65535, 0x7FFFFFFF])
@pytest.mark.parametrize("auxiliary,primask", [(0, 0), (0xFFFF, 1)])
def test_compiled_commit_matches_all_selected_stock_stores_without_changing_neighbors(linked, value, auxiliary, primask):
    h = CommitThumb(linked)
    assert h.commit(value=value, auxiliary=auxiliary, primask=primask) == 1
    assert h.cache() == stock_stores(value, auxiliary)
    assert [(address, size) for _, address, size, _ in h.cache_writes] == list(FIELDS)
    assert bytes(h.uc.mem_read(h.CONTEXT, HEALTH_BYTES)) == h.initial_adapter
    page = bytes(h.uc.mem_read(0x20C000, 0x1000))
    allowed = {address + i - 0x20C000 for address, size in FIELDS for i in range(size)}
    assert all(byte == 0xA5 for i, byte in enumerate(page) if i not in allowed)


@pytest.mark.parametrize("reason", ["null", "zero", "negative", "min_int", "unmeasured", "unproven_inventory"])
@pytest.mark.parametrize("primask", [0, 1])
def test_invalid_source_or_unproven_binding_makes_no_stock_write_and_restores_mask(linked, reason, primask):
    h = CommitThumb(linked)
    if reason == "unproven_inventory":
        h.uc.mem_write(h.CONTEXT + 164, b"\0")  # malformed HEALTH state stays closed
    values = {"zero": 0, "negative": -1, "min_int": -0x80000000}
    before = bytes(h.uc.mem_read(h.CONTEXT, HEALTH_BYTES))
    assert h.commit(null=reason == "null", measured=reason != "unmeasured",
                    value=values.get(reason, 72), primask=primask) == 0
    assert h.cache() == b"\xa5" * 16 and not h.cache_writes
    assert bytes(h.uc.mem_read(h.CONTEXT, HEALTH_BYTES)) == before


@pytest.mark.parametrize("ipsr", [2, 3, 11, 15, 16, 31])
@pytest.mark.parametrize("primask", [0, 1])
def test_exception_context_never_commits_even_with_valid_ticket(linked, ipsr, primask):
    h = CommitThumb(linked)
    assert not h.commit(ipsr=ipsr, primask=primask)
    assert not h.cache_writes and not h.adapter_reads


@pytest.mark.parametrize("phase", ["quiescing", "paused", "resuming", "ready", "fault", "resumed"])
def test_actual_arm_lifecycle_rejects_old_work_through_every_pause_resume_phase(linked, phase):
    h = CommitThumb(linked)
    assert h.invoke("wh_begin_quiesce", 1)
    if phase in ("paused", "resuming", "ready", "resumed"):
        assert h.invoke("wh_cancelled", 1, 2, 1)
        assert h.invoke("wh_fenced", 1, 2)
        assert h.invoke("wh_stopped", 1, 2, 1)  # explicit synthetic STOP receipt
    if phase in ("resuming", "ready", "resumed"):
        assert h.invoke("wh_begin_resume", 2, 17)
    if phase in ("ready", "resumed"):
        assert h.invoke("wh_resume_ready", 2, 3, 17, 1, 1)
    if phase == "resumed":
        assert h.invoke("wh_commit_health", 2, 17)
        assert h.invoke("wh_job_begin", 0, h.OUTPUT)
    if phase == "fault": h.invoke("wh_fail")
    assert not h.commit() and not h.cache_writes
    if phase == "resumed":
        new = struct.unpack("<IIB3x", h.uc.mem_read(h.OUTPUT, 12))
        assert new != h.original and h.commit(ticket=new)
        assert h.cache() == stock_stores(72, 0x1234)


@pytest.mark.parametrize("ticket", [(0, 1, 0), (2, 1, 0), (1, 0, 0), (1, 2, 0),
                                    (1, 1, 1), (1, 1, 31), (1, 1, 32), (1, 1, 255)])
def test_wrong_original_identity_does_not_commit(linked, ticket):
    h = CommitThumb(linked)
    assert not h.commit(ticket=ticket)
    assert not h.cache_writes


def test_same_job_new_serial_without_mode_switch_rejects_old_ticket(linked):
    h = CommitThumb(linked)
    assert h.invoke("wh_job_end", *h.original)
    assert h.invoke("wh_job_begin", 0, h.OUTPUT)
    assert not h.commit()
    new = struct.unpack("<IIB3x", h.uc.mem_read(h.OUTPUT, 12))
    assert new[0] == h.original[0] and new[1] > h.original[1]
    assert h.commit(ticket=new)


def test_maskable_pause_at_each_instruction_linearizes_before_or_after_all_stores(linked):
    baseline = CommitThumb(linked)
    assert baseline.commit()
    pause = CommitThumb(linked)
    assert pause.invoke("wh_begin_quiesce", 1)
    pause_bytes = bytes(pause.uc.mem_read(pause.CONTEXT, HEALTH_BYTES))
    arrivals = len(baseline.trace)
    assert arrivals > 40
    outcomes = set()
    for index in range(arrivals):
        h = CommitThumb(linked)
        h.interrupt_at, h.pause_bytes = index, pause_bytes
        accepted = h.commit()
        outcomes.add(accepted)
        assert len(h.cache_writes) == (4 if accepted else 0)
        assert h.delivered_at is not None and not h.pending_interrupt
        if accepted:
            assert all(i < h.delivered_at for i, *_ in h.cache_writes)
            assert h.cache() == baseline.cache()
        else:
            assert h.cache() == b"\xa5" * 16
        assert bytes(h.uc.mem_read(h.CONTEXT, HEALTH_BYTES)) == pause_bytes
    assert outcomes == {0, 1}
    # Deferral follows observed PRIMASK, not fabricated stock/RTOS scheduling.


def test_preexisting_mask_is_never_released_for_pending_pause(linked):
    h = CommitThumb(linked)
    pause = CommitThumb(linked); assert pause.invoke("wh_begin_quiesce", 1)
    h.pause_bytes = bytes(pause.uc.mem_read(pause.CONTEXT, HEALTH_BYTES))
    h.interrupt_at = 0
    assert h.commit(primask=1)
    assert h.delivered_at is None and h.pending_interrupt
    assert bytes(h.uc.mem_read(h.CONTEXT, HEALTH_BYTES)) == h.initial_adapter


def test_original_hr_producer_can_use_job_31_without_assigning_a_production_inventory(linked):
    h = CommitThumb(linked)
    h.invoke("wh_init", 0x80000000, 1)
    assert h.invoke("wh_job_begin", 31, h.OUTPUT)
    origin = struct.unpack("<IIB3x", h.uc.mem_read(h.OUTPUT, 12))
    assert h.commit(ticket=origin)
    # Association of this job with an HR-producing source is a caller proof,
    # not inferred by the primitive or manufactured as a production mask here.


def test_emulator_only_missing_interrupt_mask_mutant_is_detected(linked):
    h = CommitThumb(linked)
    start = h.symbols["wrc_commit_hr"] & ~1
    end = next(hi for lo, hi in h.executable if lo == start)
    body = bytes(h.uc.mem_read(start, end - start))
    assert body.count(b"\x72\xb6") == 1  # CPSID i
    h.uc.mem_write(start + body.index(b"\x72\xb6"), b"\x00\xbf")
    with pytest.raises(ThumbProofError, match="ticket read outside critical section"):
        h.commit()
    assert not h.cache_writes


def test_emulator_only_missing_mask_restore_mutant_is_detected(linked):
    baseline = CommitThumb(linked); assert baseline.commit()
    sites = [pc for (pc, masked), (_, following) in zip(baseline.trace, baseline.trace[1:])
             if masked == 1 and following == 0]
    assert len(sites) == 1
    h = CommitThumb(linked)
    first, second = struct.unpack("<HH", h.uc.mem_read(sites[0], 4))
    assert first & 0xFFF0 == 0xF380 and second == 0x8810  # MSR PRIMASK, register
    h.uc.mem_write(sites[0], b"\x00\xbf\x00\xbf")
    with pytest.raises(AssertionError): h.commit()
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 1 and len(h.cache_writes) == 4
    # Only emulator memory was changed; no linked file or stock image mutation.
