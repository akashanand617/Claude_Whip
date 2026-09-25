"""Combined conditional ELF + known-root retirement, entirely off ring.

No image writer or ring client. Health I2C/RTOS/algorithm boundaries remain the
named fixtures from the raw-retirement differential tests. Legacy dispatcher
and separate DFU reassembly are recorded boundaries, not simulated success.
"""
import hashlib
from io import BytesIO
import os
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
import pytest

from tests.test_raw_retirement import (
    STOCK, STOCK_PATH, PACKET, RAW_FLAG, RAW_MODE, RAW_TIMER, CORE,
    RawStock, RawMotion, RawSchedule, seed_a0, optical_window,
)
from whip.fwcontinuity import BIAS, ProofError, BUFFER_BYTES
from whip.fwhealth_lifecycle import OPTICAL_ENABLE, OPTICAL_DISABLE
from whip.fwstock_binding import MOCK_TIMER
from whip.fwstock_link import inspect_elf
from whip import fwretirement as retirement

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes()
SOURCE = ROOT / "firmware/unified/stock_legacy_gate.c"
OLD_ELF = ROOT / "firmware/unified/research-20260924-raw-relocation-v2/UNOWNED-raw-relocation-NOT-INSTALLABLE.elf"
DEFAULT_ELF = ROOT / "firmware/unified/research-20260924-raw-retirement-v1/UNOWNED-raw-relocation-NOT-INSTALLABLE.elf"
RETIRED_CODE = (*CORE, (0x3AC4, 0x3DE8), (0x48C6, 0x48E8),
                (0x4910, 0x4924), (0x4B02, 0x4C36), (0x4C36, 0x4CBC))


@pytest.fixture(scope="module")
def combined():
    path = Path(os.environ.get("WHIP_RETIREMENT_ELF", str(DEFAULT_ELF)))
    assert path.is_file(), "a reviewed current A1-denying conditional ELF is required; never skip"
    raw = path.read_bytes()
    plan = retirement.retirement_plan(STOCK, raw, DESCRIPTOR, policy_source=SOURCE.read_bytes())
    return raw, plan


