"""Heap-free sample I/O executed through two emulator-only stock BL edits."""
from io import BytesIO
import struct

import pytest
from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError

from tests.test_fwstock_link import linked, STOCK, DESCRIPTOR  # noqa: F401
from tests.test_stock_optical_work import WorkThumb, BUFFER, STATUS, HEALTH
from whip.fwcontinuity import BIAS, ProofError
from whip.fwoptical_io import sample_io_plan, sample_io_report, SITES, SIGNATURE, CallEdit, _bl
from whip.fwstock_binding import MUTEX_SLOT

DESTINATION = 0x224000  # fixture only, not approved ring RAM


class IOThumb(WorkThumb):
    def __init__(self, raw, *, actual=True):
        self.io_calls = []
        self.release_results, self.take_results = {}, {}
        self.gives, self.takes = 0, 0
        super().__init__(raw, actual=actual)
        image = ELFFile(BytesIO(raw))
        entry = next(s for s in image.get_section_by_name('.symtab').iter_symbols()
                     if s.name == 'woi_samples_io')
        lo = entry['st_value'] & ~1
        self.spans.append((lo, lo + entry['st_size']))
        if actual:
            self.plan = sample_io_plan(STOCK, raw, DESCRIPTOR)
        else:
            # EMULATOR ONLY: a coordinator prototype can exceed configured APP
            # capacity. WorkThumb restricts every segment/function to the
            # artificial 0x01000000 range. The production plan MUST reject it;
            # only these two known instruction sites change in emulator RAM.
            with pytest.raises(ValueError):
                sample_io_plan(STOCK, raw, DESCRIPTOR)
            assert STOCK[0x11A76:0x11A9A] == SIGNATURE
            target = entry['st_value']
            self.plan = tuple(CallEdit(site, before, _bl(BIAS + site, target), target)
                              for site, before in SITES)
        for edit in self.plan:
            assert bytes(self.uc.mem_read(BIAS + edit.file_offset, 4)) == edit.before
            self.uc.mem_write(BIAS + edit.file_offset, edit.after)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        r0, r1, r2, r3 = [uc.reg_read(r) for r in self.registers]
        if address == (self.functions.get('woi_samples_io', 0) & ~1):
            self.io_calls.append((r0, r1, r2))
        if address in (0x12C30, 0x12D4C) or offset in (0xEE12, 0xEDDA, 0xDBCA, 0xDCCE, 0xDAF0):
            raise ProofError('sample binding reached heap/old wrapper/recovery')
        if address in (0x133F4, 0x1341C):
            assert uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == 0
            assert uc.reg_read(self.a.UC_ARM_REG_IPSR) == 0
            if address == 0x133F4:
                self.mutex_available = self.take_results.get(self.takes, True)
                self.takes += 1
            else:
                self.mutex_give_ok = self.release_results.get(self.gives, True)
                self.gives += 1
        if offset == 0xDC40:
            count = struct.unpack('<I', uc.mem_read(uc.reg_read(self.a.UC_ARM_REG_SP), 4))[0]
            assert r0 == 0x33 and r2 == 1 and 0 < count <= 128
            assert uc.mem_read(r1, 1) == b'\xff'
            self._ram_span(r3, count)
            self.read_requests.append((0xFF, count))
        super()._code(uc, address, size, opaque)

    def io(self, reg, count, pointer=DESTINATION):
        return self.function('woi_samples_io', reg, pointer, count)


def test_fixed_call_plan_executes_new_c_through_original_stock_reader(linked):
    h = IOThumb(linked)
    assert tuple(e.file_offset for e in h.plan) == (0x11A80, 0x11A92)
    assert all(len(e.before) == len(e.after) == 4 for e in h.plan)
    assert h.read() == 0
    assert [(reg, count) for reg, _, count in h.io_calls] == [(0xFE, 1), (0xFF, 4)]
    assert h.transfers == [b'\xfe\x00'] and h.receives == [(0xFF, 4, 0, 4)]
    assert h.mutex_events == ['take', 'give', 'take', 'give']
    assert not h.allocations and not h.freed and not h.notifications
    assert h.word(0) == h.word(28) == 0
    baseline = WorkThumb(linked, actual=True); assert baseline.read() == 0
    assert bytes(h.uc.mem_read(BUFFER, 0x540)) == bytes(baseline.uc.mem_read(BUFFER, 0x540))
    assert bytes(h.uc.mem_read(STATUS, 32)) == bytes(baseline.uc.mem_read(STATUS, 32))


