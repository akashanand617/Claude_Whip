"""Build the experimental, globally optical-disabled RT02CR gesture image.

This is distinct from skipping the first raw-mode optical start: background
health requests and indicator flashes can also start the VC30F. The first edit
rejects all optical sensor-enable requests; the second maps the driver's RUN
operation to its existing STOP value, including indicator and recovery paths.

Optical health measurements and optical indicators are unavailable in this
image, even outside streaming. Raw start requests accelerometer wake through
the existing driver. The idle-request consumer defers sleep only while raw
mode is 4 AND BLE is connected. Stop or disconnect restores the original idle
handling. Disconnect also clears raw mode 4 and stops/deletes its producer
timer after running the original disconnect cleanup. Reconnecting requires a
new A1 04, as the host normally sends. The range, 25 Hz period, and DFU code are
unchanged. A deliberate CE 02 I2C write can bypass the optical guard.
Static checks do not establish LED behavior, streaming performance, or battery
life on hardware. This module builds bytes only; it never connects or flashes.

HARDWARE UNVALIDATED: a protocol experiment stopping the VC30F kept delivering
25 Hz packets but froze their acceleration values. The wake/idle changes address
the observed accelerometer sleep path, but fresh data still needs measurement.
"""

from __future__ import annotations

import hashlib

from whip import fwbuild

EXPERIMENTAL_LABEL = "EXPERIMENTAL — HARDWARE UNVALIDATED: optical off with raw-mode accelerometer wake/hold"
BASE_SHA256 = "f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9"
BASE_SIZE = 137540
HARDWARE = "RT02CR_V3.1"
SENSOR_ENABLE_OFFSET = 0xF68C
CHIP_RUN_OFFSET = 0x1231A
RAW_START_OFFSET = 0x21DC
IDLE_REQUEST_OFFSET = 0xCAD2
IDLE_GUARD_OFFSET = 0xF690
DISCONNECT_HOOK_OFFSET = 0x691E
DISCONNECT_CLEANUP_OFFSET = 0xF6B4

# The sensor-enable entry returns immediately, making its body available for
# this helper. In the pinned image the sole external branch into [f68c,f740)
# is dd10 -> f68c; a bytewise scan finds no absolute pointers into that region.
# All original PC-relative literal pools are outside the overwritten body.
_IDLE_GUARD = bytes.fromhex(
    "0648 0078 0428 05d1 "  # raw mode != 4 -> original request at f6a4
    "0548 0078 0228 01d1 "  # BLE state != 2 -> original request at f6a4
    "0020 7047 "            # connected raw: movs r0,#0 (Z=1); bx lr
    "a079 0028 7047 00bf "  # original ldrb/cmp; bx lr; alignment
    "ac9c2000 099e2000"     # f6ac: raw mode; f6b0: BLE connection state
)
_DISCONNECT_CLEANUP = bytes.fromhex(
    "10b5 f7f7c4fc "        # push {r4,lr}; bl 7042 (original cleanup)
    "054c 2078 0428 05d1 "  # load raw mode; mode != 4 -> pop at f6ce
    "0020 2070 2046 1030 "  # clear mode; r0 = 0x209cac + 0x10
    "f4f735fb 10bd "        # bl 3d38 (stop/delete timer); pop {r4,pc}
    "ac9c2000"             # literal at f6d0: raw-mode byte address
)
_PATCHES = {
    SENSOR_ENABLE_OFFSET: bytes.fromhex("7047"),  # bx lr, before any push
    IDLE_GUARD_OFFSET: _IDLE_GUARD,
    IDLE_REQUEST_OFFSET: bytes.fromhex("02f0ddfd"),  # bl f690
    RAW_START_OFFSET: bytes.fromhex("0420 3870 0af091fc"),
    DISCONNECT_HOOK_OFFSET: bytes.fromhex("08f0c9fe"),  # bl f6b4
    DISCONNECT_CLEANUP_OFFSET: _DISCONNECT_CLEANUP,
    CHIP_RUN_OFFSET: bytes.fromhex("0020"),
}
PAYLOAD_CHANGE_ALLOWLIST = frozenset(
    offset + i for offset, replacement in _PATCHES.items() for i in range(len(replacement))
)