class Overlay:
    """Fresh-emulator admission only; cannot reuse a running stock frame.

    All candidate sections are loaded, but only the legacy helper is executable
    for these probes. A stray old interior never becomes accepted merely
    because its address now lies inside another relocated function.
    """
    def __init__(self, raw, plan):
        super().__init__(False)
        assert plan.elf_sha256 == hashlib.sha256(raw).hexdigest()
        assert plan.stock_sha256 == hashlib.sha256(STOCK).hexdigest()
        self.plan, self.loads = plan, []
        e = ELFFile(BytesIO(raw))
        helper = next(s for s in e.get_section_by_name(".symtab").iter_symbols() if s.name == "wlg_receive")
        self.helper, self.helper_end = helper["st_value"] & ~1, (helper["st_value"] & ~1) + helper["st_size"]
        for segment in e.iter_segments():
            if segment["p_type"] == "PT_LOAD":
                lo, hi = segment["p_vaddr"], segment["p_vaddr"] + segment["p_memsz"]
                self.uc.mem_write(lo, segment.data())
                self.loads.append((lo, hi))
        for edit in plan.edits:
            assert bytes(self.uc.mem_read(BIAS + edit.file_offset, len(edit.before))) == edit.before
            self.uc.mem_write(BIAS + edit.file_offset, edit.after)
        self.uart_active = False
        self.fast_active = False
        self.prelude_boundary = []
        self.dispatches, self.dfu_receives, self.logs = [], [], []

    def _bounded_read(self, uc, access, address, size, value, opaque):
        if self.uart_active:
            if not ((BIAS <= address < address + size <= 0x84A000) or
                    self.STACK - 128 <= address < address + size <= self.STACK + 16 or
                    (address, size) in ((0x208C44, 1), (PACKET, 1))):
                raise ProofError("UART read escaped exact callback/helper fixture")
        if any(lo <= address < address + size <= hi for lo, hi in self.loads):
            self.direct_reads.append((address, size))
            return
        super()._bounded_read(uc, access, address, size, value, opaque)

    def _bounded_write(self, uc, access, address, size, value, opaque):
        if self.uart_active and not self.STACK - 128 <= address < address + size <= self.STACK:
            raise ProofError("UART write escaped bounded stack")
        super()._bounded_write(uc, access, address, size, value, opaque)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if any(edit.file_offset <= offset < offset + size <= edit.file_offset + 4
               for edit in self.plan.edits if edit.file_offset != retirement.UART_SITE):
            self.executed.add(offset)
            return
        if self.uart_active and self.helper <= address < address + size <= self.helper_end:
            self.executed.add(offset)
            return
        if any(lo <= offset < hi for lo, hi in RETIRED_CODE):
            raise ProofError("execution bypassed retired entry into old/relocated interior")
        if self.uart_active and offset in (0x5882, 0x823E):
            calls = self.dispatches if offset == 0x5882 else self.dfu_receives
            calls.append(tuple(uc.reg_read(reg) for reg in self.registers[:2]))
            self._return(0xD00DFEED)  # dispatch / DFU reassembly boundary ONLY
            return
        if self.uart_active and address == 0x5AA8:
            self.logs.append(tuple(uc.reg_read(reg) for reg in self.registers))
            self._return(0xACCE55)
            return
        if self.fast_active and offset == 0x8112:
            self.prelude_boundary.append(tuple(uc.reg_read(reg) for reg in self.registers))
            self._return()  # explicit stateful prelude boundary; NOT no-effect stock proof
            return
        ranges = ((0x657C, 0x66B6), (0x5990, 0x5992), (0x613A, 0x613C))
        if self.uart_active:
            ranges += ((0x7ACE, 0x7B22), (0x79B6, 0x7A0C), (0x5C22, 0x5C32))
        if self.fast_active:
            ranges += ((0x5882, 0x5C22), (0x1A378, 0x1A392))
        if any(lo <= offset < offset + size <= hi for lo, hi in ranges):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def uart(self, opcode, *, dfu=False, mode=0, length=16, pointer=PACKET, attribute=2):
        self.uc.mem_write(PACKET, bytes([opcode]) + bytes(range(1, 16)))
        self.uc.mem_write(0x208C44, bytes([mode]))
        self.uc.mem_write(self.STACK, struct.pack("<4I", length, pointer, 0xFACE1234, 0xABCDEF01))
        before = bytes(self.uc.mem_read(0x2084B0, 0x6284))
        packet_before = bytes(self.uc.mem_read(PACKET, 16))
        self.uart_active = True
        try:
            result = self.call(0x79B6 if dfu else 0x7ACE, pointer, length, attribute, 0x2468)
        finally:
            self.uart_active = False
        assert bytes(self.uc.mem_read(0x2084B0, 0x6284)) == before
        assert bytes(self.uc.mem_read(PACKET, 16)) == packet_before
        if dfu:
            assert not self.dispatches and self.helper - BIAS not in self.executed
        else:
            assert not self.dfu_receives
        return result


class OverlayStock(Overlay, RawStock):
    pass


class OverlayMotion(Overlay, RawMotion):
    pass


class OverlaySchedule(Overlay, RawSchedule):
    pass


def test_old_inspected_layout_cannot_claim_a1_retirement():
    raw = OLD_ELF.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "0d86ddec5c56c28b4d34ab3517c7fea32894ab04d5239a4a3d2b3641f4ee012d"
    with pytest.raises(ValueError, match="exact reviewed conditional ELF"):
        retirement.retirement_plan(STOCK, raw, DESCRIPTOR, policy_source=SOURCE.read_bytes())
    # Run the same bounded helper oracle directly so this historical negative
    # remains meaningful after the current layout inspector's pins advance.
    e = ELFFile(BytesIO(raw))
    symbol = next(s for s in e.get_section_by_name(".symtab").iter_symbols() if s.name == "wlg_receive")
    with pytest.raises(ValueError, match="opcode 0xa1"):
        retirement._policy_witness(STOCK, raw, {"address": symbol["st_value"], "bytes": symbol["st_size"]})