@pytest.mark.parametrize('phase', [0, 1])
def test_release_failure_reaches_lifecycle_fault_instead_of_stock_success(linked, phase):
    h = IOThumb(linked); h.release_results[phase] = False
    assert h.read() == 0xFFFFFFFA
    assert h.word(0) == 5 and h.word(28) == 0
    assert h.gives == h.takes == phase + 1
    assert len(h.receives) == phase
    assert h.uc.mem_read(STATUS + 10, 1) == b'\x04'
    assert h.uc.mem_read(BUFFER + 0xA6, 1) == b'\0'
    count = len(h.io_calls)
    assert h.read() == 0x80000000 and len(h.io_calls) == count
    # The original wrapper ignores this same release failure.
    legacy = WorkThumb(linked, actual=True); legacy.mutex_give_ok = False
    assert legacy.read() == 0 and legacy.word(0) == 0


@pytest.mark.parametrize('phase', [0, 1])
def test_mutex_take_failure_does_not_release_unowned_mutex(linked, phase):
    h = IOThumb(linked); h.take_results[phase] = False
    assert h.read() == 0xFFFFFFFA and h.word(0) == 5
    assert h.takes == phase + 1 and h.gives == phase
    assert not h.receives


@pytest.mark.parametrize('result', [1, 2, 3])
@pytest.mark.parametrize('direction', ['tx', 'rx'])
def test_bus_errors_release_once_and_preserve_failure_to_guarded_read(linked, result, direction):
    h = IOThumb(linked)
    if direction == 'tx': h.transfer_result = result
    else: h.read_failures[0] = (result, 2)
    assert h.read() == 0xFFFFFFFA and h.word(0) == 5 and h.word(28) == 0
    assert h.gives == h.takes == (1 if direction == 'tx' else 2)
    assert h.uc.mem_read(BUFFER + 0xA6, 1) == b'\0'
    assert not h.allocations


@pytest.mark.parametrize('reg,count,pointer', [(0, 1, DESTINATION), (0xFD, 1, DESTINATION),
    (0x100, 1, DESTINATION), (0xFE, 0, DESTINATION), (0xFE, 2, DESTINATION),
    (0xFF, 0, DESTINATION), (0xFF, 129, DESTINATION), (0xFF, 0xFFFFFFFF, DESTINATION),
    (0xFF, 4, 0), (0xFE, 1, 0)])
def test_only_fixed_sample_operations_and_bounded_lengths_are_admitted(linked, reg, count, pointer):
    h = IOThumb(linked)
    assert h.io(reg, count, pointer) == 0xFFFFFFFF
    assert not h.mutex_events and not h.transfers and not h.receives


@pytest.mark.parametrize('mask,ipsr', [(1, 0), (0, 2), (0, 3), (0, 15), (0, 16), (1, 15)])
def test_blocking_bus_is_never_entered_in_exception_or_masked_context(linked, mask, ipsr):
    h = IOThumb(linked)
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, ipsr)
    assert h.io(0xFF, 4) == 0xFFFFFFFF and not h.mutex_events
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == mask
    assert h.uc.reg_read(h.a.UC_ARM_REG_IPSR) == ipsr


@pytest.mark.parametrize('reg,count', [(0xFE, 1), (0xFF, 1), (0xFF, 4), (0xFF, 127), (0xFF, 128)])
def test_direct_buffer_bounds_and_no_heap_for_valid_operations(linked, reg, count):
    h = IOThumb(linked)
    h.uc.mem_write(DESTINATION - 8, b'\xa5' * (count + 16))
    h.uc.mem_write(DESTINATION, b'\x7f' + bytes(count - 1))
    assert h.io(reg, count) == 0
    assert h.uc.mem_read(DESTINATION - 8, 8) == b'\xa5' * 8
    assert h.uc.mem_read(DESTINATION + count, 8) == b'\xa5' * 8
    assert h.mutex_events == ['take', 'give']
    if reg == 0xFE:
        assert h.transfers == [b'\xfe\x7f'] and h.uc.mem_read(DESTINATION, 1) == b'\x7f'
    else:
        assert bytes(h.uc.mem_read(DESTINATION, count)) == h.payloads[0xFF][:count]


