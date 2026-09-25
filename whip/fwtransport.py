"""Pinned stock GATT/queue witnesses with explicit ROM boundaries, OFFLINE only.

No BLE client, image writer, registered service or installable gateway. Executes
original wrappers, callback branches and UART queue instructions. Stack/RTOS
results are fixtures, not transmission, lifetime, credit or callback-drain proof.
"""
from __future__ import annotations

from collections import deque
from io import BytesIO
import struct

from whip.fwcontinuity import BIAS, ProofError, StockMotionHarness

UART_TABLE = 0x1F25C
UART_CALLBACKS = 0x1F304
UART_APP_CB = 0x209E44
SMALL_QUEUE = 0x209E54
LARGE_QUEUE = 0x20A65C
DATA = 0x221000
APP_MESSAGE_QUEUE = 0x220180
APP_EVENT_QUEUE = 0x220184

RANGES = (
    (0x8E8, 0x93C), (0x6F28, 0x6F80), (0x7018, 0x701E), (0x703E, 0x7042),
    (0x71E6, 0x71F6), (0x76B8, 0x76EE), (0x778C, 0x77A8),
    (0x7918, 0x7950), (0x7A2A, 0x7A7C), (0x7AA4, 0x7B7C),
    (0x7D5E, 0x7DA2), (0x7DC4, 0x7F0C), (0x1445C, 0x144A0),
    (0x1580A, 0x15850), (0x1587C, 0x1588A), (0x158EE, 0x15918),
    (0x15948, 0x15956),
)


