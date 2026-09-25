"""OFFLINE exact-stock optical IRQ/processing witnesses, never device I/O.

Executes posting, hub routing, selected acquisition-status paths and result
stores. GPIO, physical transfers, classification/algorithms, motion assistance,
and notifications are named substitutes. Untagged stock messages do not become
current-generation work because the host happens to dequeue them after resume.
"""
from __future__ import annotations

import struct

from whip.fwcontinuity import BIAS, ProofError
from whip.fwstock_binding import StockBindingHarness

CONTEXT = 0x208550
DRIVER_TABLE = 0x20858C
ALGORITHM_TABLE = 0x20C20C
OPTICAL = 0x20C01C
FLAGS = 0x20C110
SPO2_RESULT = 0x20C0A8
# Synthetic backing memory, NOT allocations or ownership claims on the ring.
BUFFER, STATUS, CALLBACK_TABLE = 0x221000, 0x221800, 0x221900

RANGES = (
    (0xD8F0, 0xD942), (0xD9F8, 0xDA10),  # interrupt and software post
    (0xF774, 0xF7BA),                     # pending flag / processing entry
    (0xF74C, 0xF75C),                     # actual HR cached-result getter
    (0xF308, 0xF350), (0xF35A, 0xF544),  # exclude embedded switch table
    (0xF544, 0xF5C0), (0xF5E0, 0xF71E), # exclude literal pool
    (0x10834, 0x1085A),                   # cached-status short path only
    (0x10F06, 0x10F24), (0x10F56, 0x10F9E), (0x10FAA, 0x10FCA),
    (0x11216, 0x11246),                   # completion clears status bytes
    (0x1A378, 0x1A392),                   # actual Thumb switch helper
    (0xE83C, 0xE844), (0xE9C8, 0xE9D0), (0xEC36, 0xEC4C), (0xED40, 0xED52),
    (0x17D3A, 0x17D56),                  # signed division wrapper
)


