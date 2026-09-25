"""Pinned-stock indicator retirement evidence; NOT an image builder.

Only the emulator experiment replaces entries. No stock file, OTA checksum,
linker reservation or production capability is changed. Candidate scans are
not a proof that computed, indirect or external references cannot exist.
"""
from __future__ import annotations

import hashlib
import struct

from whip.fwcontinuity import BIAS
from whip.fwlayout import overlays
from whip.fwunified import STOCK_SHA256

# File offsets in the exact stock application, never the installed V2 image.
BEGIN, END = 0x3AC4, 0x3DE8
POOL_END = 0x3DFC
ENTRIES = (
    (0x3AC4, "brightness_callback", "10b5c948"),
    (0x3B1A, "apply_brightness", "10b50446"),
    (0x3B7A, "pattern_callback", "70b59a4c"),
    (0x3C18, "request_pattern", "ffb581b0"),
    (0x3CAC, "cancel_indicators", "70b54e4d"),
    (0x3CD2, "request_custom_pattern", "ffb54448"),
    (0x3D36, "request_timed_pattern", "f8b51546"),
    (0x3D9E, "request_with_brightness", "10b51446"),
    (0x3DC0, "indicator_active", "09481030"),
    (0x3DC8, "cancel_pattern", "10b5074c"),
)
RETURN_ZERO = bytes.fromhex("00207047")  # movs r0,#0; bx lr (flags are caller-clobbered)


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def branch_candidate(data: bytes, offset: int, address: int):
    """Decode immediate B/Bcc/BL only, without asserting an instruction boundary.

    This conservative halfword scan intentionally includes data/second halves.
    It neither follows BX/BLX registers nor treats their absence as closure.
    """
    first = struct.unpack_from("<H", data, offset)[0]
    if first & 0xF800 == 0xE000:
        return "b", address + 4 + _signed((first & 0x7FF) << 1, 12)
    if first & 0xF000 == 0xD000 and ((first >> 8) & 15) < 14:
        return "bcc", address + 4 + _signed((first & 0xFF) << 1, 9)
    if first & 0xF800 == 0xF000 and offset + 4 <= len(data):
        second = struct.unpack_from("<H", data, offset + 2)[0]
        if second & 0xD000 == 0xD000:
            sign = (first >> 10) & 1
            i1 = 1 ^ ((second >> 13) & 1) ^ sign
            i2 = 1 ^ ((second >> 11) & 1) ^ sign
            displacement = (sign << 24 | i1 << 23 | i2 << 22 |
                            (first & 0x3FF) << 12 | (second & 0x7FF) << 1)
            return "bl", address + 4 + _signed(displacement, 25)
    return None


def audit_indicators(data: bytes) -> dict:
    if hashlib.sha256(data).hexdigest() != STOCK_SHA256:
        raise ValueError("indicator audit requires exact pinned stock SHA-256")
    for offset, _, before in ENTRIES:
        if data[offset:offset + 4].hex() != before:
            raise ValueError("indicator entry witness mismatch")
    # Scan code-bearing regions at their execution addresses, not a fictitious
    # XIP address for the permanent RAM copy or final 200-byte boot overlay.
    regions = [(0x450, 0x20CC8, BIAS + 0x450),
               (0x20CC8, 0x21578, 0x207C00)]
    regions += [(o.code_flash - BIAS, o.code_flash - BIAS + o.code_size, o.code_ram)
                for o in overlays(data) if o.code_size]
    branches = []
    for low, high, address in regions:
        for offset in range(low, high - 1, 2):
            if BEGIN <= offset < END:
                continue
            branch = branch_candidate(data, offset, address + offset - low)
            if branch and branch[0] == "bl" and offset + 4 > high:
                continue
            if branch and BIAS + BEGIN <= branch[1] < BIAS + END:
                branches.append({"file": offset, "kind": branch[0],
                                 "target_file": branch[1] - BIAS})
    # Include unaligned literals; this is a candidate/reference scan, not a
    # declaration that all such bytes are executable function pointers.
    pointers = []
    for offset in range(len(data) - 3):
        value = struct.unpack_from("<I", data, offset)[0]
        if BIAS + BEGIN <= (value & ~1) < BIAS + END:
            pointers.append({"file": offset, "target_file": value - BIAS})
    return {
        "stock_sha256": STOCK_SHA256,
        "entry_only_experiment": [{"file": o, "name": n, "before": b,
                                   "after": RETURN_ZERO.hex()} for o, n, b in ENTRIES],
        "external_branch_candidates": branches,
        "pointer_candidates": pointers,
        "scan_regions": [{"file_start": lo, "file_end": hi, "runtime_start": pc}
                         for lo, hi, pc in regions],
        "preserved_literal_pool": [END, POOL_END],
        "preserved_neighbor_hooks_and_timers": [POOL_END, 0x3E48],
        "body_bytes_after_retaining_entries": END - BEGIN - 4 * len(ENTRIES),
        "approved_reclaimed_bytes": 0,
        "reference_closure_verified": False,
        "cold_boot_retention_verified": False,
        "physical_shutdown_verified": False,
        "flashable": False,
        "limits": "candidate scans omit computed/indirect/ROM references; no memory ownership, full boot, RTOS or physical proof",
    }
