"""Build the RT12COL Health-default / temporary-Gesture candidate offline.

The source is an independently repeated read of the exact installed RT12COL
application, normalized into a valid OTA restore container.  This candidate is
deliberately a small, size-preserving byte patch.  It does not replace a GATT
database, add a service, claim unused flash/RAM, or touch boot/DFU code.

Stock Health remains the boot/default.  ``A1 04`` still enters the native raw
mode, but its raw ownership is represented by the stock exclusive ``0x40`` bit
and the raw optical arm records that ownership without starting mode-7 optics.
While the bit is held, the stock manager rejects other optical starts.  The
normal host stop sequence (``A1 05`` then ``A1 02``) clears it and returns to
the RT12COL stock Health path.

V3 attempted to correct the freshness and bandwidth failures measured on V1,
but is revoked: CTRL1 ``0x62`` is low-power mode 3, not mode 2, and repeated
``A1 04`` commands re-enter its configuration/timer/producer path.

V4-LP2 and V5-LP1 are retained only for exact provenance after physical tests
produced 49.3976% and 49.0% consecutive duplicate payloads. Both are revoked and
must never be selected for installation. RT12COL's
physical sensor is the stock-supported LIS2DW12 branch (WHO_AM_I ``0x44``),
whose active CTRL1 is ``0x32``: 25 Hz in low-power mode 3. The same stock
initializer enables activity/inactivity auto-sleep with WAKE_UP_THS ``0x41``.
V4/V5's near-exact pairs are consistent with the LIS2DW12 remaining in its
12.5 Hz inactivity state, although their low-motion captures cannot prove a
wake transition. The stock driver already uses 200 Hz elsewhere, in mode 3.
V4 writes CTRL1 ``0x61``
(200 Hz, LP2, 14-bit, 720 Hz widest front end); V5 writes CTRL1 ``0x60``
(200 Hz, LP1, 12-bit, 3200 Hz widest front end).  Both use CTRL6 ``0x10`` and
retain +/-4 g.  LP1 is the resolution/step-size comparison candidate for the
12-bit STK8321; LP2 is the closer bandwidth candidate to RT02's nominal 1 kHz.

V6 is V4 plus one bounded ownership correction: Gesture writes WAKE_UP_THS
``0x01`` (stock ``0x41`` with only SLEEP_ON cleared), and every common exit
restores exact stock ``0x41``. It is reproducible and tested off-ring but is not
flash-approved.

Notification delivery, range, FIFO mode, packet layout and every non-Gesture
configuration stay stock.  First entry writes the Gesture filter/ODR and calls
the original one-shot producer.  If raw mode 4 is already active, a pre-entry
gate resets only the lease byte and branches directly to the handler epilogue:
it performs no owner/register write, one-shot producer call or timer restart.
Normal stop, disconnect and expiry restore CTRL1 ``0x32``, CTRL6 ``0x50``, raw
ownership and the volatile motion hold. V1–V7 introduce no command. The
separate V8 builder adds the bounded A2-to-stock-HID bridge documented below.

The bounded helpers occupy only the stock 0x48-sensor configuration branch.
The exact ring physically identified as 0x44; the one external selector edge
to the 0x48 branch is redirected to its existing return before reuse.  Gesture
is still accepted only after distinct A1/03 samples arrive.  These structural
facts do not replace on-ring FIFO, waveform, battery or Health-continuity tests.

This module performs no BLE I/O and cannot flash a ring.
"""

from __future__ import annotations

import hashlib

from whip import fwbuild, fwrt12col
from whip.fwoptical_io import _bl


BASE_SHA256 = "b180b27a3fddd24db8a49de7c6b0041b94621062187300ceeb79af3d7908c639"
BASE_SIZE = 137_996
HARDWARE = fwrt12col.HARDWARE
STOCK_VERSION = fwrt12col.STOCK_VERSION
LEGACY_CANDIDATE_VERSION = "RT12COL_1.00.01_260927"
LEGACY_CANDIDATE_SHA256 = "52736f328dd2ea60e284a25438284447b54837e93a0dbcc2da88737968b4483b"
V2_CANDIDATE_VERSION = "RT12COL_1.00.02_260927"
V2_CANDIDATE_SHA256 = "cca729f1b36543bea9d1076c8cf7a39542db608df40e24b9ce2920753e2efab4"
V3_CANDIDATE_VERSION = "RT12COL_1.00.03_260927"
V3_CANDIDATE_SHA256 = "ea5b7a61041d7c64213307018a29f7dc6d803a135afd94d1f1a25178c0ab5026"
LP2_CANDIDATE_VERSION = "RT12COL_1.00.04_260927"
LP2_CANDIDATE_SHA256 = "21de9507955e102e846932f1d3c1b16e736a73d9d355560af8cf89cc61093d78"
LP1_CANDIDATE_VERSION = "RT12COL_1.00.05_260927"
LP1_CANDIDATE_SHA256 = "23267b5e25e65591349861048c24b72b5cdbc60ea2d583a58315b4cd33d38217"
V6_CANDIDATE_VERSION = "RT12COL_1.00.06_260927"
V6_CANDIDATE_SHA256 = "e92c5bc0d2751c3348aeea56ece4e5b5693baf1f6ba45c2a869c2d79729e134d"
V7_CANDIDATE_VERSION = "RT12COL_1.00.07_260927"
V7_CANDIDATE_SHA256 = "cb815abea8d0ed0b4734b83790a45f632113e0bed4184de606b897727d4e9bd5"
V8_HID_CANDIDATE_VERSION = "RT12COL_1.00.08_260929"
V8_HID_CANDIDATE_SHA256 = "a8be4e97051b25adffaadfd7f23632c54f396c6711960edf7dd0bfce9d683fc6"
V9_HID_CANDIDATE_VERSION = "RT12COL_1.00.09_260929"
V9_HID_CANDIDATE_SHA256 = "27fdfa741407da90def1a1124f8f551503d519d8ef730d30e61fa195476339ef"
V10_HID_CANDIDATE_VERSION = "RT12COL_1.00.10_260929"
# Filled only after the exact offline artifact is reproduced below.  This is
# deliberately pinned rather than derived at import time.
V10_HID_CANDIDATE_SHA256 = "7e04ae9973341233d2dbbe06fc6eb4c228aab625b1c3687462416edbe7d21ce2"
BIAS = 0x825FB0

# Runtime Device Information stores the version as a 9-byte release component
# plus a 6-byte date at three payload locations.  Hardware strings are left
# byte-for-byte stock.
RUNTIME_RELEASE_OFFSETS = (0x1EF4, 0x7764, 0x9164)
RUNTIME_DATE_OFFSETS = (0x1F00, 0x7770, 0x9170)
LEGACY_RUNTIME_RELEASE = b"1.00.01_"
V2_RUNTIME_RELEASE = b"1.00.02_"
V3_RUNTIME_RELEASE = b"1.00.03_"
LP2_RUNTIME_RELEASE = b"1.00.04_"
LP1_RUNTIME_RELEASE = b"1.00.05_"
V6_RUNTIME_RELEASE = b"1.00.06_"
V7_RUNTIME_RELEASE = b"1.00.07_"
V8_HID_RUNTIME_RELEASE = b"1.00.08_"
V9_HID_RUNTIME_RELEASE = b"1.00.09_"
V10_HID_RUNTIME_RELEASE = b"1.00.10_"
RUNTIME_DATE = b"260927"
V8_HID_RUNTIME_DATE = b"260929"

