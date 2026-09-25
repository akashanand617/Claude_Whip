"""Execute selected *unmodified stock* Thumb routines, with explicit mocks.

This is a bounded data-path proof, NOT an emulator of a ring, RTOS, optics,
step/sleep algorithms or a linked unified image. No BLE or image writing.
Unmapped accesses, unreviewed code and unexpected I2C operations fail closed.
The generous test RAM/stack addresses are NOT allocations for real firmware.
"""
from __future__ import annotations

import hashlib
import struct

from whip.fwunified import STOCK_SHA256

BIAS = 0x825FB0
DRIVER = 0x20BD98
SAMPLES = DRIVER + 0x30
BUFFER = SAMPLES + 12
CAPACITY = 82
BUFFER_BYTES = CAPACITY * 6
RAW_READ = 0xCC32
FIFO_DRAIN = 0xC280
HEALTH_CONSUME = 0xCD60
WAKE = 0xCB5E
HEALTH_FEED = 0x1D9D8
DFU_TIMER = 0x80F8

# Exact pinned-image bounds, not a claim that every path inside is covered.
EXEC_RANGES = (
    (0xC25A, 0xC4FA),  # watchdog + driver FIFO append
    (0xC7D2, 0xC7D4),  # shared pop epilogue
    (0xCB5E, 0xCBB0),  # normal wake (active/timer-already-running case)
    (0xCC32, 0xCCEE),  # raw reader + shared stack epilogue
    (0xCD60, 0xCF3C),  # active health consumer (inactive paths excluded)
    (0x17D56, 0x17E5A),  # actual positive integer division/remainder
    (0x1DAB0, 0x1DB14),  # actual metric getters / idle predicate
    (0xB528, 0xB53E),  # actual activity accumulator
    (0x1EC94, 0x1EC98),  # stock no-op getter
)


class ProofError(RuntimeError):
    """A proof crossed its explicitly supported execution boundary."""


