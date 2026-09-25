"""Bounded stock lifecycle witnesses, not a sensor/RTOS or full-health emulator.

Runs pinned stock Thumb for STK configuration, optical ownership, STOP writes
and hub-message posting. Optical probe/start/algorithm-reset and all physical
I2C are explicit mocks. Inherits the strict stock identity/memory guards of the
motion harness; adds no live-device dependency, patcher or deployment path.
"""
from __future__ import annotations

import struct
from collections import deque

from whip.fwcontinuity import BIAS, HEALTH_FEED, ProofError, StockMotionHarness

OPTICAL = 0x20C01C
OPTICAL_CONFIG = 0x20854C
OPTICAL_ABSENT = 0x20C00C
HUB_QUEUE_SLOT = 0x208CA8
MOCK_QUEUE_HANDLE = 0x220100  # Fixture RAM only; NOT a firmware allocation.
STK_ACTIVE_CONFIG = 0xBF34
STK_IDLE_CONFIG = 0xBEBA
OPTICAL_ENABLE = 0xF824
OPTICAL_DISABLE = 0xF8DA
OPTICAL_CONTROL = 0x12496
POST_ENABLE = 0xDD04
POST_DISABLE = 0xDCEA
SPO2_CALLBACK = 0xE104
SPO2_RESULT = 0x20C0A8

LIFECYCLE_RANGES = (
    (0x14BC, 0x14DE),  # queue send wrapper
    (0xBEBA, 0xBF50),  # STK idle / active register configuration
    (0xDCEA, 0xDD1E),  # optical post wrappers, not hub execution
    (0xE094, 0xE0C0),  # SpO2 result setter / fallback
    (0xE104, 0xE160),  # SpO2 reporting callback / timeout
    (0xF824, 0xF92E),  # optical ownership enable/disable
    (0x10EAA, 0x10EBC),  # full optical stop: RESET, STOP, return zero
    (0x12496, 0x124C6),  # optical register 0x7b control writes
)


