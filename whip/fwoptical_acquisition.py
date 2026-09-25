"""OFFLINE stock optical read/error propagation; no real sensor or provenance.

Extends the selected dispatch witness through the original mutex/RX wrappers,
status reader, metadata parser and short classification path. Only the lowest
receive operation supplies fixture bytes/status. Algorithms and physical/RTOS
boundaries remain substitutes inherited from the dispatch harness.
"""
from __future__ import annotations

import struct

from whip.fwcontinuity import BIAS, ProofError
from whip.fwoptical_dispatch import (
    StockOpticalDispatchHarness, BUFFER, STATUS, DRIVER_TABLE,
)

# Synthetic test allocations; NOT available/owned RAM on the ring.
CHANNELS = (0x221940, 0x221980)
CLASSIFICATION = 0x221A00

ACQUISITION_RANGES = (
    (0xDC3C, 0xDCEA),                    # RX wrapper + shared return + bus read
    (0xEDDA, 0xEE12),                    # optical mutex/read/status wrapper
    (0x106E2, 0x107F2), (0x10818, 0x10834),  # parser, excluding literal island
    (0x1085A, 0x108F4),                  # classification; deeper paths fail closed
    (0x1174C, 0x117C6),                  # three/four-byte status reader
    (0x1181C, 0x11922),                  # metadata read/unpack, no sample freshness
    (0x11F3E, 0x11FCE),                  # channel controls/read-return propagation
    (0x124D8, 0x124DA),                  # real no-op, formerly a named boundary
)


class StockOpticalAcquisitionHarness(StockOpticalDispatchHarness):
    """Actual app read chain with exact bounded synthetic receive transcripts.

`payloads` supplies register bytes. `read_failures` supplies a low-level receive
status and number of prefix bytes delivered on that call (zero-based). A bus
success remains a fixture, not evidence of real acquisition, timing or health.
Wear-classification deeper paths and layout-zero floating conversion are not
admitted. Cached-ready is still an explicitly synthetic predicate.
"""

    def __init__(self, image):
        self.payloads = {
            2: bytes(4), 9: bytes(17), 10: bytes(17),
            0x42: b"\x2a", 0x40: bytes(24), 0x43: b"\x00",
            0x46: b"\x2b", 0x44: b"\x00", 0x47: b"\x00",
        }
        self.read_failures = {}
        self.read_requests = []
        self.receives = []
        self.read_returns = []
        self.parser_returns = []
        self.metadata_returns = []
        self.status_returns = []
        super().__init__(image)
        self.uc.mem_write(DRIVER_TABLE + 0x14, struct.pack("<I", CLASSIFICATION))
        self.uc.mem_write(CLASSIFICATION, bytes(32))
        self.uc.mem_write(DRIVER_TABLE + 0x20, struct.pack("<II", *CHANNELS))
        for pointer in CHANNELS:
            self.uc.mem_write(pointer, bytes(16))
        self.configure_metadata()

    def configure_metadata(self, *, sensor_kind=0x10, parsed=False, status_read=False):
        if sensor_kind not in (0x10, 0x30):
            raise ValueError("unreviewed optical sensor-kind fixture")
        # Layout one avoids unrelated software-floating conversion. This is
        # selected fixture configuration, NOT the ring's measured live layout.
        self.uc.mem_write(BUFFER, bytes([1, sensor_kind]))
        self.uc.mem_write(STATUS + 0x18, bytes([int(parsed)]))
        self.uc.mem_write(STATUS + 0x1B, bytes([int(status_read)]))

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        r0, r1, r2, r3 = [uc.reg_read(r) for r in self.registers]
        if offset == 0xEDDA:
            if r0 not in self.payloads or r2 not in (1, 3, 4, 6, 17, 24):
                raise ProofError("unreviewed optical read request")
            if len(self.payloads[r0]) < r2:
                raise ProofError("short optical fixture payload")
            self._ram_span(r1, r2)
            self.read_requests.append((r0, r2))
        if offset in (0xEE0C, 0xEE10):
            self.read_returns.append(r0)
        if offset == 0x10830:
            self.parser_returns.append(r0)
        if offset == 0x1188C:
            self.metadata_returns.append(r0)
        if offset in (0x1179C, 0x117A2):
            self.status_returns.append(r0)
        if offset == 0x1371E:
            length = struct.unpack("<I", uc.mem_read(uc.reg_read(self.a.UC_ARM_REG_SP), 4))[0]
            if r0 != 0x40015000 or r2 != 1 or not self.read_requests:
                raise ProofError("unreviewed optical receive ABI")
            self._ram_span(r1, 1)
            register = uc.mem_read(r1, 1)[0]
            if (register, length) != self.read_requests[-1]:
                raise ProofError("optical receive does not match read request")
            self._ram_span(r3, length)
            index = len(self.receives)
            result, delivered = self.read_failures.get(index, (0, length))
            if result not in (0, 1, 2, 3) or not 0 <= delivered <= length:
                raise ProofError("invalid optical receive fixture")
            # Real low-level I2C instructions are outside THIS harness. Do not
            # infer byte count/physical completion from result alone.
            if delivered:
                uc.mem_write(r3, self.payloads[register][:delivered])
            self.receives.append((register, length, result, delivered))
            self._return(result)
            return
        if any(lo <= offset and offset + size <= hi for lo, hi in ACQUISITION_RANGES):
            self.executed.add(offset)
            return  # Bypass only the explicitly replaced parent mocks.
        super()._code(uc, address, size, opaque)
