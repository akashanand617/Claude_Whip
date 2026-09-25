"""Compiled optical work + unchanged stock instructions, never real hardware.

RAM, bus bytes, mutexes and pause/STOP receipts are explicit fixtures. Neither
the in-flight bit nor these tests establishes source provenance or emitter-off.
"""
from io import BytesIO
import struct

import pytest
from elftools.elf.elffile import ELFFile

from tests.test_unified_thumb import elf  # noqa: F401
from tests.test_fwstock_link import linked, STOCK, DESCRIPTOR  # noqa: F401
from whip.fwcontinuity import BIAS, ProofError
from whip.fwoptical_samples import StockOpticalSamplesHarness
from whip.fwoptical_dispatch import BUFFER, STATUS, DRIVER_TABLE
from whip.fwstock_link import inspect_elf

HEALTH, TICKET, HEALTH_BYTES = 0x222000, 0x223000, 168
REJECTED = 0x80000000
BUFFER_BYTES = 0x540  # selected clear's full span, NOT ring allocation approval


class WorkThumb(StockOpticalSamplesHarness):
    def __init__(self, raw, *, actual=False):
        self.functions, self.spans = {}, []
        self.active = None
        self.pause_bytes = None
        self.returned_mask = None
        self.mask_trace, self.guarded_writes = [], []
        super().__init__(STOCK)
        image = ELFFile(BytesIO(raw))
        if actual:
            inspect_elf(raw, STOCK, DESCRIPTOR)
            limits = (0x847AD0, 0x84A000)  # already mapped stock RX region
        else:
            limits = (0x1000000, 0x1010000)
            self.uc.mem_map(limits[0], 0x10000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        for segment in image.iter_segments():
            if segment['p_type'] != 'PT_LOAD' or not segment['p_memsz']: continue
            lo, size = segment['p_vaddr'], segment['p_memsz']
            assert limits[0] <= lo < lo + size <= limits[1]
            assert not segment['p_flags'] & 2 and segment['p_filesz'] == size
            self.uc.mem_write(lo, segment.data())
        for symbol in image.get_section_by_name('.symtab').iter_symbols():
            if symbol['st_info']['type'] != 'STT_FUNC' or not symbol['st_size']: continue
            lo = symbol['st_value'] & ~1
            assert symbol['st_value'] & 1
            assert limits[0] <= lo < lo + symbol['st_size'] <= limits[1]
            self.functions[symbol.name] = symbol['st_value']
            # Only this component, lifecycle predicates and memset support.
            if symbol.name.startswith(('wh_', 'wop_', '__aeabi_mem')) or symbol.name in (
                    'enter', 'leave', 'inventory', 'matching', 'closing', 'drained',
                    'quiet', 'ticket_matches', 'advance'):
                self.spans.append((lo, lo + symbol['st_size']))
        self.uc.hook_add(self.u.UC_HOOK_MEM_WRITE, self._work_write)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ, self._work_read)
        self.invoke('wh_init', 1, 1)
        assert self.invoke('wh_job_begin', 0, TICKET)
        self.original = struct.unpack('<IIB3x', self.uc.mem_read(TICKET, 12))
        self.payloads[0xFF] = b'\x12\x34\xab\xcd' + bytes(124)
        for pointer, size in ((HEALTH, HEALTH_BYTES), (BUFFER, BUFFER_BYTES), (STATUS, 32)):
            self.uc.mem_write(pointer - 8, b'\xa5' * 8)
            self.uc.mem_write(pointer + size, b'\xa5' * 8)

    def _code(self, uc, address, size, opaque):
        mask = uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
        self.stack_low = min(self.stack_low, uc.reg_read(self.a.UC_ARM_REG_SP))
        if self.active:
            self.mask_trace.append((address, mask))
            if address == BIAS + 0x11994:
                assert self.active == 'read' and mask == 0
                assert self.word(28) == 1  # original job remains in flight
                if self.pause_bytes is not None:
                    uc.mem_write(HEALTH, self.pause_bytes)
            if address == BIAS + 0x11A12 and self.returned_mask is not None:
                uc.reg_write(self.a.UC_ARM_REG_PRIMASK, self.returned_mask)
            if address in (0x133F4, 0x1341C) or address in (BIAS + 0x1364A, BIAS + 0x1371E):
                assert self.active == 'read' and mask == 0  # no blocking I/O masked
            if self.active == 'retire' and address != self.STOP and not any(
                    lo <= address < address + size <= hi for lo, hi in self.spans):
                assert any(BIAS + lo <= address < address + size <= BIAS + hi
                           for lo, hi in ((0xFBC0, 0xFC32), (0x113E8, 0x11406)))
                assert mask == 1  # pure bounded stock clear only
        if any(lo <= address < address + size <= hi for lo, hi in self.spans):
            return
        super()._code(uc, address, size, opaque)

    def _work_read(self, uc, access, address, size, value, opaque):
        if self.active and HEALTH <= address < HEALTH + HEALTH_BYTES:
            assert uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == 1

    def _work_write(self, uc, access, address, size, value, opaque):
        if not self.active: return
        spans = ((HEALTH, HEALTH_BYTES), (BUFFER, BUFFER_BYTES), (STATUS, 32))
        if self.active == 'retire':
            assert any(start <= address < address + size <= start + length for start, length in
                       ((BUFFER, BUFFER_BYTES), (STATUS, 32), (self.STACK - 512, 512)))
        for start, length in spans:
            if start - 8 <= address < start + length + 8:
                if not start <= address < address + size <= start + length:
                    raise ProofError('work wrote outside bounded object')
                if start == HEALTH or self.active == 'retire':
                    assert uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == 1
                self.guarded_writes.append((address, size))

    def function(self, name, *args):
        assert len(args) <= 8
        if len(args) > 4:
            self.uc.mem_write(self.STACK, struct.pack('<' + 'I' * (len(args) - 4), *args[4:]))
        return self.call((self.functions[name] & ~1) - BIAS, *args[:4])

    def invoke(self, name, *args):
        return self.function(name, HEALTH, *args)

    def word(self, offset):
        return struct.unpack('<I', self.uc.mem_read(HEALTH + offset, 4))[0]

    def phase(self, phase):
        if phase == 'health': return
        assert self.invoke('wh_begin_quiesce', 1)
        if phase in ('paused', 'resuming', 'ready', 'resumed'):
            assert self.invoke('wh_cancelled', 1, 2, 1)
            assert self.invoke('wh_fenced', 1, 2)
            assert self.invoke('wh_stopped', 1, 2, 1)  # fixture, not physical STOP
        if phase in ('resuming', 'ready', 'resumed'):
            assert self.invoke('wh_begin_resume', 2, 17)
        if phase in ('ready', 'resumed'):
            assert self.invoke('wh_resume_ready', 2, 3, 17, 1, 1)
        if phase == 'resumed':
            assert self.invoke('wh_commit_health', 2, 17)
            assert self.invoke('wh_job_begin', 0, TICKET)
        if phase == 'fault': self.invoke('wh_fail')

    def read(self, *, ticket=None, pointer=HEALTH, buffer=BUFFER, status=STATUS):
        self.active = 'read'
        try:
            return self.function('wop_read', pointer, *(ticket or self.original), buffer, status)
        finally:
            self.active = None

    def retire(self, token=1, *, pointer=HEALTH, buffer=BUFFER, status=STATUS):
        self.active = 'retire'
        try:
            return self.function('wop_retire', pointer, token, buffer, status)
        finally:
            self.active = None