# A1 raw callback: remove SpO2, PPG and subtype-5 notifications, retaining only
# A1/03 accelerometer delivery.  These are complete 32-bit Thumb BL calls.
SUPPRESSED_NOTIFY_CALLS = (0x1E48, 0x1EA2, 0x1F64)

# Native A1 handler and queue/link sites, all mapped in the captured RT12 image.
RAW_OWNER_LOAD = 0x21CE
RAW_STOP_CALL = 0x21F0
RAW_TIMER_IMMEDIATE = 0x2242
RAW_START_ONESHOT_CALL = 0x22EA
RAW_START_GATE = 0x21C8
RAW_START_HELPER = 0xC080
RAW_STOP_HELPER = 0xC094
DISCONNECT_HOOK = 0x692E
DISCONNECT_HELPER = 0xC0A4
QUEUE_RETRY_LIMITS = (0x7C80, 0x7C88, 0x7CD6, 0x7CDA)
CONNECTION_PARAMETER_CALL = 0x94A4
MAINTENANCE_TIMER_LITERAL = 0x1257C
RAW_OPTICAL_ARM = 0xF670
RAW_LEASE_BODY = 0x1FC8
RAW_LEASE_EPILOGUE = 0x1FD2

# LIS2DW12 active configuration, selected by the stock WHO_AM_I == 0x44
# branch. CTRL1 0x32 is 25 Hz, low-power mode 3. At 200 Hz, 0x61 selects LP2
# (14-bit, widest cutoff 720 Hz) and 0x60 selects LP1 (12-bit, widest cutoff
# 3200 Hz). CTRL6 0x50 and 0x10 both select +/-4 g; 0x10 selects BW_FILT=00.
# The exact stock driver writes 0x62 (200 Hz LP3) at file 0xc9e2, proving only
# the ODR path, not that 0x62 was the intended Gesture mode.
LIS2DW12_ACTIVE_ODR = 0xC04A
LIS2DW12_STOCK_CTRL1 = 0x32
LIS2DW12_LP2_CTRL1 = 0x61
LIS2DW12_LP1_CTRL1 = 0x60
LIS2DW12_STOCK_CTRL6 = 0x50
LIS2DW12_GESTURE_CTRL6 = 0x10
LIS2DW12_STOCK_WAKE_UP_THS = 0x41
LIS2DW12_GESTURE_WAKE_UP_THS = 0x01
LIS2DW12_OTHER_SENSOR_BRANCH = 0xBFE2
LIS2DW12_ODR_HELPER = 0xC064
LIS2DW12_STOCK_200HZ_WRITE = 0xC9E2

# The exact ring identifies as LIS2DW12 (0x44), so the stock 0x48-sensor branch
# is unreachable. Redirect that selector to its existing return and use only
# the retired branch bytes for four bounded helpers. Full configuration chooses
# 25/200 Hz from the native raw-mode byte. Raw entry writes 200 Hz and preserves
# the original one-shot producer. Raw stop restores 25 Hz after the original
# timer stop/delete. Disconnect preserves stock cleanup and, only for mode 4,
# clears raw state, stops/deletes its timer and restores 25 Hz.
V2_LIS2DW12_ODR_CALL = bytes.fromhex("00f00bf800bf00bf")
V2_LIS2DW12_ODR_HELPER_BYTES = bytes.fromhex(
    "10b5054c6078042801d1622100e032212020fff735fe10bdd49c2000"
)
V2_RAW_START_HELPER_BYTES = bytes.fromhex(
    "10b562212020fff72dfe0020f5f7affe10bd00bf"
)
V2_RAW_STOP_HELPER_BYTES = bytes.fromhex(
    "10b5f7f753fe32212020fff721fe10bd"
)
V2_DISCONNECT_HELPER_BYTES = bytes.fromhex(
    "10b5faf7daff074c6078042809d10020208010342046f7f741fe"
    "32212020fff70ffe10bdd49c2000"
)

RAW_START_HELPER_CALL = bytes.fromhex("09f0c9fe")
RAW_STOP_HELPER_CALL = bytes.fromhex("09f050ff")
DISCONNECT_HELPER_CALL = bytes.fromhex("05f0b9fb")

# Generated from firmware/rt12col_gesture_helpers.S with Cortex-M0+ code only.
# Each 00bf00bf marker is replaced below by one pinned BL. Revoked V3 used the
# first 192 bytes. Corrected candidates use 220 bytes, including a complete
# first-entry helper, and leave the exact retired branch return at 0xc142.
LIS2DW12_CONFIG_HELPER = 0xC064
RAW_START_CONFIG_HELPER = 0xC084
RESTORE_STOCK_HELPER = 0xC0A4
DISCONNECT_RESTORE_HELPER = 0xC0F0
LEASE_TICK_HELPER = 0xC108
RAW_FIRST_ENTRY_HELPER = 0xC120
V3_HELPER_REGION_END = 0xC124
HELPER_REGION_END = 0xC140
LEASE_TICKS = 250
LEASE_SECONDS = 10
V3_HELPER_TEMPLATE = bytes.fromhex(
    "10b52e4c6078042805d11021252000bf00bf622100e03221202000bf00bf10bd"
    "10b5264c002020711021252000bf00bf6221202000bf00bf002000bf00bf10bd"
    "10b504461d490020087048700871402000bf00bf204600bf00bf3221202000bf"
    "00bf5021252000bf00bf82b0694600200870887001204870684600bf00bf0028"
    "02d1012000bf00bf02b010bd10b500bf00bf0a4c6078042803d12046103000bf"
    "00bf10bd10b5054c207901302071fa2803d32046103000bf00bf10bdd49c2000"
)
HELPER_CALLS = {
    0xC072: 0xBCE4,  # conditional config: CTRL6
    0xC07E: 0xBCE4,  # conditional config: CTRL1
    0xC090: 0xBCE4,  # start: CTRL6
    0xC098: 0xBCE4,  # start: CTRL1
    0xC09E: 0x1DEE,  # preserved original one-shot producer
    0xC0B4: 0xDB18,  # release exclusive raw owner 0x40
    0xC0BA: 0x3D40,  # null-safe timer stop/delete
    0xC0C2: 0xBCE4,  # restore CTRL1
    0xC0CA: 0xBCE4,  # restore CTRL6
    0xC0DE: 0xD408,  # exact 3B motion-state setter
    0xC0E8: 0xC61C,  # exact motion-release follow-up
    0xC0F2: 0x705E,  # original disconnect cleanup
    0xC102: RESTORE_STOCK_HELPER,
    0xC11A: RESTORE_STOCK_HELPER,
    0xC124: 0xDB18,  # corrected first entry: release previous owner
    0xC12A: 0xDB32,  # corrected first entry: record exclusive owner 0x40
}


CORRECTED_LP2_HELPER_TEMPLATE = bytes.fromhex(
    "10b5344c6078042805d11021252000bf00bf612100e03221202000bf00bf10bd"
    "10b52c4c002020711021252000bf00bf6121202000bf00bf002000bf00bf10bd"
    "10b5044623490020087048700871402000bf00bf204600bf00bf3221202000bf"
    "00bf5021252000bf00bf82b0694600200870887001204870684600bf00bf0028"
    "02d1012000bf00bf02b010bd10b500bf00bf104c6078042803d12046103000bf"
    "00bf10bd10b50b4c207901302071fa2803d32046103000bf00bf10bd10b50648"
    "00bf00bf402000bf00bf042078700120387010bdd49c2000f49c2000"
)
assert len(CORRECTED_LP2_HELPER_TEMPLATE) == HELPER_REGION_END - LIS2DW12_CONFIG_HELPER