def test_exact_records_policy_and_all_false_permissions(combined):
    raw, plan = combined
    assert plan.policy_cases == 1078 and len(plan.policy_digest) == 64
    assert len(plan.edits) == 16 and sum(len(edit.after) for edit in plan.edits) == 64
    assert {edit.file_offset for edit in plan.edits} == {
        0x1E4A, 0x2104, 0x48C6, 0x4B02, 0x4C36, 0x7B0A,
        0x3AC4, 0x3B1A, 0x3B7A, 0x3C18, 0x3CAC, 0x3CD2,
        0x3D36, 0x3D9E, 0x3DC0, 0x3DC8,
    }
    assert not any((plan.flashable, plan.reference_closure_verified, plan.cold_boot_retention_verified,
                    plan.physical_shutdown_verified, plan.health_continuity_verified, plan.approved_reclaimed_bytes))
    with pytest.raises(ValueError):
        inspect_elf(raw, STOCK, DESCRIPTOR)
    h = OverlayStock(raw, plan)
    actual = bytes(h.uc.mem_read(BIAS, len(STOCK)))
    permitted = {i for lo, hi in h.loads if lo < retirement.layout.APPEND for i in range(lo - BIAS, hi - BIAS)}
    permitted |= {i for edit in plan.edits for i in range(edit.file_offset, edit.file_offset + 4)}
    assert all(a == b or i in permitted for i, (a, b) in enumerate(zip(STOCK, actual, strict=True)))
    for lo, hi in retirement.PRESERVED:
        assert actual[lo:hi] == STOCK[lo:hi]
    assert STOCK_PATH.read_bytes() == STOCK


def test_source_stock_instruction_overlap_and_layout_mutants_refuse(combined, monkeypatch):
    raw, _ = combined
    with pytest.raises(ValueError, match="immutable input bytes"):
        retirement.retirement_plan(STOCK, bytearray(raw), DESCRIPTOR, policy_source=SOURCE.read_bytes())
    with pytest.raises(ValueError, match="policy source"):
        retirement.retirement_plan(STOCK, raw, DESCRIPTOR, policy_source=SOURCE.read_bytes() + b"\n")
    changed = bytearray(STOCK); changed[0x1F48] ^= 1
    with pytest.raises(ValueError):
        retirement.retirement_plan(bytes(changed), raw, DESCRIPTOR, policy_source=SOURCE.read_bytes())
    for entry, reason in (
            ((0x1E4A, "wrong-old", "00000000"), "old bytes"),
            ((0x1E4A, "duplicate", "f0b589b0"), "overlapping retirement records"),
            ((retirement.UART_SITE, "split-BL", retirement.UART_BEFORE.hex()), "wide instruction"),
            ((0x3CA8, "shared-tail", STOCK[0x3CA8:0x3CAC].hex()), "overlaps retained"),
            ((0x1E50, "relocated-text", STOCK[0x1E50:0x1E54].hex()), "overlaps retained")):
        with monkeypatch.context() as m:
            m.setattr(retirement, "ENTRIES", (*retirement.ENTRIES, entry))
            with pytest.raises(ValueError, match=reason):
                retirement.retirement_plan(STOCK, raw, DESCRIPTOR, policy_source=SOURCE.read_bytes())


def test_nonhelper_opcode_drift_cannot_hide_behind_unchanged_geometry(combined):
    raw, _ = combined
    changed = bytearray(raw)
    section = ELFFile(BytesIO(raw)).get_section_by_name(".trial_mode_controller")
    changed[section["sh_offset"]] ^= 1
    # The separate inspector promises geometry/inventory, NOT all-opcode
    # provenance. The fixed artifact pin must independently close this gap.
    retirement.layout.inspect_trial(bytes(changed), STOCK, DESCRIPTOR)
    with pytest.raises(ValueError, match="exact reviewed conditional ELF"):
        retirement.retirement_plan(STOCK, bytes(changed), DESCRIPTOR,
                                   policy_source=SOURCE.read_bytes())


def test_all_fifteen_direct_entries_are_noops_without_fake_timer_cancellation(combined):
    raw, plan = combined
    for offset, _, _ in retirement.ENTRIES:
        for mask in (0, 1):
            h = OverlayStock(raw, plan)
            h.uc.mem_write(RAW_FLAG, b"\x01\x04\x01")
            h.uc.mem_write(RAW_TIMER, struct.pack("<I", MOCK_TIMER))
            h.uc.mem_write(0x209D10, struct.pack("<II", MOCK_TIMER, MOCK_TIMER))
            h.uc.mem_write(0x209D18, struct.pack("<I", 4))
            h.uc.mem_write(0x209D1C, b"\x01")
            h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
            before = h.observations()
            assert h.call(offset, PACKET, 0x55, 0xAA, 0x1234) == 0
            assert [h.uc.reg_read(reg) for reg in h.registers[1:]] == [0x55, 0xAA, 0x1234]
            assert h.observations() == before
            assert h.executed == {offset, offset + 2}
            assert not h.timer_calls and not h.notifications and not h.indicator_requests