def test_compiled_read_executes_real_stock_reader_without_publishing_health(elf):
    h = WorkThumb(elf)
    assert h.read() == 0
    assert h.transfers == [b'\xfe\x00'] and h.receives == [(0xFF, 4, 0, 4)]
    assert bytes(h.uc.mem_read(BUFFER + 0xA8, 4)) == b'\x34\x12\xcd\xab'
    assert h.word(0) == 0 and h.word(28) == 0
    assert not h.result_stores and not h.notifications
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


@pytest.mark.parametrize('failure', ['tx', 'rx', 'partial_rx', 'mutex'])
def test_transport_failure_is_preserved_and_faults_health_without_fake_stop(elf, failure):
    h = WorkThumb(elf)
    if failure == 'tx': h.transfer_result = 1
    elif failure == 'mutex': h.mutex_available = False
    else: h.read_failures[0] = (1, 2 if failure == 'partial_rx' else 0)
    assert h.read() == 0xFFFFFFFA
    assert h.word(0) == 5 and h.word(28) == 0
    assert h.uc.mem_read(HEALTH + 165, 2) == bytes(2)
    assert h.uc.mem_read(STATUS + 10, 1) == b'\x04'  # no speculative cursor rollback
    before = len(h.transfers)
    assert h.read() == REJECTED and len(h.transfers) == before


@pytest.mark.parametrize('kind', [0x10, 0x30])
def test_stock_positive_incomplete_status_is_not_promoted_to_success(elf, kind):
    h = WorkThumb(elf); h.configure_samples(new=5, sensor_kind=kind)
    assert h.read() == 1
    assert h.word(0) == 5 and h.word(28) == 0
    # 0x10 delivers the complete prefix first; 0x30 returns before I/O.
    assert bool(h.receives) is (kind == 0x10)