def _helper_template(gesture_ctrl1: int) -> bytes:
    if gesture_ctrl1 not in (LIS2DW12_LP2_CTRL1, LIS2DW12_LP1_CTRL1, 0x62):
        raise ValueError("unsupported Gesture CTRL1")
    old = bytes.fromhex("6221")
    replacement = bytes((gesture_ctrl1, 0x21))
    template = (V3_HELPER_TEMPLATE if gesture_ctrl1 == 0x62
                else CORRECTED_LP2_HELPER_TEMPLATE)
    if template.count(bytes.fromhex("6121") if gesture_ctrl1 != 0x62 else old) != 2:
        raise AssertionError("helper CTRL1 sites drifted")
    return (template if gesture_ctrl1 == LIS2DW12_LP2_CTRL1
            else template.replace(old if gesture_ctrl1 == 0x62 else bytes.fromhex("6121"), replacement))


LP2_HELPER_TEMPLATE = _helper_template(LIS2DW12_LP2_CTRL1)
LP1_HELPER_TEMPLATE = _helper_template(LIS2DW12_LP1_CTRL1)


def _helper_blob(template: bytes) -> bytes:
    blob = bytearray(template)
    for site, target in HELPER_CALLS.items():
        index = site - LIS2DW12_CONFIG_HELPER
        if index + 4 > len(blob):
            continue
        if blob[index:index + 4] != bytes.fromhex("00bf00bf"):
            raise AssertionError(f"helper BL marker drifted at {site:#x}")
        blob[index:index + 4] = _bl(BIAS + site, (BIAS + target) | 1)
    return bytes(blob)


V3_HELPER_BYTES = _helper_blob(V3_HELPER_TEMPLATE)
LP2_HELPER_BYTES = _helper_blob(LP2_HELPER_TEMPLATE)
LP1_HELPER_BYTES = _helper_blob(LP1_HELPER_TEMPLATE)

# V6 keeps the V4 LP2 configuration and changes only activity/inactivity
# ownership: Gesture writes WAKE_UP_THS 0x01 (stock 0x41 with SLEEP_ON clear),
# and the common exit writes exact stock 0x41. The separately assembled source
# is firmware/rt12col_gesture_helpers_v6.S. It fits inside the same unreachable
# WHO_AM_I=0x48 branch and leaves the shared stock epilogue at 0xc142 intact.
V6_RAW_START_CONFIG_HELPER = 0xC072
V6_GESTURE_CONFIG_COMMON = 0xC082
V6_RESTORE_STOCK_HELPER = 0xC09E
V6_DISCONNECT_RESTORE_HELPER = 0xC0EA
V6_LEASE_TICK_HELPER = 0xC102
V6_RAW_FIRST_ENTRY_HELPER = 0xC11A
V6_HELPER_REGION_END = 0xC138

V6_HELPER_TEMPLATE = bytes.fromhex(
    "3348407804280ad03221202000bf10b53e7100bf00bf002000bf00bf10bd10b5"
    "0121342000bf00bf1021252000bf00bf6121202000bf00bf10bd10b504462449"
    "002008800871402000bf00bf204600bf00bf3221202000bf00bf5021252000bf"
    "00bf4121342000bf00bf82b0012000020090684600bf00bf002802d1012000bf"
    "00bf02b010bd10b500bf00bf104c6078042803d12046103000bf00bf10bd10b5"
    "0b4c207901302071fa2803d32046103000bf00bf10bd10b50548203000bf00bf"
    "402000bf00bf042078700120387010bdd49c2000"
)
assert len(V6_HELPER_TEMPLATE) == V6_HELPER_REGION_END - LIS2DW12_CONFIG_HELPER

V6_HELPER_CALLS = {
    0xC076: V6_GESTURE_CONFIG_COMMON,
    0xC07C: 0x1DEE,
    0xC088: 0xBCE4,
    0xC090: 0xBCE4,
    0xC098: 0xBCE4,
    0xC0AC: 0xDB18,
    0xC0B2: 0x3D40,
    0xC0BA: 0xBCE4,
    0xC0C2: 0xBCE4,
    0xC0CA: 0xBCE4,
    0xC0D8: 0xD408,
    0xC0E2: 0xC61C,
    0xC0EC: 0x705E,
    0xC0FC: V6_RESTORE_STOCK_HELPER,
    0xC114: V6_RESTORE_STOCK_HELPER,
    0xC120: 0xDB18,
    0xC126: 0xDB32,
}


def _v6_helper_blob() -> bytes:
    blob = bytearray(V6_HELPER_TEMPLATE)
    # Health configuration tail-calls the stock register writer so its LR is
    # preserved without spending four bytes on a nested BL plus return.
    short_site, short_target = 0xC070, 0xBCE4
    short_index = short_site - LIS2DW12_CONFIG_HELPER
    if blob[short_index:short_index + 2] != bytes.fromhex("00bf"):
        raise AssertionError("V6 tail-branch marker drifted")
    displacement = short_target - (short_site + 4)
    if displacement & 1 or not -2048 <= displacement <= 2046:
        raise AssertionError("V6 tail branch no longer fits Thumb-1")
    blob[short_index:short_index + 2] = (
        0xE000 | ((displacement >> 1) & 0x7FF)
    ).to_bytes(2, "little")

    for site, target in V6_HELPER_CALLS.items():
        index = site - LIS2DW12_CONFIG_HELPER
        if blob[index:index + 4] != bytes.fromhex("00bf00bf"):
            raise AssertionError(f"V6 helper BL marker drifted at {site:#x}")
        blob[index:index + 4] = _bl(BIAS + site, (BIAS + target) | 1)
    return bytes(blob)


V6_HELPER_BYTES = _v6_helper_blob()

# V7 is a single-register timing comparison against physically fresh V6. It
# retains LP2/14-bit mode, +/-4 g, widest LP2 bandwidth, SLEEP_ON ownership,
# every exit and the lease-only renewal gate. CTRL1 0x51 changes only ODR from
# 200 to 100 Hz, testing the lower bound suggested by RT02's documented 10 ms
# equidistant mode while retaining four source frames per 25 Hz callback. It
# was physically tested: freshness passed, but model transfer did not beat V6.
# It remains recognition-only and must never be auto-routed for installation.
if V6_HELPER_TEMPLATE.count(bytes.fromhex("6121")) != 1:
    raise AssertionError("V6 Gesture CTRL1 site drifted")
V7_HELPER_TEMPLATE = V6_HELPER_TEMPLATE.replace(
    bytes.fromhex("6121"), bytes.fromhex("5121")
)


def _v7_helper_blob() -> bytes:
    blob = bytearray(V7_HELPER_TEMPLATE)
    short_site, short_target = 0xC070, 0xBCE4
    short_index = short_site - LIS2DW12_CONFIG_HELPER
    displacement = short_target - (short_site + 4)
    blob[short_index:short_index + 2] = (
        0xE000 | ((displacement >> 1) & 0x7FF)
    ).to_bytes(2, "little")
    for site, target in V6_HELPER_CALLS.items():
        index = site - LIS2DW12_CONFIG_HELPER
        if blob[index:index + 4] != bytes.fromhex("00bf00bf"):
            raise AssertionError(f"V7 helper BL marker drifted at {site:#x}")
        blob[index:index + 4] = _bl(BIAS + site, (BIAS + target) | 1)
    return bytes(blob)