def test_actual_uart_filter_and_separate_dfu_route_with_combined_layout(combined):
    raw, plan = combined
    for opcode in (0xA1, 0xBF, 0xCE, 0xCD, 0xA0, 0x9C, 0x51):
        for mode in (0, 1, 255):
            h = OverlayStock(raw, plan)
            assert h.uart(opcode, mode=mode) == 0
            assert h.dispatches == ([] if mode == 1 or opcode in retirement.DENIED else [(PACKET, 16)])
            assert 0x8112 not in h.executed and not h.messages and not h.timer_calls
            dfu = OverlayStock(raw, plan)
            assert dfu.uart(opcode, mode=mode, dfu=True) == 0
            assert dfu.dfu_receives == [(PACKET, 16)]
            assert not dfu.dispatches and not dfu.logs
    for length in (0, 15, 17, 0x10010, 0xFFFFFFFF):
        h = OverlayStock(raw, plan)
        assert h.uart(0xA1, length=length, pointer=0xDEAD0000) == 0
        assert not h.dispatches and not h.dfu_receives


def test_actual_queued_a1_wrap_and_stored_callbacks_hit_stubs(combined):
    h = OverlayStock(*combined)
    queue = 0x209D50
    h.uc.mem_write(queue, struct.pack("<HH", 9, 1))
    for index in (9, 0):
        h.uc.mem_write(queue + 4 + index * 16, b"\xa1\x04" + bytes(14))
    h.uc.mem_write(RAW_FLAG, b"\x01\x04\x01")
    h.uc.mem_write(RAW_TIMER, struct.pack("<I", MOCK_TIMER))
    before_raw = bytes(h.uc.mem_read(RAW_FLAG, 20))
    h.call(0x657C)
    assert struct.unpack("<HH", h.uc.mem_read(queue, 4)) == (1, 1)
    assert {0x657C, 0x6688, 0x2104, 0x2106, 0x66A2}.issubset(h.executed)
    assert h.direct_writes[-2:] == [(0x66A2, queue, 2, 0), (0x66A2, queue, 2, 1)]
    for literal, entry in ((0x239C, 0x1E4A), (0x3DF0, 0x3AC4), (0x3DF8, 0x3B7A)):
        pointer = struct.unpack("<I", h.uc.mem_read(BIAS + literal, 4))[0]
        assert pointer == BIAS + entry + 1
        assert h.call((pointer & ~1) - BIAS, MOCK_TIMER) == 0
    assert bytes(h.uc.mem_read(RAW_FLAG, 20)) == before_raw
    assert not h.notifications and not h.messages and not h.timer_calls and not h.indicator_requests


def test_known_direct_diagnostic_dispatch_calls_hit_stubs_with_prelude_explicit(combined):
    for opcode, site, entry in ((0xBF, 0x5BB6, 0x48C6), (0xCD, 0x5C14, 0x4C36),
                                (0xCE, 0x5C1C, 0x4B02)):
        h = OverlayStock(*combined)
        h.uc.mem_write(PACKET, bytes([opcode]) + bytes(15))
        before = bytes(h.uc.mem_read(0x2084B0, 0x6284))
        h.fast_active = True
        try:
            h.call(0x5882, PACKET)
        finally:
            h.fast_active = False
        assert {0x5882, 0x5890, site, entry, entry + 2}.issubset(h.executed)
        assert len(h.prelude_boundary) == 1
        assert bytes(h.uc.mem_read(0x2084B0, 0x6284)) == before
        assert not h.notifications and not h.messages and not h.timer_calls


def test_old_interior_cannot_masquerade_as_a_relocated_function(combined):
    for offset in (0x1E4E, 0x1E50, 0x1F70, 0x202A, 0x2108, 0x3AC8, 0x3CA8, 0x4B08, 0x4C3C):
        with pytest.raises(ProofError, match="bypassed"):
            OverlayStock(*combined).call(offset)
    h = OverlayStock(*combined)
    h.uc.mem_write(BIAS + 0x1E4A, bytes.fromhex("08607047"))
    with pytest.raises(ProofError, match="unreviewed data write"):
        h.call(0x1E4A, 1, 0x22D000)