def test_invalid_stock_configuration_faults_before_io(elf):
    h = WorkThumb(elf); h.uc.mem_write(BUFFER + 4, b'\0')
    assert h.read() == 0xFFFFFFFF
    assert h.word(0) == 5 and not h.transfers and not h.receives


def test_existing_inflight_read_or_run_is_not_overlapped(elf):
    h = WorkThumb(elf)
    assert h.invoke('wh_run_begin', *h.original)
    assert h.read() == REJECTED and not h.sample_attempts
    assert h.word(28) == 1


def test_ended_job_cannot_reuse_ticket_after_new_serial(elf):
    h = WorkThumb(elf)
    assert h.invoke('wh_job_end', *h.original)
    assert h.invoke('wh_job_begin', 0, TICKET)
    assert h.read() == REJECTED and not h.sample_attempts
    fresh = struct.unpack('<IIB3x', h.uc.mem_read(TICKET, 12))
    assert fresh[0] == h.original[0] and fresh[1] > h.original[1]
    assert h.read(ticket=fresh) == 0


@pytest.mark.parametrize('new,expected', [(0, 0xFFFFFFFE), (1, 0xFFFFFFFD)])
def test_no_data_or_incomplete_group_is_not_new_data_or_a_health_fault(elf, new, expected):
    h = WorkThumb(elf); h.configure_samples(new=new)
    assert h.read() == expected
    assert h.word(0) == 0 and h.word(28) == 0
    assert not h.transfers and not h.receives


@pytest.mark.parametrize('phase', ['quiescing', 'paused', 'resuming', 'ready', 'fault', 'resumed'])
def test_original_work_never_relabels_itself_across_pause_resume(elf, phase):
    h = WorkThumb(elf); h.phase(phase)
    assert h.read() == REJECTED and not h.sample_attempts
    if phase == 'resumed':
        fresh = struct.unpack('<IIB3x', h.uc.mem_read(TICKET, 12))
        assert fresh != h.original and h.read(ticket=fresh) == 0


@pytest.mark.parametrize('ticket', [(0, 1, 0), (2, 1, 0), (1, 0, 0), (1, 2, 0),
                                    (1, 1, 1), (1, 1, 31), (1, 1, 32), (1, 1, 255)])
def test_wrong_ticket_rejects_before_stock_work(elf, ticket):
    h = WorkThumb(elf)
    assert h.read(ticket=ticket) == REJECTED and not h.sample_attempts


def test_inflight_work_blocks_pause_receipts_and_late_completion_is_not_accepted(elf):
    pause = WorkThumb(elf)
    assert pause.invoke('wh_run_begin', *pause.original)
    assert pause.invoke('wh_begin_quiesce', 1)
    assert not pause.invoke('wh_cancelled', 1, 2, 1)
    assert not pause.invoke('wh_fenced', 1, 2)
    assert not pause.invoke('wh_stopped', 1, 2, 1)
    h = WorkThumb(elf)
    h.pause_bytes = bytes(pause.uc.mem_read(HEALTH, HEALTH_BYTES))
    assert h.read() == REJECTED
    assert h.receives and h.word(0) == 1 and h.word(28) == 0
    assert h.invoke('wh_cancelled', 1, 2, 1)
    assert h.invoke('wh_fenced', 1, 2)
    assert h.invoke('wh_stopped', 1, 2, 1)
    assert h.retire() == 1


@pytest.mark.parametrize('operation', ['read', 'retire'])
@pytest.mark.parametrize('reason', ['null_adapter', 'null_buffer', 'null_status', 'wrong_buffer',
                                    'wrong_status', 'masked', 'exception', 'inventory'])
def test_invalid_entry_is_read_only_and_preserves_interrupt_state(elf, operation, reason):
    h = WorkThumb(elf)
    if operation == 'retire': h.phase('paused')
    kwargs = {}
    if reason.startswith('null_'): kwargs[{'null_adapter': 'pointer', 'null_buffer': 'buffer',
                                          'null_status': 'status'}[reason]] = 0
    if reason.startswith('wrong_'): kwargs[reason[6:]] = BUFFER + 4
    mask, ipsr = int(reason == 'masked'), 15 if reason == 'exception' else 0
    if reason == 'inventory': h.uc.mem_write(HEALTH + 164, b'\0')
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, ipsr)
    before = bytes(h.uc.mem_read(HEALTH, HEALTH_BYTES))
    assert getattr(h, operation)(**kwargs) == (REJECTED if operation == 'read' else 0)
    assert not h.sample_attempts and not h.guarded_writes
    assert bytes(h.uc.mem_read(HEALTH, HEALTH_BYTES)) == before
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == mask
    assert h.uc.reg_read(h.a.UC_ARM_REG_IPSR) == ipsr