V7_HELPER_BYTES = _v7_helper_blob()

# V8 returns to the physically selected V6 200 Hz/wide-band source and adds a
# size-neutral UART-to-HID bridge. The exact RT12COL_V1.0 board identifies its
# accelerometer as LIS2DW12 (0x44). The stock STK8321 (0x23) initializer at
# 0xbf30 is therefore unreachable after both of its only call edges are
# retired. Its complete 80-byte span holds the bridge without new RAM, GATT
# attributes, report-map changes, image growth, or a second task/timer.
HID_COMMAND = 0xA2
HID_DISPATCH_HOOK = 0x637E
HID_BRIDGE = 0xBF30
HID_BRIDGE_END = 0xBF80
HID_STK_INIT_BRANCH = 0xBFDA
HID_STK_RESET_BRANCH = 0xC21A
HID_SWIPE_SCHEDULER = 0x12366
HID_CONSUMER_PRESS = 0x3E1E
HID_CONSUMER_RELEASE = 0x3E48
HID_3B_HANDLER = 0x5C82
HID_MOUSE_SEND = 0x3D70
HID_WHEEL_HELPER = 0xBF14
HID_WHEEL_HELPER_END = 0xBF30
HID_HYBRID_PRESS = 0x3E1E
HID_HYBRID_RELEASE = 0x3E20
HID_HYBRID_SENDER_END = 0x3E70
HID_HYBRID_REPORT_MAPS = (0x1FE3E, 0x1FEE1)
HID_NATIVE_RELEASE_CALLS = (0x12256, 0x122DA, 0x12454)
HID_REPORT_SEND = 0x11B2A

HID_BRIDGE_TEMPLATE = bytes.fromhex(
    "10b50446a2291ad1607804280fd20122022805d20121002800d14942002003e0"
    "002102384000013800bf00bf06e02038182803d200bf00bf00bf00bf00212046"
    "3b2902d100bf00bf002110bd00000000"
)
assert len(HID_BRIDGE_TEMPLATE) == HID_BRIDGE_END - HID_BRIDGE

HID_BRIDGE_CALLS = {
    0xBF58: HID_SWIPE_SCHEDULER,
    0xBF64: HID_CONSUMER_PRESS,
    0xBF68: HID_CONSUMER_RELEASE,
    0xBF74: HID_3B_HANDLER,
}


def _hid_bridge_blob() -> bytes:
    blob = bytearray(HID_BRIDGE_TEMPLATE)
    for site, target in HID_BRIDGE_CALLS.items():
        index = site - HID_BRIDGE
        if blob[index:index + 4] != bytes.fromhex("00bf00bf"):
            raise AssertionError(f"HID bridge BL marker drifted at {site:#x}")
        blob[index:index + 4] = _bl(BIAS + site, (BIAS + target) | 1)
    return bytes(blob)


HID_BRIDGE_BYTES = _hid_bridge_blob()

# V9 extends the exact V8 bridge without changing its 80-byte placement.
# The additional 28-byte STK-only helper at 0xbf14 is called only from the
# initializer at 0xbf30, whose two selector edges V8 already retires. The
# action byte itself bounds the wheel delta to +/-5; payload bytes are unused.
# The helper returns 0x30 after wheel handling; the bridge subtracts 0x20 and
# the replacement sender consumes resulting 0x10 without a second report.
# The 82-byte replacement sender is exact-size and retains stock HID-enabled,
# GATT connection/attribute pointers and the three-byte ID4 send path. Its
# descriptor replaces both 81-byte stock map variants with one Keyboard
# Application collection containing Consumer bits and an 8-bit keycode Array.
# Host interpretation, especially Consumer fields inside that collection,
# remains experimental and must not be represented as physically verified.
V9_WHEEL_TEMPLATE = bytes.fromhex(
    "10b50f2808d209231b1a04d000200146024600bf00bf302010bd0000"
)
V9_BRIDGE_TEMPLATE = bytes.fromhex(
    "10b50446a2291ad16078042807d300bf00bf203800bf00bf00bf00bf"
    "0ee00122022805d20121002800d14942002003e00021023840000138"
    "00bf00bf002120463b2902d100bf00bf002110bd00000000"
)
assert len(V9_WHEEL_TEMPLATE) == HID_WHEEL_HELPER_END - HID_WHEEL_HELPER
assert len(V9_BRIDGE_TEMPLATE) == HID_BRIDGE_END - HID_BRIDGE

V9_HYBRID_SENDER_TEMPLATE = bytes.fromhex(
    "00e0ff200eb500220292ff280fd0b2281dd8802806d20a2819d20121"
    "81406a46118104e020304006400e6a4690720b48007800280bd00320"
    "00900120019005480649807c097802ab182200bf00bf0ebd0000"
)
assert len(V9_HYBRID_SENDER_TEMPLATE) == HID_HYBRID_SENDER_END - HID_HYBRID_PRESS

V9_HYBRID_REPORT_DESCRIPTOR = bytes.fromhex(
    "05010906a1018504150025017501950a050c"
    "09b509b609b709cd09e20a21020a23020a240209e909ea"
    "81027506950181030507150026650075089501190029658100"
    "a4b4a4b4a4b4a4b4a4b4a4b4a4b4c0"
)
assert len(V9_HYBRID_REPORT_DESCRIPTOR) == 81

# V10 changes no report fields, sender or wire action.  Physical iOS logs read
# V9's exact map but rejected its Keyboard usage as secondary because each full
# selectable map still began with Mouse/Digitizer.  Reorder each complete map
# so the exact V9 Keyboard-ID4 descriptor is its first top-level Application
# collection, followed by the byte-exact original Mouse/Digitizer descriptor.
# Full-map sizes, all report IDs and the GATT database remain unchanged.
HID_FULL_REPORT_MAPS = (0x1FDFC, 0x1FE8F)
V10_MOUSE_REPORT_PREFIX = bytes.fromhex(
    "05010902a10185010901a10005091901290515002501950575018102"
    "9501750381010501093009311601f826ff0775109502810609381581"
    "257f750895018106c0c0"
)
V10_TOUCH_REPORT_PREFIX = bytes.fromhex(
    "050d0904a10185010922a10209421500250175019501810209328102"
    "950681037508095195018102050126ff0f7510550e65330930360000"
    "46b50495018102468a0309318102c0050d0954750895018102c0"
)
assert len(V10_MOUSE_REPORT_PREFIX) == 66
assert len(V10_TOUCH_REPORT_PREFIX) == 82
V10_KEYBOARD_FIRST_REPORT_MAPS = {
    HID_FULL_REPORT_MAPS[0]: V9_HYBRID_REPORT_DESCRIPTOR + V10_MOUSE_REPORT_PREFIX,
    HID_FULL_REPORT_MAPS[1]: V9_HYBRID_REPORT_DESCRIPTOR + V10_TOUCH_REPORT_PREFIX,
}
assert tuple(map(len, V10_KEYBOARD_FIRST_REPORT_MAPS.values())) == (147, 163)