def test_restoring_an_entry_or_uart_bl_breaks_known_root_shutdown(combined):
    h = OverlayStock(*combined)
    h.uc.mem_write(BIAS + 0x1E4A, STOCK[0x1E4A:0x1E4E])
    with pytest.raises(ProofError, match="bypassed"):
        h.call(0x1E4A)
    h = OverlayStock(*combined)
    h.uc.mem_write(BIAS + retirement.UART_SITE, retirement.UART_BEFORE)
    assert h.uart(0xA1) == 0
    assert h.dispatches == [(PACKET, 16)]  # independent oracle catches missing early filter
    assert h.helper - BIAS not in h.executed


def test_selected_health_optical_current_schedule_and_a0_keep_stock_behavior(combined):
    for probe_ok in (False, True):
        traces = []
        for h in (RawStock(False), OverlayStock(*combined)):
            h.probe_ok = probe_ok
            h.call(OPTICAL_ENABLE, 0x10)
            assert bool(h.optical_starts) is probe_ok
            h.call(OPTICAL_DISABLE, 0x10)
            expected = bytearray(seed_a0(h))
            # A0's actual F80e -> F7ce path reaches the same named probe
            # fixture used above. The cold seed assumes probe_ok=True.
            expected[3] = 0x21 if probe_ok else 0
            expected[-1] = sum(expected[:-1]) % 256
            h.call(0x1DCA)
            assert h.notifications == [bytes(expected)]
            assert h.transfers == [b"\x7b\xa5", b"\x7b\0"]
            traces.append((h.ownership(), h.optical_state(), h.optical_starts, h.transfers,
                           h.mutex_events, h.notifications, bytes(h.uc.mem_read(0x2084B0, 0x6284))))
        assert traces[0] == traces[1]
    traces = []
    for h in (RawSchedule(False), OverlaySchedule(*combined)):
        h.set_controls(interval=5, enables=0x1F)
        h.tick(3600)
        assert h.messages == [(3, 1, mask) for mask in (0x10, 0x100, 0x200, 0x1000)]
        traces.append((h.messages, h.timer_starts, h.bookkeeping,
                       bytes(h.uc.mem_read(0x2084B0, 0x6284))))
    assert traces[0] == traces[1]


def test_retained_9c_charging_tail_and_idle_mode_veto_match_stock(combined):
    traces = []
    for h in (RawStock(False), OverlayStock(*combined)):
        h.uc.mem_write(PACKET, b"\x9c\0" + bytes(14))
        h.uc.mem_write(RAW_TIMER, struct.pack("<I", MOCK_TIMER))
        h.call(0x1CB4, PACKET)
        assert h.timer_calls == [("stop", RAW_TIMER), ("delete", RAW_TIMER)]
        assert h.notifications == [b"\x9c" + bytes(14) + b"\x9c"]
        h.uc.mem_write(RAW_FLAG, b"\x01")
        h.charging_tail()
        assert bytes(h.uc.mem_read(RAW_FLAG, 1)) == b"\0"
        h.uc.mem_write(RAW_MODE, b"\x04")
        assert h.call(0xA762) == 0
        assert {0x1CD2, 0x3E30, 0x34F6, 0xA762, 0x1E42}.issubset(h.executed)
        traces.append((h.timer_calls, h.notifications, h.extra_calls,
                       bytes(h.uc.mem_read(0x2084B0, 0x6284))))
    assert traces[0] == traces[1]


def test_shared_optical_reader_fifo_and_step_sleep_input_boundary_unchanged(combined):
    traces = []
    for h in (RawMotion(False), OverlayMotion(*combined)):
        samples, count, arrays = optical_window(h)
        assert h.cursor() == (480 + 18) % BUFFER_BYTES and h.cursor(health=True) == 480
        assert h.consume_health() == [(y, x, z) for x, y, z in samples]
        assert h.filtered_magnitudes == [8000, 8022, 8051]
        traces.append((count, arrays, h.health_inputs, h.filtered_magnitudes,
                       bytes(h.uc.mem_read(0x2084B0, 0x6284))))
    assert traces[0] == traces[1]
    mutant = OverlayMotion(*combined)
    mutant.uc.mem_write(BIAS + 0xCC32, retirement.RETURN_ZERO)
    with pytest.raises(AssertionError):
        optical_window(mutant)
