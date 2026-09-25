"""OFFLINE stock callbacks observed at a proposed health-publication boundary.

Unchanged pinned Thumb executes; timer deletion, wear classification and result
aggregation are explicit mocks. The supplied publication predicate may invoke
compiled wh_result_allowed. This is NOT an installed hook, complete inventory,
sensor simulator, persistence proof, or evidence of physical STOP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from whip.fwcontinuity import BIAS, ProofError
from whip.fwhealth_lifecycle import StockLifecycleHarness


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    start: int
    callback: int
    timer: int
    mask: int
    aggregate: int
    value_argument: int = 0


# Exact pinned-stock paths, NOT an exhaustive/approved adapter job inventory.
SCHEDULED_JOBS = (
    ScheduledJob("hr", 0xE420, 0xE384, 0x20C0C4, 0x10, 0xE2E4, 1),
    ScheduledJob("spo2", 0xE168, 0xE104, 0x20C0AC, 0x80, 0xE0C6),
    ScheduledJob("owner_200", 0xE8C2, 0xE856, 0x20C0E8, 0x200, 0xE7BC),
    ScheduledJob("owner_100", 0xEA58, 0xE9E0, 0x20C0F0, 0x100, 0xE948),
    ScheduledJob("owner_1000", 0xECBE, 0xEC54, 0x20C104, 0x1000, 0xEB7C),
)

# All direct BL callers found in the pinned executable scan, each manually
# reviewed. Does NOT rule out indirect calls, ROM producers or other I2C paths.
ENABLE_POST_CALLERS = (
    0x21C4, 0x222A, 0x2290, 0x22B2, 0x45D6, 0x4E72, 0x5368,
    0x53CA, 0x53D8, 0x53EC, 0x540A, 0x5446, 0x5486, 0xA922,
    0xDE96, 0xE198, 0xE458, 0xE556, 0xE8EE, 0xEA84, 0xECEC,
)

CALLBACK_RANGES = (
    (0xE384, 0xE420),  # HR timeout / fallback / aggregate request
    (0xE56C, 0xE596),  # HR reset and cancellation (not timer completion)
    (0xE856, 0xE8C2), (0xE9E0, 0xEA4E), (0xEC54, 0xECB4),
    (0xEC36, 0xEC4C),  # owner_1000 result conversion
    (0xF736, 0xF75C),  # stock optical failure/state/cached-result getters
)


class StockPublicationHarness(StockLifecycleHarness):
    """Publication observer: generated-result taint persists across callbacks.

The original callback ticket MUST be captured in publication_allowed's closure;
the harness never obtains a new ticket to relabel delayed stock work. A true
verified_source_fixture is only a synthetic positive control. Any executed PRNG
call overrides it and permanently marks this one-job harness unmeasured.
"""

    def __init__(self, image: bytes, job: ScheduledJob,
                 publication_allowed: Callable[[bool], bool], *,
                 verified_source_fixture: bool = False):
        if job not in SCHEDULED_JOBS:
            raise ValueError("unreviewed stock callback job")
        self.job = job
        self.publication_allowed = publication_allowed
        self.verified_source_fixture = verified_source_fixture
        self.generated = False
        self.publication_attempts: list[tuple[int, bool, bool]] = []
        self.accepted_results: list[int] = []
        self.wear_fixture = 0
        self.activity_fixture = 0
        super().__init__(image)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if offset == 0x081C:
            self.generated = True
        if offset == self.job.aggregate:
            value = uc.reg_read(self.registers[self.job.value_argument])
            measured = self.verified_source_fixture and not self.generated
            allowed = bool(self.publication_allowed(measured))
            self.publication_attempts.append((value, measured, allowed))
            if allowed:
                self.accepted_results.append(value)
            # Never run the aggregator/NVM write, even in the positive control.
            self._return()
            return
        if offset in {j.aggregate for j in SCHEDULED_JOBS}:
            raise ProofError("unexpected other-job result publication")
        if offset == 0x3E30:
            pointer = uc.reg_read(self.registers[0])
            if pointer != self.job.timer:
                raise ProofError("unexpected other-job timer cancellation")
            self.timer_cancel_requests.append(pointer)
            self._return()
            return
        if offset in (0xB7B0, 0xB5CE):
            if self.job.name != "hr":
                raise ProofError("unexpected HR wear/activity fixture")
            self.mock_calls.append(offset)
            self._return(self.wear_fixture if offset == 0xB7B0 else self.activity_fixture)
            return
        if any(lo <= offset < hi for lo, hi in CALLBACK_RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)


class StockStartHarness(StockLifecycleHarness):
    """Selected real start/cancel paths with explicit settings/timer fixtures.

Only records requested timer ABI and hub posts. A mock timer create/delete
cannot attest a queued callback was drained or that sensor work completed.
"""

    START_RANGES = (
        (0x4E0C, 0x4E9A),  # opcode 0x1e start, timeout, explicit stop
        (0xDE04, 0xDEB4),  # wear/probe start and pointer-writing callback
        (0xE168, 0xE1B2), (0xE420, 0xE47A), (0xE51C, 0xE578),
        (0xE8C2, 0xE916), (0xEA58, 0xEAA6), (0xECBE, 0xED0E),
        (0xE9D0, 0xE9D8), (0xF736, 0xF75C),
    )

    def __init__(self, image: bytes):
        self.timer_starts: list[tuple[int, int, int, int]] = []
        self.realtime_results: list[tuple[int, int]] = []
        self.settings_enabled_fixture = True
        self.wear_fixture = 0
        self.busy_fixture = 0
        super().__init__(image)
        self.uc.mem_write(0x208C44, b"\x03\x00\x01")

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        args = [uc.reg_read(r) for r in self.registers]
        if offset == 0x3E04:
            pointer, callback, period, repeat = args
            known = {(j.timer, BIAS + j.callback + 1, 1000, 1) for j in SCHEDULED_JOBS}
            known |= {(0x209D44, BIAS + 0x4E0C + 1, 1000, 1),
                      (0x20C018, BIAS + 0xDE04 + 1, 2500, 1)}
            if tuple(args) not in known:
                raise ProofError("unreviewed timer start ABI")
            self.timer_starts.append(tuple(args))
            self._return()  # record only, no RTOS timer created
            return
        if offset in (0x1726, 0x176A, 0x1776, 0x1880, 0x189E, 0x2696):
            self.mock_calls.append(offset)
            self._return(self.settings_enabled_fixture)
            return
        if offset in (0xB7B0, 0x2DAE, 0x1A92, 0xA85C):
            self.mock_calls.append(offset)
            self._return({0xB7B0: self.wear_fixture, 0x2DAE: self.busy_fixture,
                          0x1A92: 123456, 0xA85C: 0}[offset])
            return
        if offset == 0x47D6:
            if args[0] != 0x1E:
                raise ProofError("unreviewed realtime result opcode")
            self.realtime_results.append(tuple(args[:2]))
            self._return()
            return
        if offset == 0x3E30 or address == 0x136BC:  # selected ROM os_timer_stop
            if args[0] not in (0x209D44, 0x20C018):
                raise ProofError("unreviewed auxiliary timer cancellation")
            self.timer_cancel_requests.append(args[0])
            self._return()
            return
        if any(lo <= offset < hi for lo, hi in self.START_RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)