def _v9_hid_blobs() -> tuple[bytes, bytes]:
    wheel = bytearray(V9_WHEEL_TEMPLATE)
    bridge = bytearray(V9_BRIDGE_TEMPLATE)
    for blob, origin, calls in (
        (wheel, HID_WHEEL_HELPER, {0xBF26: HID_MOUSE_SEND}),
        (bridge, HID_BRIDGE, {
            0xBF3E: HID_WHEEL_HELPER,
            0xBF44: HID_HYBRID_PRESS,
            0xBF48: HID_HYBRID_RELEASE,
            0xBF68: HID_SWIPE_SCHEDULER,
            0xBF74: HID_3B_HANDLER,
        }),
    ):
        for site, target in calls.items():
            index = site - origin
            if blob[index:index + 4] != bytes.fromhex("00bf00bf"):
                raise AssertionError(f"V9 HID BL marker drifted at {site:#x}")
            blob[index:index + 4] = _bl(BIAS + site, (BIAS + target) | 1)
    return bytes(wheel), bytes(bridge)


V9_WHEEL_BYTES, V9_BRIDGE_BYTES = _v9_hid_blobs()


def _v9_hybrid_sender_blob() -> bytes:
    blob = bytearray(V9_HYBRID_SENDER_TEMPLATE)
    site = 0x3E68
    index = site - HID_HYBRID_PRESS
    if blob[index:index + 4] != bytes.fromhex("00bf00bf"):
        raise AssertionError("V9 sender BL marker drifted")
    blob[index:index + 4] = _bl(BIAS + site, (BIAS + HID_REPORT_SEND) | 1)
    return bytes(blob)


V9_HYBRID_SENDER_BYTES = _v9_hybrid_sender_blob()


def _short_b(source: int, target: int) -> bytes:
    displacement = target - (source + 4)
    if displacement & 1 or not -2048 <= displacement <= 2046:
        raise ValueError("Thumb-1 B target is out of range or unaligned")
    return (0xE000 | ((displacement >> 1) & 0x7FF)).to_bytes(2, "little")


# At RAW_START_GATE, r7 is the raw-state object and r6 is the handler's pinned
# zero register. Only active=1 AND mode=4 clear lease byte +4 and exit at
# 0x22ee. Every other state calls the complete first-entry helper, which records
# owner 0x40 and stores active=1/mode=4, then enters the unchanged timer path.
def _raw_start_gate_bytes(first_entry_helper: int) -> bytes:
    return (
        bytes.fromhex("3878012804d17878042801d13e71")
        + _short_b(RAW_START_GATE + 14, 0x22EE)
        + _bl(BIAS + RAW_START_GATE + 16, (BIAS + first_entry_helper) | 1)
        + _short_b(RAW_START_GATE + 20, 0x2240)
    )


RAW_START_GATE_BYTES = _raw_start_gate_bytes(RAW_FIRST_ENTRY_HELPER)
assert len(RAW_START_GATE_BYTES) == 22


def _raw_lease_body_bytes(lease_tick_helper: int) -> bytes:
    return (
        _bl(BIAS + RAW_LEASE_BODY, (BIAS + lease_tick_helper) | 1)
        + _short_b(RAW_LEASE_BODY + 4, RAW_LEASE_EPILOGUE)
        + bytes.fromhex("00bf00bf")
    )


RAW_LEASE_BODY_BYTES = _raw_lease_body_bytes(LEASE_TICK_HELPER)

# At RAW_OPTICAL_ARM, ``b 0xf638`` reaches the original ``mask |= bits`` tail.
# It is used only after the A1 owner was changed to exclusive bit 0x40.  That
# bit takes the stock fast-return path for subsequent Health optical requests;
# A1 02 clears it during the required two-command stop sequence.
RAW_OPTICAL_RECORD_BRANCH = bytes.fromhex("e2e7")

# Complete neighboring signatures.  A matching byte at a patch location is not
# enough: these anchors bind each edit to its reviewed instruction context.
_SIGNATURES = (
    (0x1DEE, bytes.fromhex("f0b589b000206c4620700190029003900490a1202071")),
    (0x1E38, bytes.fromhex("a0730f2101a802f059f86b46d87401a805f0f0fe0bf0bbff")),
    (0x1E92, bytes.fromhex("88730f2101a802f02cf86946c87401a805f0c3fe0026")),
    (0x1F54, bytes.fromhex("88730f2101a801f0cbff6946c87401a805f062fe")),
    (0x21C8, bytes.fromhex("5c480bf0a5fc0120c0020bf0aefc04207870012038702fe0")),
    (0x223C, bytes.fromhex("687878703c487d220123d2003e49103801f062fd4ae0")),
    (0x22E2, bytes.fromhex("04a805f0a2fc0020fff780fd70e6")),
    (0x6926, bytes.fromhex("14217976b876787400f096fb2046ff381438")),
    (0x7C7A, bytes.fromhex("01280bd07078142805d2401c70701420e5f784da12e0")),
    (0x7CD0, bytes.fromhex("01280cd07078142806d21420e5f75bda7078401c7070")),
    (0x947C, bytes.fromhex(
        "feb5434cff236068f533c278464d5100891e8eb2817802964f00bf1e"
        "bfb20197009303783b48807c0cf04efc0120a070"
    )),
    (0x121F6, bytes.fromhex(
        "10b5df4c607a002801d01e2801d901206072f7f79ef9627adb480023"
        "4243da49db48f1f77cfd10bd"
    )),
    (0xF5EA, bytes.fromhex(
        "f8b50446f4f75ffb6b49002010390870674da021288827460f400126"
        "00281ad0420617d4002f12d0084210d1"
    )),
    (0xF662, bytes.fromhex(
        "c821402c03d00120c002844205d14a48001f01800721817004e0"
    )),
    (0xC02A, bytes.fromhex(
        "10212520fff759fe00213f20fff755fe50212520fff751fedf212e20"
        "fff74dfe32212020fff749fe00212320fff745fe00212220fff741fe"
    )),
    (0xBFD8, bytes.fromhex("232821d0442824d048283fd0ade0")),
    (0xC1F4, bytes.fromhex(
        "10b53220fff7c0fdfff7a5ff6b480078482816d0442814d0332807d0"
        "152805d0112805d023280ad0282801d0002010bd"
    )),
    (0x6378, bytes.fromhex("00190179001d3b294bd015dc152935d0")),
    (0xBF30, bytes.fromhex(
        "10b5b6211420fff7a2fe1d4932200968884705210f20fff79afe5e20c021"
        "fff796fe34200421fff792fe20200521fff78efe1a200221fff78afe1720"
        "4021fff786fe3d202021fff782fefff7cbff10bd"
    )),
    (0xC064, bytes.fromhex(
        "1325012269462846fff753fe6a461178ef2421402020014311702846"
        "fff763fe102001226946fff744fe6a461178102001431170fff757fe"
        "012269462846fff738fe6a4611780826314311702846fff74afe1525"
        "012269462846fff72afe6a461078062108433043"
    )),
    (fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET - 8,
     bytes.fromhex("984c2078c0070bd17d21c900e01ce5f7f3db")),
)