class StockMotionHarness:
    """Selected stock functions, synthetic STK8321 FIFO, observed health input.

    Algorithm feed at 0x1d9d8 and downstream aggregate at 0x1e190 are mocked.
    This verifies sample delivery/order, NOT the resulting step/sleep values.
    Calls are serialized; real RTOS scheduling/interrupt races are not emulated.
    """

    STOP = 0x3FFF0
    STACK = 0x22F000
    OUTPUTS = (0x221020, 0x222020, 0x223020)

    def __init__(self, image: bytes):
        if hashlib.sha256(image).hexdigest() != STOCK_SHA256:
            raise ValueError("continuity proof requires exact pinned stock SHA-256")
        # Optional dependency: normal application imports never require Unicorn.
        import unicorn as u
        from unicorn import arm_const as a

        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, image)
        self.uc.mem_map(0x200000, 0x30000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_write(0x207C00, image[0x20CC8:0x21578])
        self.uc.mem_write(0x2084B0, image[0x21578:0x21A58])
        self.fifo: list[tuple[int, int, int]] = []
        self.health_inputs: list[tuple[int, int, int]] = []
        self.aggregate_calls: list[tuple[int, int]] = []
        self.i2c_calls: list[tuple[int, int]] = []
        self.fifo_status_ok = True
        self.fifo_data_ok = True
        self.last_data_read_ok: bool | None = None
        self.on_publish = None  # test observer, NOT an installed firmware hook
        self.executed: set[int] = set()
        self.returned = False
        self.registers = (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                          a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._publish,
                         begin=SAMPLES + 8, end=SAMPLES + 9)
        # Driver initialized, active, normal timer already running; no wake.
        self.uc.mem_write(DRIVER, bytes([0x23]))
        self.uc.mem_write(SAMPLES, bytes([1, 1, 1, 0, 0, 0, 0, 0]))

    def _return(self, result=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, result & 0xFFFFFFFF)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    @staticmethod
    def _ram_span(address, length):
        if length < 0 or not 0x200000 <= address <= address + length <= 0x230000:
            raise ProofError("mock accessed outside fixture RAM")

    def _publish(self, uc, access, address, size, value, _):
        if address != SAMPLES + 8 or size != 2 or value >= BUFFER_BYTES or value % 6 or \
                uc.reg_read(self.a.UC_ARM_REG_PC) != BIAS + 0xC4E8:
            raise ProofError("unexpected producer cursor store")
        old = self.cursor()
        count = ((value - old) % BUFFER_BYTES) // 6
        if not 1 <= count <= 32 or self.last_data_read_ok is None:
            raise ProofError("producer update lacks a modeled FIFO data read")
        batch = [struct.unpack("<hhh", uc.mem_read(BUFFER + (old + i * 6) % BUFFER_BYTES, 6))
                 for i in range(count)]
        if self.on_publish is not None:
            self.on_publish(batch, self.last_data_read_ok)
        self.last_data_read_ok = None

    def _code(self, uc, address, size, _):
        if address == self.STOP:
            self.returned = True
            uc.emu_stop()
            return
        r0, r1, r2, _ = [uc.reg_read(r) for r in self.registers]
        if address == 0x3F848:  # ROM memcpy: explicit byte semantics
            if r2 > 512:
                raise ProofError("unexpected memcpy length")
            self._ram_span(r0, r2)
            self._ram_span(r1, r2)
            if r2:
                uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
            self._return(r0)
            return
        if address == 0x3F918:  # ROM __rt_memclr_w, length in bytes
            if r1 > 512:
                raise ProofError("unexpected memclr length")
            self._ram_span(r0, r1)
            if r1:
                uc.mem_write(r0, bytes(r1))
            self._return(r0)
            return
        offset = address - BIAS
        if offset == 0xBC6A:
            self._ram_span(r1, r2)
            self.i2c_calls.append((r0, r2))
            if r0 == 0x0C and r2 == 1:
                if not self.fifo_status_ok:
                    self._return(0)
                    return
                uc.mem_write(r1, bytes([min(len(self.fifo), 32)]))
            elif r0 == 0x3F and 0 < r2 <= 192 and r2 % 6 == 0:
                self.last_data_read_ok = self.fifo_data_ok
                if not self.fifo_data_ok:
                    # No bytes transferred. Stock ignores this failure at c39e.
                    self._return(0)
                    return
                count = r2 // 6
                if count > len(self.fifo):
                    raise ProofError("FIFO underflow")
                uc.mem_write(r1, b"".join(struct.pack("<hhh", *v) for v in self.fifo[:count]))
                del self.fifo[:count]
            else:
                raise ProofError(f"unexpected I2C reg={r0:#x}, length={r2}")
            self._return(1)
            return
        if offset == HEALTH_FEED:
            signed = lambda v: (v + 0x80000000) % 0x100000000 - 0x80000000
            self.health_inputs.append(tuple(signed(v) for v in (r0, r1, r2)))
            self._return()
            return
        if offset == 0x1E190:
            self.aggregate_calls.append((r0, r1))
            self._return()
            return
        if offset == 0x2DAE:  # charging predicate, fixture explicitly unplugged
            self._return(0)
            return
        if not any(lo <= offset < hi for lo, hi in EXEC_RANGES):
            raise ProofError(f"unreviewed execution at runtime {address:#x}, file {offset:#x}")
        self.executed.add(offset)

    def call(self, offset: int, *args: int, budget: int = 100_000) -> int:
        if len(args) > 4:
            raise ValueError("at most four register arguments")
        for register, value in zip(self.registers, (*args, 0, 0, 0, 0)):
            self.uc.reg_write(register, value)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, self.STOP | 1)
        self.returned = False
        try:
            self.uc.emu_start((BIAS + offset) | 1, 0xFFFFFFFF, count=budget)
        except self.u.UcError as exc:
            raise ProofError(f"unmapped/invalid stock execution: {exc}") from exc
        if not self.returned:
            raise ProofError("instruction budget exhausted without return")
        if self.uc.reg_read(self.a.UC_ARM_REG_SP) != self.STACK:
            raise ProofError("stack not restored")
        return self.uc.reg_read(self.a.UC_ARM_REG_R0)

    def cursor(self, *, health=False) -> int:
        return int.from_bytes(self.uc.mem_read(SAMPLES + (10 if health else 8), 2), "little")

    def set_cursors(self, producer: int, consumer: int):
        if any(v < 0 or v >= BUFFER_BYTES or v % 6 for v in (producer, consumer)):
            raise ValueError("cursor must name one of the 82 six-byte samples")
        self.uc.mem_write(SAMPLES + 8, struct.pack("<HH", producer, consumer))

    def raw_read(self, count=1) -> tuple[int, list[tuple[int, int, int]]]:
        # Stock count >=82 can alias to empty; don't conceal that with test helpers.
        if not 1 <= count < CAPACITY:
            raise ValueError("supported raw count is 1..81")
        for ptr in self.OUTPUTS:
            self.uc.mem_write(ptr - 16, b"\xA5" * (count * 2 + 32))
        result = self.call(RAW_READ, *self.OUTPUTS, count)
        arrays = []
        for ptr in self.OUTPUTS:
            if bytes(self.uc.mem_read(ptr - 16, 16)) != b"\xA5" * 16 or \
                    bytes(self.uc.mem_read(ptr + count * 2, 16)) != b"\xA5" * 16:
                raise ProofError("raw output buffer overrun")
            arrays.append(struct.unpack("<" + "h" * count, self.uc.mem_read(ptr, count * 2)))
        return result, list(zip(*arrays))

    def consume_health(self) -> list[tuple[int, int, int]]:
        before = len(self.health_inputs)
        self.call(HEALTH_CONSUME)
        return self.health_inputs[before:]
