"""Build the small Health-default / temporary-Gesture firmware candidate.

This exact-image experiment reuses the stock ``A1 04``/``A1 05`` raw-mode
state instead of adding a second control stack. Stock Health is unchanged while
raw mode is not four. During connected raw mode four, new optical starts and
VC30F RUN writes are blocked while the existing STK wake/idle hold supplies the
25 Hz motion stream. Stop or disconnect restores the stock Health path.

The helpers replace the exact 252-byte FEE7 attribute database only after its
sole known registration call is replaced with a local 0xff result. UART, DFU,
DIS, HID, Health, step/sleep code, application extent and container length stay
in place. This module builds bytes only; physical validation and recovery are
still mandatory before deployment.
"""
from __future__ import annotations

import hashlib

from whip import fwbuild
from whip.fwoptical_io import _bl

BASE_SHA256 = "f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9"
BASE_SIZE = 137540
HARDWARE = "RT02CR_V3.1"
BIAS = 0x825FB0

# Startup registers UART, DFU, DIS, FEE7 and HID in that order. The original
# candidate confused UART's 0x749A call with FEE7. That removed UART while
# leaving FEE7 registered against bytes replaced by helper code. The exact FEE7
# registration call is 0x74B6 -> 0x7B3A on the pinned 25 Hz image.
FEE7_SETUP_CALL = 0x74B6
HELPER_OFFSET = 0x1F128
HELPER_CAPACITY = 252

# Generated from experiments/unified_mode_helpers.S/.ld with the pinned
# Cortex-M0+ toolchain. Tests rebuild it and compare every byte/symbol.
HELPER_BLOB = bytes.fromhex(
    "05490978042906d09e46f8b50446034b9847034b18471847ac9c2000599c8200"
    "4556830006480078042805d105480078022801d100207047a079002870470000"
    "ac9c2000099e20009e4608b500216a461170002805d0012805d002280bd00120"
    "08bd117008e0084b1b78042b01d1002002e05a2000e0a5201070012269467b20"
    "024b984708bd0000ac9c2000934c830010b5064b9847064c2078042805d10020"
    "20702046"
    "1030034b984710bdf3cf8200ac9c2000e99c8200"
)
HELPERS = {
    "sensor_enable_gate": 0x00,
    "idle_guard": 0x24,
    "chip_control": 0x48,
    "disconnect_cleanup": 0x90,
}

SENSOR_ENTRY = 0xF68C
IDLE_REQUEST = 0xCAD2
CHIP_CONTROL = 0x122FE
RAW_START = 0x21DC
DISCONNECT_HOOK = 0x691E

_SIGNATURES = (
    (0x748E, bytes.fromhex(
        "70bd10b505200ef0e7f8304800f03ffa2b4ca41f20702d4800f0aef96070"
    )),
    (0xF68C, bytes.fromhex("f8b50446f4f70afb744900200870724d")),
    (0xCAD0, bytes.fromhex("f8bda07900280ed0fff736fafff7d4fe")),
    (0x122FE, bytes.fromhex(
        "08b500216a461170002805d0012805d0022805d0012008bd117003e05a2000e0"
        "a5201070012269467b20fcf7dbfc08bd"
    )),
    (0x21D6, bytes.fromhex("5b480bf053fd0120c0020bf05cfd04202de0")),
    (0x6916, bytes.fromhex("14217976b876787400f090fb2046ff381438")),
    (0x1F224, bytes.fromhex("83d982002dda82009bda8200")),
)
_FEE7_DATABASE_SHA256 = "661f30b250906d25208494dc54f911f301e31a48ad69328dee2124839b750de1"


def _target(name: str) -> int:
    return (BIAS + HELPER_OFFSET + HELPERS[name]) | 1


def _entry_hook(site: int, name: str) -> bytes:
    # r3 is caller-clobbered; preserve the caller LR across the long BL so the
    # helper can recreate the overwritten stock prologue and return correctly.
    return bytes.fromhex("7346") + _bl(BIAS + site + 2, _target(name))


def patch_map() -> dict[int, bytes]:
    return {
        FEE7_SETUP_CALL: bytes.fromhex("ff2000bf"),  # movs r0,#0xff; nop
        HELPER_OFFSET: HELPER_BLOB,
        SENSOR_ENTRY: _entry_hook(SENSOR_ENTRY, "sensor_enable_gate"),
        IDLE_REQUEST: _bl(BIAS + IDLE_REQUEST, _target("idle_guard")),
        CHIP_CONTROL: _entry_hook(CHIP_CONTROL, "chip_control"),
        RAW_START: bytes.fromhex("042038700af091fc"),
        DISCONNECT_HOOK: _bl(BIAS + DISCONNECT_HOOK, _target("disconnect_cleanup")),
    }


def build(data: bytes) -> bytes:
    """Return a refreshed candidate only for the exact pinned 25 Hz base."""
    if len(data) != BASE_SIZE:
        raise ValueError(f"expected {BASE_SIZE} bytes, found {len(data)}")
    if data[:4] != bytes.fromhex("e5c3bd81"):
        raise ValueError("expected the RT02CR Realtek container magic")
    hardware = data[0x30:0x50].split(b"\0", 1)[0].decode("ascii", errors="replace")
    if hardware != HARDWARE:
        raise ValueError(f"expected hardware {HARDWARE!r}, found {hardware!r}")
    problems = fwbuild.verify(data)
    if problems:
        raise ValueError("base container is inconsistent: " + "; ".join(problems))
    if hashlib.sha256(data).hexdigest() != BASE_SHA256:
        raise ValueError("unrecognized 25 Hz base")
    for offset, expected in _SIGNATURES:
        if data[offset:offset + len(expected)] != expected:
            raise ValueError(f"instruction signature mismatch at {offset:#x}")
    database = data[HELPER_OFFSET:HELPER_OFFSET + HELPER_CAPACITY]
    if hashlib.sha256(database).hexdigest() != _FEE7_DATABASE_SHA256:
        raise ValueError("FEE7 database signature mismatch")
    if len(HELPER_BLOB) > HELPER_CAPACITY:
        raise ValueError("conditional helpers exceed retired database")

    patches = patch_map()
    edits = {offset + index: value for offset, replacement in patches.items()
             for index, value in enumerate(replacement)}
    patched = fwbuild.patch(data, edits)
    changed = {i for i, (before, after) in enumerate(zip(data, patched)) if before != after}
    allowed = set(edits)
    allowed.update(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    allowed.update(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    if changed - allowed:
        raise ValueError("candidate changed bytes outside the exact patch map")
    if len(patched) != len(data) or fwbuild.verify(patched):
        raise ValueError("candidate container verification failed")
    return patched