def _common_patch_map(runtime_release: bytes) -> dict[int, bytes]:
    patches: dict[int, bytes] = {
        # 0x800 construction -> exclusive stock raw owner 0x40 + alignment NOP.
        RAW_OWNER_LOAD: bytes.fromhex("402000bf"),
        RAW_TIMER_IMMEDIATE: bytes([4]),
        CONNECTION_PARAMETER_CALL: bytes.fromhex("00bf00bf"),
        MAINTENANCE_TIMER_LITERAL: (600_000).to_bytes(4, "little"),
        RAW_OPTICAL_ARM: RAW_OPTICAL_RECORD_BRANCH,
    }
    patches.update({offset: bytes.fromhex("00bf00bf") for offset in SUPPRESSED_NOTIFY_CALLS})
    patches.update({offset: bytes([2]) for offset in QUEUE_RETRY_LIMITS})
    patches.update({offset: runtime_release for offset in RUNTIME_RELEASE_OFFSETS})
    patches.update({offset: RUNTIME_DATE for offset in RUNTIME_DATE_OFFSETS})
    return patches


def legacy_patch_map() -> dict[int, bytes]:
    """Return the reproducible V1 map retained for rollback/audit."""
    return _common_patch_map(LEGACY_RUNTIME_RELEASE)


def v2_patch_map() -> dict[int, bytes]:
    """Return the superseded 200 Hz / ODR/4 V2 draft for provenance only."""
    patches = _common_patch_map(V2_RUNTIME_RELEASE)
    patches[LIS2DW12_OTHER_SENSOR_BRANCH] = bytes.fromhex("1cd0")
    patches[LIS2DW12_ACTIVE_ODR] = V2_LIS2DW12_ODR_CALL
    patches[LIS2DW12_ODR_HELPER] = V2_LIS2DW12_ODR_HELPER_BYTES
    patches[RAW_START_ONESHOT_CALL] = RAW_START_HELPER_CALL
    patches[RAW_STOP_CALL] = RAW_STOP_HELPER_CALL
    patches[RAW_START_HELPER] = V2_RAW_START_HELPER_BYTES
    patches[RAW_STOP_HELPER] = V2_RAW_STOP_HELPER_BYTES
    patches[DISCONNECT_HOOK] = DISCONNECT_HELPER_CALL
    patches[DISCONNECT_HELPER] = V2_DISCONNECT_HELPER_BYTES
    return patches


def v3_patch_map() -> dict[int, bytes]:
    """Return the revoked but exactly reproducible V3 edit map."""
    patches = _common_patch_map(V3_RUNTIME_RELEASE)
    patches[LIS2DW12_OTHER_SENSOR_BRANCH] = bytes.fromhex("1cd0")
    patches[LIS2DW12_ACTIVE_ODR] = (
        _bl(BIAS + LIS2DW12_ACTIVE_ODR, (BIAS + LIS2DW12_CONFIG_HELPER) | 1)
        + bytes.fromhex("00bf00bf")
    )
    patches[RAW_START_ONESHOT_CALL] = _bl(
        BIAS + RAW_START_ONESHOT_CALL, (BIAS + RAW_START_CONFIG_HELPER) | 1
    )
    patches[RAW_STOP_CALL] = _bl(
        BIAS + RAW_STOP_CALL, (BIAS + RESTORE_STOCK_HELPER) | 1
    )
    patches[DISCONNECT_HOOK] = _bl(
        BIAS + DISCONNECT_HOOK, (BIAS + DISCONNECT_RESTORE_HELPER) | 1
    )
    patches[RAW_LEASE_BODY] = RAW_LEASE_BODY_BYTES
    patches[LIS2DW12_CONFIG_HELPER] = V3_HELPER_BYTES
    return patches


def _corrected_patch_map(runtime_release: bytes, helper_bytes: bytes) -> dict[int, bytes]:
    """Build either corrected candidate, including the lease-only entry gate."""
    patches = _common_patch_map(runtime_release)
    # The gate calls a complete first-entry helper for owner/state setup, so the
    # old overlapping four-byte owner edit must not be emitted.
    patches.pop(RAW_OWNER_LOAD)
    patches[RAW_START_GATE] = RAW_START_GATE_BYTES
    patches[LIS2DW12_OTHER_SENSOR_BRANCH] = bytes.fromhex("1cd0")
    patches[LIS2DW12_ACTIVE_ODR] = (
        _bl(BIAS + LIS2DW12_ACTIVE_ODR, (BIAS + LIS2DW12_CONFIG_HELPER) | 1)
        + bytes.fromhex("00bf00bf")
    )
    patches[RAW_START_ONESHOT_CALL] = _bl(
        BIAS + RAW_START_ONESHOT_CALL, (BIAS + RAW_START_CONFIG_HELPER) | 1
    )
    patches[RAW_STOP_CALL] = _bl(
        BIAS + RAW_STOP_CALL, (BIAS + RESTORE_STOCK_HELPER) | 1
    )
    patches[DISCONNECT_HOOK] = _bl(
        BIAS + DISCONNECT_HOOK, (BIAS + DISCONNECT_RESTORE_HELPER) | 1
    )
    patches[RAW_LEASE_BODY] = RAW_LEASE_BODY_BYTES
    patches[LIS2DW12_CONFIG_HELPER] = helper_bytes
    return patches


def lp2_patch_map() -> dict[int, bytes]:
    return _corrected_patch_map(LP2_RUNTIME_RELEASE, LP2_HELPER_BYTES)


def lp1_patch_map() -> dict[int, bytes]:
    return _corrected_patch_map(LP1_RUNTIME_RELEASE, LP1_HELPER_BYTES)


def v6_patch_map() -> dict[int, bytes]:
    """V4-LP2 plus only the bounded SLEEP_ON clear/exact-stock restore."""
    patches = _common_patch_map(V6_RUNTIME_RELEASE)
    patches.pop(RAW_OWNER_LOAD)
    patches[RAW_START_GATE] = _raw_start_gate_bytes(V6_RAW_FIRST_ENTRY_HELPER)
    patches[LIS2DW12_OTHER_SENSOR_BRANCH] = bytes.fromhex("1cd0")
    patches[LIS2DW12_ACTIVE_ODR] = (
        _bl(BIAS + LIS2DW12_ACTIVE_ODR, (BIAS + LIS2DW12_CONFIG_HELPER) | 1)
        + bytes.fromhex("00bf00bf")
    )
    patches[RAW_START_ONESHOT_CALL] = _bl(
        BIAS + RAW_START_ONESHOT_CALL, (BIAS + V6_RAW_START_CONFIG_HELPER) | 1
    )
    patches[RAW_STOP_CALL] = _bl(
        BIAS + RAW_STOP_CALL, (BIAS + V6_RESTORE_STOCK_HELPER) | 1
    )
    patches[DISCONNECT_HOOK] = _bl(
        BIAS + DISCONNECT_HOOK, (BIAS + V6_DISCONNECT_RESTORE_HELPER) | 1
    )
    patches[RAW_LEASE_BODY] = _raw_lease_body_bytes(V6_LEASE_TICK_HELPER)
    patches[LIS2DW12_CONFIG_HELPER] = V6_HELPER_BYTES
    return patches


def v7_patch_map() -> dict[int, bytes]:
    """V6 with only Gesture CTRL1 0x61 -> 0x51 (200 -> 100 Hz LP2)."""
    patches = v6_patch_map()
    patches.update({offset: V7_RUNTIME_RELEASE for offset in RUNTIME_RELEASE_OFFSETS})
    patches[LIS2DW12_CONFIG_HELPER] = V7_HELPER_BYTES
    return patches