class StockOpticalDispatchHarness(StockBindingHarness):
    """Selected stock paths with synthetic old buffers and explicit boundaries.

    An admission predicate is an emulated boundary experiment, not an installed
    hook or producer inventory proof. It must close over an ORIGINAL ticket,
    never acquire a new one at dispatch. No physical sample is claimed here.
    """
    def __init__(self, image, *, admission=None):
        self.admission = admission
        self.admissions = []
        self.gpio_calls = []
        self.boundaries = []
        self.acquisition_statuses = []
        self.result_stores = []
        self.notifications = []
        self.sensor_parse_result = 0
        self.classification_fixture = 2
        self.algorithm_fixture = 72
        self.raw_reporting_fixture = False
        super().__init__(image)
        # Exact stock pointers with deliberately synthetic backing storage.
        self.uc.mem_write(DRIVER_TABLE + 0x10, struct.pack("<I", BUFFER))
        self.uc.mem_write(DRIVER_TABLE + 0x1C, struct.pack("<I", STATUS))
        self.uc.mem_write(ALGORITHM_TABLE + 0x14, struct.pack("<I", CALLBACK_TABLE))
        self.uc.mem_write(CALLBACK_TABLE, bytes(16))  # no indirect algorithm callback
        self.uc.mem_write(CONTEXT + 0xC, struct.pack("<I", BUFFER))
        self.uc.mem_write(BUFFER, bytes(0x500))
        self.uc.mem_write(STATUS, bytes(32))
        self.uc.mem_write(FLAGS, bytes(12))
        self.uc.mem_write(OPTICAL, bytes(16))
        self.uc.mem_write(SPO2_RESULT, bytes(4))
        self.uc.hook_add(self.u.UC_HOOK_MEM_WRITE, self._result_store)

    def arrange(self, *, mode=0, owner=0x10, cached_ready=True, error_bit_set=False):
        if mode not in (0, 1):
            raise ValueError("unreviewed processing mode")
        self.uc.mem_write(CONTEXT + 9, bytes([mode]))
        # This bit causes actual 10f56 to return UINT32_MAX before buffer
        # parsing. Its physical cause is NOT established as an I2C failure.
        self.uc.mem_write(STATUS + 8, bytes([0x10 if error_bit_set else 0]))
        # Mark status already read. The real status helper does NOT read I2C.
        self.uc.mem_write(STATUS + 0x1A, bytes([int(cached_ready), 1]))
        self.set_ownership(owner, 1)

    def _result_store(self, uc, access, address, size, value, opaque):
        destinations = ((OPTICAL + 2, OPTICAL + 3), (OPTICAL + 6, OPTICAL + 8),
                        (OPTICAL + 12, OPTICAL + 13), (SPO2_RESULT, SPO2_RESULT + 1),
                        (0x20C0E4, 0x20C0E5), (0x20C0FB, 0x20C0FC),
                        (0x20C100, 0x20C101), (0x20C10C, 0x20C10E))
        if any(lo <= address and address + size <= hi for lo, hi in destinations):
            self.result_stores.append((uc.reg_read(self.a.UC_ARM_REG_PC) - BIAS,
                                       address, size, value & ((1 << (8 * size)) - 1)))

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        args = tuple(uc.reg_read(r) for r in self.registers)
        if offset == 0xF7A8 and self.admission is not None:
            allowed = bool(self.admission())
            self.admissions.append(allowed)
            if not allowed:
                self._return()
                return
        if offset == 0xF320:
            self.acquisition_statuses.append(args[0])  # actual return from 10f56
        if offset in (0x1399A, 0x1396E, 0x13988, 0x13980):
            self.gpio_calls.append((offset, args[:2]))
            if offset == 0x1399A:
                if args[0] != 0x21: raise ProofError("unexpected optical IRQ pin")
                self._return(0x00200000)  # explicit bit-mask fixture, not MMIO
            else:
                if args[0] != 0x00200000: raise ProofError("unexpected GPIO mask")
                self._return()
            return
        if offset in (0x106E2, 0x1085A, 0xEE50, 0xEFF8, 0xF94E, 0x124D8,
                      0xFBC0, 0xEDDA, 0x1A20C, 0xF0EE):
            self.boundaries.append((offset, args))
            if offset == 0x106E2:
                if args[0] != BUFFER: raise ProofError("unreviewed device parse buffer")
                self._return(self.sensor_parse_result)
            elif offset == 0x1085A:
                if args[0] != CONTEXT: raise ProofError("unreviewed classification context")
                self._return(self.classification_fixture)
            elif offset == 0xEE50:
                # Shared motion assistance is deliberately NOT run or drained.
                self._ram_span(args[0], 2)
                uc.mem_write(args[0], bytes(2))
                self._return()
            elif offset in (0xEFF8, 0xF94E):
                if args[0] != CONTEXT: raise ProofError("unreviewed algorithm context")
                self._return(self.algorithm_fixture)
            elif offset == 0xEDDA:
                if args[0] != 0x40 or args[2] != 24:
                    raise ProofError("unreviewed completion register read")
                self._ram_span(args[1], 24)
                if bytes(uc.mem_read(args[1], 24)) != bytes(24):
                    raise ProofError("completion buffer not cleared")
                self._return()  # read data/completion are not modeled here
            else:
                self._return()
            return
        if offset == 0x6812:
            self.boundaries.append((offset, args))
            self._return(self.raw_reporting_fixture)
            return
        if offset in (0x4766, 0x6828):
            if offset == 0x4766:
                if args[0] != 0xC5 or args[2] != 11:
                    raise ProofError("unreviewed raw result packet")
                self._ram_span(args[1], 11)
                packet = bytes(uc.mem_read(args[1], 11))
            else:
                packet = struct.pack("<III", *args[:3])
            self.notifications.append((offset, packet))
            self._return()
            return
        if any(lo <= offset and offset + size <= hi for lo, hi in RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)