class StockTransportHarness(StockMotionHarness):
    """Strict reviewed execution ranges; peripheral access remains unmapped.

ROM mocks write only explicit output pointers/queues and snapshot arguments.
No ROM function body or real Bluetooth stack is emulated. A retained pointer or
successful byte result cannot establish its physical lifetime or delivery.
"""

    def __init__(self, image):
        self.image = bytes(image)
        self.stack_calls = []
        self.registrations = []
        self.registration_results = deque()
        self.send_results = deque()
        self.default_send_result = 1
        self.sends = []
        self.messages = []
        self.message_results = deque()
        self.logs = []
        self.delays = []
        self.legacy_receives = []
        self.setup_boundaries = []
        self.shim_functions = {}
        self.shim_spans = []
        super().__init__(image)
        self.uc.mem_write(0x208998, struct.pack('<I', APP_MESSAGE_QUEUE))
        self.uc.mem_write(0x208994, struct.pack('<I', APP_EVENT_QUEUE))
        self.uc.mem_write(0x209E11, bytes([2, 3]))  # connected fixture, conn_id 3
        self.uc.mem_write(0x209E1B, bytes([4]))    # synthetic assigned UART service

    def _read_bytes(self, address, length):
        if length < 0 or length > 2048:
            raise ProofError('unreviewed transport data length')
        if not (0x200000 <= address <= address + length <= 0x230000 or
                BIAS <= address <= address + length <= BIAS + len(self.image)):
            raise ProofError('transport mock read outside explicit RAM/image')
        return bytes(self.uc.mem_read(address, length))

    def _stack(self, count):
        sp = self.uc.reg_read(self.a.UC_ARM_REG_SP)
        return struct.unpack('<' + 'I' * count, self._read_bytes(sp, count * 4))

    def _code(self, uc, address, size, opaque):
        if address == self.STOP:
            self.returned = True
            uc.emu_stop()
            return
        r0, r1, r2, r3 = [uc.reg_read(r) for r in self.registers]
        offset = address - BIAS
        if address == 0x4926:  # SystemCall_Stack: arguments/status only
            self.stack_calls.append((r0, r1, r2, r3))
            if r0 == 0x3102:
                read, write, cccd, result_ptr = self._stack(4)
                database = self._read_bytes(r2, r3)
                self.registrations.append((r2, database, (read, write, cccd)))
                result, service = (self.registration_results.popleft()
                                   if self.registration_results else (1, len(self.registrations) - 1))
                self._ram_span(r1, 1)
                self._ram_span(result_ptr, 1)
                if result == 1: uc.mem_write(r1, bytes([service]))
                uc.mem_write(result_ptr, bytes([result]))
            elif r0 == 0x3108:
                data, length, kind, result_ptr = self._stack(4)
                self.sends.append((r1, r2, r3, self._read_bytes(data, length), kind))
                result = self.send_results.popleft() if self.send_results else self.default_send_result
                self._ram_span(result_ptr, 1)
                uc.mem_write(result_ptr, bytes([result]))
            elif r0 not in (0x3100, 0x3104, 0x3200):
                raise ProofError(f'unreviewed stack service {r0:#x}')
            self._return(0xD00DFEED)  # wrappers must use the pointed status, not this
            return
        if address == 0x5AA8:  # ROM logging, no formatted-data or I/O execution
            self.logs.append((r0, r1, r2, r3))
            self._return()
            return
        if address == 0x12ED6:  # actual application helper uses two queue posts
            if r0 not in (APP_MESSAGE_QUEUE, APP_EVENT_QUEUE) or r2 != 0:
                raise ProofError('unexpected application queue ABI')
            message = self._read_bytes(r1, 8 if r0 == APP_MESSAGE_QUEUE else 1)
            accepted = self.message_results.popleft() if self.message_results else True
            self.messages.append((r0, message, accepted))
            self._return(int(accepted))
            return
        if address == 0x13146:
            if r0 != 20: raise ProofError('unexpected queue retry delay')
            self.delays.append(r0)
            self._return()
            return
        if address == 0x3F848:  # ROM memcpy byte semantics, not transport ownership
            data = self._read_bytes(r1, r2)
            self._ram_span(r0, r2)
            if data: uc.mem_write(r0, data)
            self._return(r0)
            return
        if offset in (0x1484A, 0x7F10):
            # Setup-only client registration and TX allocation are boundaries.
            self.setup_boundaries.append((offset, r0, r1))
            self._return(9 if offset == 0x1484A else 0)
            return
        if offset == 0x5C22:
            self.legacy_receives.append((r0, r1, self._read_bytes(r0, min(r1, 20))))
            self._return()
            return
        if any(lo <= address and address + size <= hi for lo, hi in self.shim_spans):
            return
        if not any(lo <= offset and offset + size <= hi for lo, hi in RANGES):
            raise ProofError(f'unreviewed transport execution at {address:#x}, file {offset:#x}')
        self.executed.add(offset)

    def call(self, offset, *args, budget=100_000):
        if len(args) > 8: raise ValueError('at most eight ARM argument words')
        for register, value in zip(self.registers, (*args, 0, 0, 0, 0)):
            self.uc.reg_write(register, value)
        saved = [getattr(self.a, f'UC_ARM_REG_R{i}') for i in range(4, 12)]
        for i, reg in enumerate(saved): self.uc.reg_write(reg, 0xABCDE000 + i)
        self.uc.mem_write(self.STACK - 1024, b'\xa5' * 1056)
        if len(args) > 4:
            self.uc.mem_write(self.STACK, struct.pack('<' + 'I' * (len(args) - 4), *args[4:]))
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, self.STOP | 1)
        self.returned = False
        try:
            self.uc.emu_start((BIAS + offset) | 1, 0xFFFFFFFF, count=budget)
        except self.u.UcError as exc:
            raise ProofError(f'invalid/unmapped transport execution: {exc}') from exc
        if not self.returned: raise ProofError('transport instruction budget exhausted')
        if self.uc.reg_read(self.a.UC_ARM_REG_SP) != self.STACK:
            raise ProofError('transport ABI failed to restore stack')
        if any(self.uc.reg_read(reg) != 0xABCDE000 + i for i, reg in enumerate(saved)):
            raise ProofError('transport ABI changed callee-saved register')
        if bytes(self.uc.mem_read(self.STACK - 1024, 16)) != b'\xa5' * 16:
            raise ProofError('transport stack canary changed')
        return self.uc.reg_read(self.a.UC_ARM_REG_R0)

    def queue_cursors(self):
        return struct.unpack('<HH', self.uc.mem_read(SMALL_QUEUE + 2, 4))

    def load_shim(self, data):
        """Admit ONLY the two compiled shim functions, not the entire test ELF."""
        from elftools.elf.elffile import ELFFile
        elf = ELFFile(BytesIO(data))
        if (elf.elfclass, elf.little_endian, elf['e_machine'], elf['e_type']) != (32, True, 'EM_ARM', 'ET_EXEC'):
            raise ValueError('ARM32 little-endian executable required')
        if self.shim_spans: raise ValueError('shim already loaded')
        self.uc.mem_map(0x01000000, 0x10000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        loaded = []
        for segment in elf.iter_segments():
            if segment['p_type'] != 'PT_LOAD': continue
            start, length = segment['p_vaddr'], segment['p_memsz']
            if segment['p_flags'] & 2 or not 0x01000000 <= start <= start + length <= 0x0100F000:
                raise ValueError('unexpected writable/out-of-region test segment')
            self.uc.mem_write(start, segment.data())
            loaded.append((start, start + length))
        symbols = elf.get_section_by_name('.symtab')
        if not symbols: raise ValueError('symbols required')
        entry = None
        for symbol in symbols.iter_symbols():
            if symbol.name and symbol['st_shndx'] == 'SHN_UNDEF': raise ValueError('unresolved symbol')
            if symbol.name == 'wr_init': entry = symbol['st_value']
            if symbol.name not in ('wg_stock_add', 'wg_stock_notify20'): continue
            start, length = symbol['st_value'] & ~1, symbol['st_size']
            if not symbol['st_value'] & 1 or not length or not any(lo <= start < start + length <= hi for lo, hi in loaded):
                raise ValueError('shim function outside loaded Thumb spans')
            self.shim_functions[symbol.name] = symbol['st_value']
            self.shim_spans.append((start, start + length))
        if len(self.shim_functions) != 2 or elf['e_entry'] != entry:
            raise ValueError('unexpected guarded ELF entry/shim set')

    def call_shim(self, name, *args):
        if name not in self.shim_functions: raise ValueError('unknown shim')
        return self.call((self.shim_functions[name] & ~1) - BIAS, *args)