def v8_hid_patch_map() -> dict[int, bytes]:
    """V6 source/lease behavior plus the bounded stock-HID command bridge."""
    patches = v6_patch_map()
    patches.update({offset: V8_HID_RUNTIME_RELEASE for offset in RUNTIME_RELEASE_OFFSETS})
    patches.update({offset: V8_HID_RUNTIME_DATE for offset in RUNTIME_DATE_OFFSETS})
    patches[HID_DISPATCH_HOOK] = _bl(
        BIAS + HID_DISPATCH_HOOK, (BIAS + HID_BRIDGE) | 1
    )
    patches[HID_STK_INIT_BRANCH] = bytes.fromhex("00bf")
    patches[HID_STK_RESET_BRANCH] = bytes.fromhex("00bf")
    patches[HID_BRIDGE] = HID_BRIDGE_BYTES
    return patches


def v9_hid_patch_map() -> dict[int, bytes]:
    """Experimental V9 wheel and one-report keyboard-array HID candidate."""
    patches = v8_hid_patch_map()
    patches.update({offset: V9_HID_RUNTIME_RELEASE for offset in RUNTIME_RELEASE_OFFSETS})
    patches[HID_WHEEL_HELPER] = V9_WHEEL_BYTES
    patches[HID_BRIDGE] = V9_BRIDGE_BYTES
    patches[HID_HYBRID_PRESS] = V9_HYBRID_SENDER_BYTES
    for offset in HID_HYBRID_REPORT_MAPS:
        patches[offset] = V9_HYBRID_REPORT_DESCRIPTOR
    for site in HID_NATIVE_RELEASE_CALLS:
        patches[site] = _bl(BIAS + site, (BIAS + HID_HYBRID_RELEASE) | 1)
    return patches


def v10_hid_patch_map() -> dict[int, bytes]:
    """V9 reports reordered so Keyboard is each full map's primary usage."""
    patches = v9_hid_patch_map()
    patches.update({offset: V10_HID_RUNTIME_RELEASE
                    for offset in RUNTIME_RELEASE_OFFSETS})
    for offset in HID_HYBRID_REPORT_MAPS:
        patches.pop(offset)
    patches.update(V10_KEYBOARD_FIRST_REPORT_MAPS)
    return patches


def patch_map() -> dict[int, bytes]:
    """Return the current off-ring LP2 comparison candidate edit map."""
    return lp2_patch_map()


def _edits(replacements: dict[int, bytes]) -> dict[int, tuple[int, int]]:
    source_bytes = {
        RAW_OWNER_LOAD: bytes.fromhex("0120c002"),
        RAW_START_GATE: bytes.fromhex(
            "5c480bf0a5fc0120c0020bf0aefc0420787001203870"
        ),
        RAW_TIMER_IMMEDIATE: bytes([0x7D]),
        CONNECTION_PARAMETER_CALL: bytes.fromhex("0cf04efc"),
        MAINTENANCE_TIMER_LITERAL: (60_000).to_bytes(4, "little"),
        RAW_OPTICAL_ARM: bytes.fromhex("4a48"),
        RAW_STOP_CALL: bytes.fromhex("01f0a6fd"),
        RAW_LEASE_BODY: bytes.fromhex("ff21f531642012f019fb"),
        LIS2DW12_OTHER_SENSOR_BRANCH: bytes.fromhex("3fd0"),
        LIS2DW12_ACTIVE_ODR: bytes.fromhex("32212020fff749fe"),
        LIS2DW12_CONFIG_HELPER: bytes.fromhex(
            "1325012269462846fff753fe6a461178ef2421402020014311702846"
        ),
        RAW_START_ONESHOT_CALL: bytes.fromhex("fff780fd"),
        DISCONNECT_HOOK: bytes.fromhex("00f096fb"),
        RAW_START_HELPER: bytes.fromhex(
            "fff763fe102001226946fff744fe6a4611781020"
        ),
        RAW_STOP_HELPER: bytes.fromhex(
            "01431170fff757fe012269462846fff7"
        ),
        DISCONNECT_HELPER: bytes.fromhex(
            "38fe6a4611780826314311702846fff74afe1525012269462846fff7"
            "2afe6a461078062108433043"
        ),
        HID_DISPATCH_HOOK: bytes.fromhex("3b294bd0"),
        HID_STK_INIT_BRANCH: bytes.fromhex("21d0"),
        HID_STK_RESET_BRANCH: bytes.fromhex("0ad0"),
        HID_BRIDGE: bytes.fromhex(
            "10b5b6211420fff7a2fe1d4932200968884705210f20fff79afe5e20c021"
            "fff796fe34200421fff792fe20200521fff78efe1a200221fff78afe1720"
            "4021fff786fe3d202021fff782fefff7cbff10bd"
        ),
        HID_WHEEL_HELPER: bytes.fromhex(
            "10b511207421fff7b0fe10200f21fff7acfe3e20c821fff7a8fe10bd"
        ),
        HID_HYBRID_PRESS: bytes.fromhex(
            "0eb51649097800290ed001221146814003200192029100900f480f49"
            "807c02ab1822097811f012fd0ebd0eb50c48007800280dd000200290"
            "012103200191009005480549807c02ab1822097811f0fefc0ebd"
        ),
    }
    source_bytes.update({offset: None for offset in SUPPRESSED_NOTIFY_CALLS})
    source_bytes.update({offset: bytes([0x14]) for offset in QUEUE_RETRY_LIMITS})
    source_bytes.update({offset: b"1.00.00_" for offset in RUNTIME_RELEASE_OFFSETS})
    source_bytes.update({offset: b"260520" for offset in RUNTIME_DATE_OFFSETS})
    stock_consumer_descriptor = bytes.fromhex(
        "050c0901a10185041500250175019518"
        "09b509b609b709cd09e2093009e509e709e909ea"
        "0a52010a53010a54010a55010a83010a8a010a92010a9401"
        "0a21020a23020a24020a25020a26020a27028102c0"
    )
    source_bytes.update({offset: stock_consumer_descriptor
                         for offset in HID_HYBRID_REPORT_MAPS})
    source_bytes.update({
        HID_FULL_REPORT_MAPS[0]: V10_MOUSE_REPORT_PREFIX + stock_consumer_descriptor,
        HID_FULL_REPORT_MAPS[1]: V10_TOUCH_REPORT_PREFIX + stock_consumer_descriptor,
    })
    source_bytes.update({site: _bl(BIAS + site, (BIAS + HID_CONSUMER_RELEASE) | 1)
                         for site in HID_NATIVE_RELEASE_CALLS})

    # Helper revisions replace a contiguous retired 0x48-sensor branch prefix,
    # not independent guessed fragments. V3 is 192 bytes; corrected builds are
    # 220 bytes and include the complete first-entry helper.
    if LIS2DW12_CONFIG_HELPER in replacements:
        helper_length = len(replacements[LIS2DW12_CONFIG_HELPER])
        if helper_length == V3_HELPER_REGION_END - LIS2DW12_CONFIG_HELPER:
            source_bytes[LIS2DW12_CONFIG_HELPER] = bytes.fromhex(
            "1325012269462846fff753fe6a461178ef2421402020014311702846"
            "fff763fe102001226946fff744fe6a461178102001431170fff757fe"
            "012269462846fff738fe6a4611780826314311702846fff74afe1525"
            "012269462846fff72afe6a461078062108433043bf2108404106490e21"
            "4011702846fff736fe1624012269462046fff716fe6a461178a1200143"
            "11702046fff728fe1424012269462046fff708fe6a4610780121084301"
            "07090f60200143f320014011702046fff714fe1224"
            )
        elif helper_length == HELPER_REGION_END - LIS2DW12_CONFIG_HELPER:
            source_bytes[LIS2DW12_CONFIG_HELPER] = bytes.fromhex(
                "1325012269462846fff753fe6a461178ef2421402020014311702846"
                "fff763fe102001226946fff744fe6a461178102001431170fff757fe"
                "012269462846fff738fe6a4611780826314311702846fff74afe1525"
                "012269462846fff72afe6a461078062108433043bf2108404106490e21"
                "4011702846fff736fe1624012269462046fff716fe6a461178a1200143"
                "11702046fff728fe1424012269462046fff708fe6a4610780121084301"
                "07090f60200143f320014011702046fff714fe1224012269462046fff7"
                "f4fd6a461178fb2001400420014311702046fff7"
            )
        elif helper_length == V6_HELPER_REGION_END - LIS2DW12_CONFIG_HELPER:
            source_bytes[LIS2DW12_CONFIG_HELPER] = bytes.fromhex(
                "1325012269462846fff753fe6a461178ef2421402020014311702846"
                "fff763fe102001226946fff744fe6a461178102001431170fff757fe"
                "012269462846fff738fe6a4611780826314311702846fff74afe1525"
                "012269462846fff72afe6a461078062108433043bf2108404106490e21"
                "4011702846fff736fe1624012269462046fff716fe6a461178a1200143"
                "11702046fff728fe1424012269462046fff708fe6a4610780121084301"
                "07090f60200143f320014011702046fff714fe1224012269462046fff7"
                "f4fd6a461178fb2001400420"
            )
        elif helper_length != len(source_bytes[LIS2DW12_CONFIG_HELPER]):
            raise AssertionError("unexpected helper region length")

    result: dict[int, tuple[int, int]] = {}
    for offset, replacement in replacements.items():
        expected = source_bytes[offset]
        if expected is None:
            # Every suppressed call targets the RT12 stock notify wrapper.  BL
            # deltas differ, so the exact bytes are pinned per call below.
            expected = {
                0x1E48: bytes.fromhex("05f0f0fe"),
                0x1EA2: bytes.fromhex("05f0c3fe"),
                0x1F64: bytes.fromhex("05f062fe"),
            }[offset]
        if len(expected) != len(replacement):
            raise AssertionError(f"patch length changed at {offset:#x}")
        for index, (old, new) in enumerate(zip(expected, replacement)):
            result[offset + index] = (old, new)
    return result