class StockLifecycleHarness(StockMotionHarness):
    """Controlled peripheral failures and queued intent, never physical state.

    A successful mocked start records a mode but executes neither optical
    configuration nor sensor hardware. Queue acceptance does not run the hub;
    callers must not interpret these tests as asynchronous completion evidence.
    """

    def __init__(self, image: bytes):
        self.stk_writes: list[tuple[int, int]] = []
        self.stk_failed_registers: set[int] = set()
        self.optical_writes: list[tuple[int, bytes]] = []
        self.optical_write_ok = True
        self.optical_starts: list[tuple[int, int]] = []
        self.mock_calls: list[int] = []
        self.probe_ok = True
        self.queue_accepts = True
        self.messages: list[tuple[int, int, int]] = []
        self.post_attempts: list[tuple[int, int, int]] = []
        self.prng_values: deque[int] = deque()
        self.spo2_aggregate_inputs: list[int] = []
        self.timer_cancel_requests: list[int] = []
        super().__init__(image)
        self.uc.mem_write(HUB_QUEUE_SLOT, struct.pack("<I", MOCK_QUEUE_HANDLE))

    def _code(self, uc, address, size, opaque):
        r0, r1, r2, _ = [uc.reg_read(r) for r in self.registers]
        offset = address - BIAS
        if offset == 0x081C:
            # Explicit PRNG outputs, not sensor values. Fail if the selected
            # callback unexpectedly asks for more entropy than the fixture.
            if not self.prng_values:
                raise ProofError("unexpected stock PRNG call")
            result = self.prng_values.popleft()
            if not 0 <= result <= 0x7FFFFFFF:
                raise ProofError("fixture PRNG value outside stock result range")
            self._return(result)
            return
        if offset == 0xE0C6:  # result aggregation boundary; no persistence claim
            self.spo2_aggregate_inputs.append(r0)
            self._return()
            return
        if offset == 0x3E30:
            # Only selected SpO2 callback's timer cancellation is modeled.
            if r0 != SPO2_RESULT + 4:
                raise ProofError("unreviewed timer cancellation")
            self.timer_cancel_requests.append(r0)
            self._return()
            return
        if offset == 0xBC9E:  # STK write helper, single register / byte
            if not 0 <= r0 <= 0xFF or not 0 <= r1 <= 0xFF:
                raise ProofError("invalid STK register write")
            self.stk_writes.append((r0, r1))
            self._return(r0 not in self.stk_failed_registers)
            return
        if offset == 0xEE12:  # optical write helper, reviewed control register only
            if r0 != 0x7B or r2 != 1:
                raise ProofError("unreviewed optical I2C operation")
            self._ram_span(r1, r2)
            self.optical_writes.append((r0, bytes(uc.mem_read(r1, r2))))
            # Unlike the STK helper, EE12 uses zero-success / UINT32_MAX-error.
            # Workflow3 executes the real wrapper/bus-error path independently.
            self._return(0 if self.optical_write_ok else 0xFFFFFFFF)
            return
        if offset in (0x3CAC, 0x191BC, 0x14904):
            # Indicator cancellation and optical algorithm initialization are
            # MOCK BOUNDARIES; this deliberately does not prove their effects.
            self.mock_calls.append(offset)
            self._return()
            return
        if offset == 0xF7CE:  # fixture chip-ID probe, not actual I2C validation
            self.mock_calls.append(offset)
            self._return(self.probe_ok)
            return
        if offset == 0xF128:  # observed normal-start request, not hardware RUN
            if r0 != OPTICAL_CONFIG:
                raise ProofError("unreviewed optical config pointer")
            rate, mode = struct.unpack("<HB", uc.mem_read(r0, 3))
            self.optical_starts.append((rate, mode))
            self._return()
            return
        if address == 0x12ED6:  # ROM os_msg_send_intern
            if r0 != MOCK_QUEUE_HANDLE or r2 != 0:
                raise ProofError("unreviewed queue target or blocking send")
            self._ram_span(r1, 8)
            message = struct.unpack("<HHI", uc.mem_read(r1, 8))
            self.post_attempts.append(message)
            if self.queue_accepts:
                self.messages.append(message)
            self._return(self.queue_accepts)
            return
        if any(lo <= offset < hi for lo, hi in LIFECYCLE_RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def set_ownership(self, mask: int, state: int = 1):
        if not 0 <= mask <= 0xFFFF or not 0 <= state <= 3:
            raise ValueError("invalid optical mask/state")
        self.uc.mem_write(OPTICAL, struct.pack("<H", mask))
        self.uc.mem_write(OPTICAL + 4, bytes([state]))

    def ownership(self) -> int:
        return int.from_bytes(self.uc.mem_read(OPTICAL, 2), "little")

    def optical_state(self) -> int:
        return self.uc.mem_read(OPTICAL + 4, 1)[0]


class StockFeedHarness(StockMotionHarness):
    """Real per-sample scaling/smoothing; downstream step algorithm is MOCKED.

    Does not extend the parent harness globally: tests must explicitly select
    this class. This establishes call count and front-end arithmetic only.
    """

    FEED_RANGES = (
        (0x1D4CC, 0x1D4F2),  # stock integer square root
        (0x1D9D8, 0x1DAA4),  # per-input magnitude and two-sample axis mean
        (0x17D3A, 0x17D56),  # signed division wrapper
        (0x1DD54, 0x1DD68),  # clamped candidate-count parameter setter
    )

    def __init__(self, image: bytes):
        self.filtered_magnitudes: list[int] = []
        super().__init__(image)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if offset == HEALTH_FEED:
            values = [uc.reg_read(r) for r in self.registers[:3]]
            self.health_inputs.append(tuple((v + 0x80000000) % 0x100000000 - 0x80000000
                                            for v in values))
        if offset == 0x1DB40:
            self.filtered_magnitudes.append(uc.reg_read(self.registers[0]))
            self._return()
            return
        if any(lo <= offset < hi for lo, hi in self.FEED_RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)