def test_unexpected_stock_return_mask_faults_without_enabling_interrupts(elf):
    h = WorkThumb(elf); h.returned_mask = 1
    assert h.read() == REJECTED
    assert h.word(0) == 5 and h.word(28) == 0
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 1


@pytest.mark.parametrize('ready', [0, 1, 2])
def test_retirement_matches_stock_clear_for_all_channels_even_when_not_ready(elf, ready):
    h = WorkThumb(elf); h.phase('paused')
    original_buffer = bytes((i * 17 + 23) & 255 for i in range(BUFFER_BYTES))
    original_status = bytearray(range(32)); original_status[26] = ready
    h.uc.mem_write(BUFFER, original_buffer)
    h.uc.mem_write(STATUS, bytes(original_status))
    reference = StockOpticalSamplesHarness(STOCK)
    reference.uc.mem_write(BUFFER, original_buffer)
    reference.uc.mem_write(STATUS, bytes(original_status))
    reference.uc.mem_write(STATUS + 26, b'\x01')
    reference.call(0xFBC0, BUFFER)
    expected = bytes(reference.uc.mem_read(BUFFER, BUFFER_BYTES))
    before_health = bytes(h.uc.mem_read(HEALTH, HEALTH_BYTES))
    assert h.retire() == 1
    assert bytes(h.uc.mem_read(BUFFER, BUFFER_BYTES)) == expected
    assert bytes(h.uc.mem_read(STATUS, 32)) == bytes(original_status[:24]) + bytes(4) + bytes(original_status[28:])
    assert bytes(h.uc.mem_read(HEALTH, HEALTH_BYTES)) == before_health
    assert not h.transfers and not h.receives and not h.mutex_events and not h.allocations
    assert not h.result_stores and not h.notifications
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


@pytest.mark.parametrize('phase', ['health', 'quiescing', 'ready', 'fault', 'resumed'])
def test_retirement_rejects_nonquiet_or_already_prepared_health_state(elf, phase):
    h = WorkThumb(elf); h.phase(phase)
    assert not h.retire(h.word(12)) and not h.guarded_writes


@pytest.mark.parametrize('partial', [False, True])
def test_quiet_resume_can_retire_before_fresh_preparation_without_relabeling_state(elf, partial):
    h = WorkThumb(elf)
    if partial:
        h.phase('quiescing')
        assert h.invoke('wh_begin_resume', 2, 17)
        assert not h.retire(2) and not h.guarded_writes
        assert h.invoke('wh_cancelled', 2, 3, 1)
        assert h.invoke('wh_fenced', 2, 3)
        assert not h.retire(2) and not h.guarded_writes
        assert h.invoke('wh_stopped', 2, 3, 1)  # explicit physical fixture
    else:
        h.phase('resuming')  # carries a prior fully evidenced quiet state
    assert h.word(0) == 3
    before = bytes(h.uc.mem_read(HEALTH, HEALTH_BYTES))
    assert not h.retire(1) and not h.guarded_writes
    assert h.retire(2)
    assert bytes(h.uc.mem_read(HEALTH, HEALTH_BYTES)) == before
    assert h.uc.mem_read(BUFFER + 0xA8, 128) == bytes(128)
    assert h.uc.mem_read(STATUS + 24, 4) == bytes(4)
    assert not h.transfers and not h.receives and not h.mutex_events
    assert not h.allocations and not h.result_stores and not h.notifications
    assert h.invoke('wh_resume_ready', 2, 3, 17, 1, 1)
    h.guarded_writes.clear()
    assert not h.retire(2) and not h.guarded_writes


@pytest.mark.parametrize('token', [0, 2, 0xFFFFFFFF])
def test_retirement_rejects_stale_or_wrong_controller_token(elf, token):
    h = WorkThumb(elf); h.phase('paused')
    assert not h.retire(token) and not h.guarded_writes


def test_actual_address_link_executes_read_and_retirement_with_original_stock(linked):
    h = WorkThumb(linked, actual=True)
    assert h.read() == 0
    h.phase('paused')
    assert h.retire() == 1
    assert h.uc.mem_read(BUFFER + 0xA8, 128) == bytes(128)
    assert h.uc.mem_read(STATUS + 24, 4) == bytes(4)


@pytest.mark.parametrize('operation', ['read', 'retire'])
def test_emulator_only_missing_entry_mask_mutant_is_detected(elf, operation):
    h = WorkThumb(elf)
    if operation == 'retire': h.phase('paused')
    start = h.functions['enter'] & ~1
    end = next(hi for lo, hi in h.spans if lo == start)
    body = bytes(h.uc.mem_read(start, end - start))
    assert body.count(b'\x72\xb6') == 1
    h.uc.mem_write(start + body.index(b'\x72\xb6'), b'\x00\xbf')
    with pytest.raises(AssertionError): getattr(h, operation)()