def _build(data: bytes, *, replacements: dict[int, bytes], version: str,
           expected_digest: str | None) -> bytes:
    if len(data) != BASE_SIZE:
        raise ValueError(f"expected {BASE_SIZE} bytes, found {len(data)}")
    if hashlib.sha256(data).hexdigest() != BASE_SHA256:
        raise ValueError("unrecognized RT12COL stock restore SHA-256")
    problems = fwrt12col.verify_ota(data)
    if problems:
        raise ValueError("base container is inconsistent: " + "; ".join(problems))
    for offset, expected in _SIGNATURES:
        if data[offset:offset + len(expected)] != expected:
            raise ValueError(f"instruction signature mismatch at {offset:#x}")

    edits = _edits(replacements)
    candidate = fwrt12col.patch_ota(data, edits, version=version)
    changed = {i for i, pair in enumerate(zip(data, candidate)) if pair[0] != pair[1]}
    allowed = set(edits)
    allowed.update(range(0x10, 0x30))
    allowed.update(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    allowed.update(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    if changed - allowed:
        raise ValueError("candidate changed bytes outside the reviewed patch and derived fields")
    if len(candidate) != len(data) or fwrt12col.verify_ota(candidate):
        raise ValueError("candidate container verification failed")
    if candidate[fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET:
                 fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET + 2] != data[
                     fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET:
                     fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET + 2]:
        raise ValueError("DFU reassembly timer changed")
    digest = hashlib.sha256(candidate).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError(f"candidate drifted: expected {expected_digest}, got {digest}")
    return candidate


def build_v1(data: bytes) -> bytes:
    """Reproduce the archived V1 image; never selected as the current candidate."""
    return _build(
        data,
        replacements=legacy_patch_map(),
        version=LEGACY_CANDIDATE_VERSION,
        expected_digest=LEGACY_CANDIDATE_SHA256,
    )


def build_v2(data: bytes) -> bytes:
    """Reproduce the superseded V2 draft; never selected as current."""
    return _build(
        data,
        replacements=v2_patch_map(),
        version=V2_CANDIDATE_VERSION,
        expected_digest=V2_CANDIDATE_SHA256,
    )


def build_v3(data: bytes) -> bytes:
    """Reproduce revoked V3 for provenance; never select it for installation."""
    return _build(
        data,
        replacements=v3_patch_map(),
        version=V3_CANDIDATE_VERSION,
        expected_digest=V3_CANDIDATE_SHA256,
    )


def build_lp2(data: bytes) -> bytes:
    """Reproduce physically rejected V4-LP2 for provenance; never install it."""
    return _build(
        data,
        replacements=lp2_patch_map(),
        version=LP2_CANDIDATE_VERSION,
        expected_digest=LP2_CANDIDATE_SHA256,
    )


def build_lp1(data: bytes) -> bytes:
    """Reproduce physically rejected V5-LP1 for provenance; never install it."""
    return _build(
        data,
        replacements=lp1_patch_map(),
        version=LP1_CANDIDATE_VERSION,
        expected_digest=LP1_CANDIDATE_SHA256,
    )


def build_v6(data: bytes) -> bytes:
    """Build V6 SLEEP_ON hypothesis candidate off-ring; not flash-approved."""
    return _build(
        data,
        replacements=v6_patch_map(),
        version=V6_CANDIDATE_VERSION,
        expected_digest=V6_CANDIDATE_SHA256,
    )


def build_v7(data: bytes) -> bytes:
    """Build the disabled 100 Hz source-cadence comparison; never auto-route."""
    return _build(
        data,
        replacements=v7_patch_map(),
        version=V7_CANDIDATE_VERSION,
        expected_digest=V7_CANDIDATE_SHA256,
    )


def build_v8_hid(data: bytes) -> bytes:
    """Build the off-ring V6-based HID bridge candidate; never auto-route."""
    return _build(
        data,
        replacements=v8_hid_patch_map(),
        version=V8_HID_CANDIDATE_VERSION,
        expected_digest=V8_HID_CANDIDATE_SHA256,
    )


def build_v9_hid(data: bytes) -> bytes:
    """Build the offline-only hybrid HID artifact used by the guarded app route."""
    return _build(
        data,
        replacements=v9_hid_patch_map(),
        version=V9_HID_CANDIDATE_VERSION,
        expected_digest=V9_HID_CANDIDATE_SHA256,
    )


def build_v10_hid(data: bytes) -> bytes:
    """Build the offline-only keyboard-primary full-map reorder experiment."""
    return _build(
        data,
        replacements=v10_hid_patch_map(),
        version=V10_HID_CANDIDATE_VERSION,
        expected_digest=V10_HID_CANDIDATE_SHA256,
    )


def build(data: bytes) -> bytes:
    """Default to the corrected LP2 comparison candidate; still not flash-approved."""
    return build_lp2(data)