# File offsets, not addresses relative to the application payload. All
# signatures include neighboring instructions, not only the edited halfwords.
_SIGNATURES = (
    (0xF68A, bytes.fromhex(
        "08bd f8b5 0446 f4f70afb 7449 0020 0870 724d a021 2888 2746 "
        "0f40 0126 0028 1ad0 4206 17d4 002f 12d0 0842 10d1 6848"
    )),
    (0xCAD0, bytes.fromhex("f8bd a079 0028 0ed0 fff736fa fff7d4fe 0028 f5d0")),
    (0x21D6, bytes.fromhex("5b48 0bf053fd 0120 c002 0bf05cfd 0420 2de0 0120 c002")),
    (0x6916, bytes.fromhex("1421 7976 b876 7874 00f090fb 2046 ff38 1438")),
    (0xF6B2, bytes.fromhex(
        "0842 10d1 6848 ff21 001f 8670 9131 0180 09f0a9fc 05f04bf8 "
        "6348 001f fff793fc 2e71 0020 6873"
    )),
    (0x7042, bytes.fromhex("10b5 1349 0020 0870 1349 0870 06f0f6f9 0028 02d1 0120 05f0c4fa 10bd")),
    (0x3D38, bytes.fromhex("10b5 0446 0068 0028 05d0 2046 e9f7e2dc 2046 e9f7f1dc 10bd")),
    (0x122FE, bytes.fromhex(
        "08b5 0021 6a46 1170 0028 05d0 0128 05d0 0228 05d0 0120 08bd "
        "1170 03e0 5a20 00e0 a520 1070 0122 6946 7b20 fcf7dbfc 08bd"
    )),
)


def build(data: bytes) -> bytes:
    """Patch only the pinned 25 Hz archive; reject every other input."""
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
    for offset, expected in _SIGNATURES:
        if data[offset:offset + len(expected)] != expected:
            raise ValueError(f"instruction signature mismatch at file offset {offset:#x}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != BASE_SHA256:
        raise ValueError(f"unrecognized base SHA-256 {digest}; expected {BASE_SHA256}")

    # Raw start stores mode=4 BEFORE cb06 posts its wake request. cb06 takes no
    # argument, preserves r4-r6/LR on its stack, and does not modify r7 (the mode
    # pointer). The existing movs/strb at 21e4/2244 then harmlessly stores 4 again.
    # Its driver task performs the wake asynchronously; initial cached samples
    # are possible until that task runs.
    #
    # The idle guard replaces ldrb/cmp at the final request consumer, including
    # requests pending before raw start or posted by the wake task itself. It
    # changes only r0 and flags; ca60 already saved LR. Its existing beq uses Z
    # to reach the normal FIFO-drain path. The pending request is retained, so
    # A1 05/02 clearing raw mode restores its original handling without a latch.
    # Stock disconnect clears 0x209e09 before our hook; the connection predicate
    # releases the hold immediately. The wrapper preserves the original 7042
    # call, then clears only raw mode 4 and calls the existing null-safe 3d38
    # stop/delete helper on timer handle slot 0x209cbc. Its push {r4,lr} keeps
    # 8-byte stack alignment and preserves the caller's r4; the caller overwrites
    # r0 and flags immediately after return. This also stops the 25 Hz producer
    # work that would otherwise continue after disconnect. A reconnect itself
    # does not wake STK: the host must send a fresh A1 04.
    edits = {offset + i: value for offset, replacement in _PATCHES.items()
             for i, value in enumerate(replacement)}
    patched = fwbuild.patch(data, edits)
    changed = {i for i, (before, after) in enumerate(zip(data, patched)) if before != after}
    derived = set(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    derived.update(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    if changed - PAYLOAD_CHANGE_ALLOWLIST - derived:
        raise ValueError("built image changed bytes outside the reviewed patch and derived fields")
    problems = fwbuild.verify(patched)
    if problems:
        raise ValueError("built container is inconsistent: " + "; ".join(problems))
    return patched
