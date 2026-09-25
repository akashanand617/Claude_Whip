"""OFFLINE exact-stock optical sample/cursor witnesses; never device access.

Runs selected FIFO-style byte reader, demultiplexing and conditional buffer
clear instructions. Bus bytes/results are explicit fixtures, not a physical
FIFO model. Does not establish sample timing, original job identity, clinical
accuracy or approved RAM/stock hooks.
"""
from __future__ import annotations

from whip.fwcontinuity import BIAS, ProofError
from whip.fwoptical_acquisition import StockOpticalAcquisitionHarness
from whip.fwoptical_dispatch import BUFFER, STATUS

SAMPLE_RANGES = (
    (0x10610, 0x106E2),              # sample acquisition/ready bookkeeping
    (0x11922, 0x11B14), (0x11B18, 0x11C9C),  # exclude embedded literal word
    (0x124C6, 0x124D8),              # two-byte big-endian word + byte cursor
    (0xFBC0, 0xFC32), (0x113E8, 0x11406),  # conditional buffer clear / fill
)


class StockOpticalSamplesHarness(StockOpticalAcquisitionHarness):
    """Unchanged stock sample code, explicit RX/TX/RTOS boundary fixtures.

Defaults select a single enabled optical channel, one word per group. Fixtures
choose the bytes returned by register FF, including wrap cases; there is no
assumed device cursor, acquisition timestamp or physical FIFO overflow model.
"""

    def __init__(self, image):
        self.cursor_writes = []
        self.sample_returns = []
        self.sample_attempts = []
        self.stack_low = self.STACK
        super().__init__(image)
        self.payloads[0xFF] = bytes(128)
        self.configure_samples()
        self.uc.hook_add(self.u.UC_HOOK_MEM_WRITE, self._cursor_write)

    def configure_samples(self, *, old=0, new=4, group=1, sensor_kind=0x10,
                          layout=1, ready=0):
        capacity = 128 if layout == 1 else 96
        if layout not in (0, 1) or sensor_kind not in (0x10, 0x30) or \
                not (0 <= old <= capacity and 0 <= new <= capacity and
                     1 <= group <= 32 and ready in (0, 1, 2)):
            raise ValueError("unreviewed optical sample fixture")
        self.uc.mem_write(BUFFER, bytes([layout, sensor_kind]))
        self.uc.mem_write(BUFFER + 4, bytes([1, group, 1]))
        self.uc.mem_write(BUFFER + 0x9C, b"\x01\x00")  # one enabled channel
        self.uc.mem_write(BUFFER + 0x228, bytes(2))
        self.uc.mem_write(BUFFER + 0x3B4, bytes(4))
        self.uc.mem_write(STATUS + 8, bytes([0, 0, old, new, 0]))
        self.uc.mem_write(STATUS + 0x18, bytes([1, 0, ready, 1]))

    def _cursor_write(self, uc, access, address, size, value, opaque):
        if address == STATUS + 0xA:
            self.cursor_writes.append((uc.reg_read(self.a.UC_ARM_REG_PC) - BIAS,
                                       size, value))

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        r0, r1, r2, _ = [uc.reg_read(r) for r in self.registers]
        self.stack_low = min(self.stack_low, uc.reg_read(self.a.UC_ARM_REG_SP))
        if offset == 0x11994:
            self.sample_attempts.append((r0, r1, r2))
        if offset == 0x11A12:
            self.sample_returns.append(r0)
        if offset == 0xEDDA and r0 == 0xFF:
            if not 0 < r2 <= 128 or len(self.payloads[r0]) < r2:
                raise ProofError("unreviewed optical sample read length")
            self._ram_span(r1, r2)
            self.read_requests.append((r0, r2))
            self.executed.add(offset)
            return  # execute actual read wrapper, bypass parent's metadata bound
        if any(lo <= offset and offset + size <= hi for lo, hi in SAMPLE_RANGES):
            self.executed.add(offset)
            return  # includes actual buffer clear in place of its parent mock
        super()._code(uc, address, size, opaque)

    def call(self, offset, *args, budget=100_000):
        saved = {getattr(self.a, f"UC_ARM_REG_R{i}"): 0xA0000000 + i for i in range(4, 12)}
        for register, value in saved.items():
            self.uc.reg_write(register, value)
        result = super().call(offset, *args, budget=budget)
        if any(self.uc.reg_read(register) != value for register, value in saved.items()):
            raise ProofError("optical sample call corrupted callee-saved register")
        return result

    def read_samples(self):
        return self.call(0x11994, BUFFER, STATUS + 0xA,
                         self.uc.mem_read(STATUS + 0xB, 1)[0])
