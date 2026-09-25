"""Actual stock scheduled-job selection with explicitly synthetic time/RTOS.

Unlike the older start harness's boolean settings fixtures, this executes the
five real enable getters/setters and minute dispatcher. It does not emulate
clock hardware, storage, motion/activity bookkeeping or timer scheduling.
Never call the whole minute dispatcher as a production resume shortcut.
"""
from __future__ import annotations

import struct

from whip.fwcontinuity import BIAS
from whip.fwhealth_adapter import StockStartHarness

# Pinned STOCK-only; the original25Hz/V2-family RAM map differs.
HR_INTERVAL = 0x208AAC
ENABLES = 0x208AAD
OPERATING_MODE = 0x208C44
TIME_SET = 0x208C46
PENDING_SECONDS = 0x209CAC
SCHEDULER_SECONDS = 0x208BE4
GETTERS = (0x1726, 0x176A, 0x1776, 0x1880, 0x189E)
SETTERS = (0x1732, 0x174E, 0x1782, 0x188C, 0x18AA)


class StockScheduleHarness(StockStartHarness):
    """Selected unchanged instructions only; no physical continuity claim.

    Stock job starts still post to a mocked queue and timer-create boundary.
    The read clock returns a fixed fixture; scheduler elapsed/pending counters
    are genuine RAM loads/stores. Non-optical minute/hour/day work is recorded
    and intercepted, never mistaken for step/sleep/history preservation.
    """
    RANGES = (
        (0x1202, 0x12D2),
        (0x1726, 0x1794), (0x1880, 0x18BC),
        (0x2696, 0x26A6), (0x17D3A, 0x17D56),
        (0x17E5A, 0x17E5C), (0x17F18, 0x17F22),  # actual divide-zero return
    )
    BOOKKEEPING = (0x3FE4, 0x2ABE, 0x3FAC, 0x3FD6, 0xE4DE,
                   0x373E, 0xB53E, 0x15FA, 0x11C0)

    def __init__(self, image):
        self.bookkeeping = []
        self.clock_calls = []
        self.now_fixture = 3 * 86400
        super().__init__(image)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if offset in (0x1A3C, 0x1A92, 0x24CA):
            # Tick reconciliation, timestamp getter and calendar conversion are
            # explicit substitutes. No RTC/MMIO or calendar code is executed.
            self.clock_calls.append(offset)
            if offset == 0x24CA:
                pointer = uc.reg_read(self.registers[0])
                self._ram_span(pointer, 8)
                uc.mem_write(pointer, bytes(8))  # initialized unused local fixture
            self._return(self.now_fixture if offset == 0x1A92 else 0)
            return
        if offset in self.BOOKKEEPING:
            self.bookkeeping.append((offset, uc.reg_read(self.registers[0])))
            self._return()
            return
        if any(lo <= offset < hi for lo, hi in self.RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def set_controls(self, interval=5, enables=0x1F, mode=3, time_set=1):
        values = (interval, enables, mode, time_set)
        if any(not 0 <= v <= 255 for v in values):
            raise ValueError("control fixtures must be bytes")
        for address, value in zip((HR_INTERVAL, ENABLES, OPERATING_MODE, TIME_SET), values):
            self.uc.mem_write(address, bytes([value]))

    def tick(self, seconds, pending=1):
        """Fixture only: arrange a pending delta ending at scheduler `seconds`."""
        if not 0 <= pending <= seconds <= 0xFFFFFFFF:
            raise ValueError("invalid scheduler fixture")
        self.uc.mem_write(PENDING_SECONDS, struct.pack("<I", pending))
        self.uc.mem_write(SCHEDULER_SECONDS, struct.pack("<I", seconds - pending))
        self.call(0x1202)