def test_null_mutex_fails_before_rom_call(linked):
    h = IOThumb(linked); h.uc.mem_write(MUTEX_SLOT, bytes(4))
    assert h.io(0xFF, 4) == 0xFFFFFFFF and not h.mutex_events


def test_failed_allocator_is_not_reached_by_the_new_binding(linked):
    h = IOThumb(linked); h.allocate_ok = False
    assert h.read() == 0 and not h.allocations


@pytest.mark.parametrize('reg,count', [(0xFE, 1), (0xFF, 4)])
@pytest.mark.parametrize('failure', ['not_ready', 'busy'])
def test_bus_readiness_failure_releases_without_automatic_recovery(linked, reg, count, failure):
    h = IOThumb(linked)
    if failure == 'not_ready': h.bus_ready = False
    else: h.bus_busy = True
    assert h.io(reg, count) == 0xFFFFFFFF
    assert h.mutex_events == ['take', 'give'] and h.delay_calls
    assert not h.transfers and not h.receives and not h.allocations


def test_pause_during_checked_io_rejects_late_zero_and_keeps_original_ticket(linked):
    h = IOThumb(linked); pause = IOThumb(linked)
    assert pause.invoke('wh_run_begin', *pause.original)
    assert pause.invoke('wh_begin_quiesce', 1)
    h.pause_bytes = bytes(pause.uc.mem_read(HEALTH, 168))
    assert h.read() == 0x80000000 and h.word(0) == 1 and h.word(28) == 0
    assert not h.allocations and len(h.receives) == 1


def test_encoding_reproduces_both_known_stock_calls_and_never_changes_disk_image(linked):
    for (site, original), destination in zip(SITES, (0xEE12, 0xEDDA), strict=True):
        assert _bl(BIAS + site, (BIAS + destination) | 1) == original
    h = IOThumb(linked)
    for edit in h.plan:
        assert STOCK[edit.file_offset:edit.file_offset + 4] == edit.before
        assert bytes(h.uc.mem_read(BIAS + edit.file_offset, 4)) == edit.after
    allowed = {site + i for site, _ in SITES for i in range(4)}
    actual = bytes(h.uc.mem_read(BIAS + 0x450, len(STOCK) - 0x450))
    assert {i + 0x450 for i, (a, b) in enumerate(zip(actual, STOCK[0x450:], strict=True))
            if a != b}.issubset(allowed)


def test_saved_plan_is_bound_to_inputs_and_never_claims_an_installed_image(linked):
    import hashlib
    report = sample_io_report(STOCK, linked, DESCRIPTOR)
    assert report['replacement_instruction_bytes'] == 8 and len(report['edits']) == 2
    assert report['component_elf_sha256'] == hashlib.sha256(linked).hexdigest()
    assert report['stock_sha256'] == hashlib.sha256(STOCK).hexdigest()
    assert not any(report[k] for k in ('stock_file_modified', 'stock_hooks_attached', 'flashable'))


@pytest.mark.parametrize('bad', ['stock', 'descriptor', 'elf'])
def test_plan_rejects_wrong_inputs(linked, bad):
    stock, descriptor, elf = STOCK, DESCRIPTOR, linked
    if bad == 'stock': stock += b'\0'
    elif bad == 'descriptor': descriptor += b'\n'
    else: elf = b'wrong'
    with pytest.raises((ValueError, ELFError)):
        sample_io_plan(stock, elf, descriptor)


@pytest.mark.parametrize('source,target', [(1, 3), (0, 2), (0, 0x1000005), (0x2000000, 1)])
def test_branch_encoder_rejects_alignment_and_range_errors(source, target):
    with pytest.raises(ValueError): _bl(source, target)
