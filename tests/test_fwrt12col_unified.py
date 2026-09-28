"""Exact-image checks for the RT12COL unified candidate; never device I/O."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import struct
import subprocess

import capstone
from elftools.elf.elffile import ELFFile
import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_THUMB
from unicorn import arm_const as arm

from whip import fwbuild, fwrt12col, fwrt12col_unified as unified
from whip.fwcontinuity import BIAS
from whip.fwindicator import branch_candidate


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "firmware" / "rt12col-stock-1.00.00.bin"
LEGACY_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v1-experimental.bin"
V2_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v2-experimental.bin"
V3_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v3-experimental.bin"
CANDIDATE_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v4-lp2-experimental.bin"
LP1_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v5-lp1-experimental.bin"
V6_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v6-sleep-fix-experimental.bin"
V7_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v7-100hz-comparison-experimental.bin"


@pytest.fixture(scope="module")
def base() -> bytes:
    return BASE_PATH.read_bytes()


@pytest.fixture(scope="module")
def candidate(base: bytes) -> bytes:
    return unified.build(base)


def test_pinned_source_and_candidate_are_reproducible(base, candidate):
    assert len(base) == len(candidate) == unified.BASE_SIZE
    assert hashlib.sha256(base).hexdigest() == unified.BASE_SHA256
    assert hashlib.sha256(candidate).hexdigest() == unified.LP2_CANDIDATE_SHA256
    assert candidate == CANDIDATE_PATH.read_bytes()
    assert fwrt12col.verify_ota(base) == []
    assert fwrt12col.verify_ota(candidate) == []


def test_checked_in_cortex_m0_helper_source_assembles_to_embedded_template(tmp_path):
    clang = shutil.which("clang")
    assert clang is not None, "clang is required to audit the checked-in ARM helper source"
    source = ROOT / "firmware" / "rt12col_gesture_helpers.S"
    output = tmp_path / "rt12col_gesture_helpers.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-c", source, "-o", output],
        check=True, capture_output=True, text=True,
    )
    with output.open("rb") as stream:
        elf = ELFFile(stream)
        section = elf.get_section_by_name(".text.rt12_helpers")
        assert section is not None
        assert section.data() == unified.LP2_HELPER_TEMPLATE
        assert section.data_size == unified.HELPER_REGION_END - unified.LIS2DW12_CONFIG_HELPER
        assert elf.get_section_by_name(".rel.text.rt12_helpers") is None
        assert elf.get_section_by_name(".rela.text.rt12_helpers") is None

    lp1_output = tmp_path / "rt12col_gesture_helpers_lp1.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-DGESTURE_CTRL1=0x60",
         "-c", source, "-o", lp1_output],
        check=True, capture_output=True, text=True,
    )
    with lp1_output.open("rb") as stream:
        section = ELFFile(stream).get_section_by_name(".text.rt12_helpers")
        assert section is not None and section.data() == unified.LP1_HELPER_TEMPLATE


def test_v6_cortex_m0_source_assembles_exactly_without_relocations(tmp_path):
    clang = shutil.which("clang")
    assert clang is not None
    source = ROOT / "firmware" / "rt12col_gesture_helpers_v6.S"
    output = tmp_path / "rt12col_gesture_helpers_v6.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-c", source, "-o", output],
        check=True, capture_output=True, text=True,
    )
    with output.open("rb") as stream:
        elf = ELFFile(stream)
        section = elf.get_section_by_name(".text.rt12_helpers_v6")
        assert section is not None
        assert section.data() == unified.V6_HELPER_TEMPLATE
        assert section.data_size == unified.V6_HELPER_REGION_END - unified.LIS2DW12_CONFIG_HELPER
        assert elf.get_section_by_name(".rel.text.rt12_helpers_v6") is None
        assert elf.get_section_by_name(".rela.text.rt12_helpers_v6") is None

    v7_output = tmp_path / "rt12col_gesture_helpers_v7.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-DGESTURE_CTRL1=0x51",
         "-c", source, "-o", v7_output],
        check=True, capture_output=True, text=True,
    )
    with v7_output.open("rb") as stream:
        section = ELFFile(stream).get_section_by_name(".text.rt12_helpers_v6")
        assert section is not None
        assert section.data() == unified.V7_HELPER_TEMPLATE
        assert section.data_size == unified.V6_HELPER_REGION_END - unified.LIS2DW12_CONFIG_HELPER


def test_archived_v1_remains_exactly_reproducible_but_is_not_current(base):
    legacy = unified.build_v1(base)
    assert hashlib.sha256(legacy).hexdigest() == unified.LEGACY_CANDIDATE_SHA256
    assert legacy == LEGACY_PATH.read_bytes()
    assert legacy != unified.build(base)


def test_superseded_v2_draft_remains_exactly_reproducible_but_is_not_current(base):
    v2 = unified.build_v2(base)
    assert hashlib.sha256(v2).hexdigest() == unified.V2_CANDIDATE_SHA256
    assert v2 == V2_PATH.read_bytes()
    assert v2 != unified.build(base)


def test_revoked_v3_remains_reproducible_and_both_corrected_candidates_are_pinned(base):
    v3 = unified.build_v3(base)
    lp2 = unified.build_lp2(base)
    lp1 = unified.build_lp1(base)
    assert hashlib.sha256(v3).hexdigest() == unified.V3_CANDIDATE_SHA256
    assert hashlib.sha256(lp2).hexdigest() == unified.LP2_CANDIDATE_SHA256
    assert hashlib.sha256(lp1).hexdigest() == unified.LP1_CANDIDATE_SHA256
    assert v3 == V3_PATH.read_bytes()
    assert lp2 == CANDIDATE_PATH.read_bytes()
    assert lp1 == LP1_PATH.read_bytes()
    assert len({v3, lp2, lp1}) == 3


def test_v6_sleep_fix_is_exactly_reproducible_and_container_valid(base):
    v6 = unified.build_v6(base)
    assert len(v6) == unified.BASE_SIZE
    assert hashlib.sha256(v6).hexdigest() == unified.V6_CANDIDATE_SHA256
    assert v6 == V6_PATH.read_bytes()
    assert fwrt12col.verify_ota(v6) == []
    assert v6[0x10:0x30].split(b"\0", 1)[0].decode() == unified.V6_CANDIDATE_VERSION


def test_v6_changes_only_reviewed_v4_sites_identity_and_derived_container_bytes(base):
    v4, v6 = unified.build_lp2(base), unified.build_v6(base)
    changed = {i for i, pair in enumerate(zip(v4, v6)) if pair[0] != pair[1]}
    reviewed = set(range(0x10, 0x30))
    reviewed.update(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    reviewed.update(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    for patch_map in (unified.lp2_patch_map(), unified.v6_patch_map()):
        reviewed.update(
            offset + index
            for offset, replacement in patch_map.items()
            for index in range(len(replacement))
        )
    assert changed <= reviewed
    # Boot, services, partitioning, the stock 0x34/0x35/0x3f initializer and
    # the protected DFU timer remain byte-for-byte V4/stock.
    for start, end in ((0x450, 0x800), (0x7480, 0x7520),
                       (0xC4F0, 0xCC10), (0x1F000, 0x1F224),
                       (fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET - 16,
                        fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET + 32)):
        assert v6[start:end] == v4[start:end]


def test_only_reviewed_payload_runtime_identity_and_derived_bytes_change(base, candidate):
    changed = {i for i, values in enumerate(zip(base, candidate)) if values[0] != values[1]}
    payload = {
        offset + index
        for offset, replacement in unified.patch_map().items()
        for index in range(len(replacement))
    }
    allowed = set(range(0x10, 0x30)) | payload
    allowed |= set(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    allowed |= set(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    assert changed <= allowed
    assert payload <= changed | {
        # NOP halfwords can contain a byte already equal to the source byte.
        i for i in payload if base[i] == candidate[i]
    }
    assert candidate[0x30:0x50] == base[0x30:0x50]
    assert candidate[0x10:0x30].split(b"\0", 1)[0].decode() == unified.LP2_CANDIDATE_VERSION


def test_stock_boot_ble_dfu_sensor_and_partition_structures_are_not_replaced(base, candidate):
    # Entry/reset and all five service-registration callsites are outside the
    # patch set. The whole FEE7 table that the revoked RT02 image reused stays
    # untouched, as do the accelerometer driver and DFU retry timer.
    for start, end in (
        (0x450, 0x800),
        (0x7480, 0x7520),
        (0x1F000, 0x1F224),
        (0xBB00, unified.LIS2DW12_OTHER_SENSOR_BRANCH),
        (unified.LIS2DW12_OTHER_SENSOR_BRANCH + 2, unified.LIS2DW12_ACTIVE_ODR),
        (unified.HELPER_REGION_END, 0xCA00),
        (fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET - 16,
         fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET + 32),
    ):
        assert candidate[start:end] == base[start:end]
    assert len(candidate) - fwbuild.PAYLOAD_START == int.from_bytes(candidate[0x58:0x5C], "little")


def test_raw_callback_keeps_only_accelerometer_notification(base, candidate):
    for offset in unified.SUPPRESSED_NOTIFY_CALLS:
        assert base[offset:offset + 4] != bytes.fromhex("00bf00bf")
        assert candidate[offset:offset + 4] == bytes.fromhex("00bf00bf")
    # A1/03 packet's notify call remains intact.
    assert candidate[0x1F22:0x1F26] == base[0x1F22:0x1F26] == bytes.fromhex("05f083fe")


def test_raw_owner_uses_stock_exclusive_bit_and_optical_arm_records_without_run(candidate):
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    owner = list(md.disasm(candidate[unified.RAW_FIRST_ENTRY_HELPER:0xC138],
                           unified.RAW_FIRST_ENTRY_HELPER))
    assert [(i.mnemonic, i.op_str) for i in owner] == [
        ("push", "{r4, lr}"), ("ldr", "r0, [pc, #0x18]"),
        ("bl", "#0xdb18"), ("movs", "r0, #0x40"), ("bl", "#0xdb32"),
        ("movs", "r0, #4"), ("strb", "r0, [r7, #1]"),
        ("movs", "r0, #1"), ("strb", "r0, [r7]"), ("pop", "{r4, pc}"),
    ]
    arm = list(md.disasm(candidate[0xF662:0xF67C], 0xF662))
    branch = next(i for i in arm if i.address == unified.RAW_OPTICAL_ARM)
    assert branch.mnemonic == "b" and int(branch.op_str.lstrip("#"), 0) == 0xF638
    # f638 is the unchanged mask-recording tail, not the optical start at f686.
    tail = list(md.disasm(candidate[0xF638:0xF640], 0xF638))
    assert [(i.mnemonic, i.op_str) for i in tail] == [
        ("ldrh", "r0, [r5]"), ("orrs", "r0, r4"),
        ("strh", "r0, [r5]"), ("pop", "{r3, r4, r5, r6, r7, pc}"),
    ]


def test_rate_queue_and_connection_edits_match_proven_rt02_strategy(base, candidate):
    assert base[unified.RAW_TIMER_IMMEDIATE] == 125
    assert candidate[unified.RAW_TIMER_IMMEDIATE] == 4
    for offset in unified.QUEUE_RETRY_LIMITS:
        assert base[offset] == 20 and candidate[offset] == 2
    assert candidate[unified.CONNECTION_PARAMETER_CALL:
                     unified.CONNECTION_PARAMETER_CALL + 4] == bytes.fromhex("00bf00bf")
    assert int.from_bytes(candidate[unified.MAINTENANCE_TIMER_LITERAL:
                                    unified.MAINTENANCE_TIMER_LITERAL + 4], "little") == 600_000


def _instructions(data, offset, length):
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    return [(i.address, i.mnemonic, i.op_str)
            for i in md.disasm(data[offset:offset + length], offset)]


def test_lis2dw12_source_is_gesture_conditional_lp2_200hz_and_delivery_is_25hz(base, candidate):
    assert base[unified.LIS2DW12_ACTIVE_ODR:
                unified.LIS2DW12_ACTIVE_ODR + 8] == bytes.fromhex("32212020fff749fe")
    assert candidate[unified.LIS2DW12_ACTIVE_ODR:
                     unified.LIS2DW12_ACTIVE_ODR + 8] == unified.patch_map()[
                         unified.LIS2DW12_ACTIVE_ODR
                     ]
    helper = _instructions(candidate, unified.LIS2DW12_CONFIG_HELPER, 32)
    assert [(m, o) for _, m, o in helper] == [
        ("push", "{r4, lr}"), ("ldr", "r4, [pc, #0xd0]"),
        ("ldrb", "r0, [r4, #1]"), ("cmp", "r0, #4"),
        ("bne", "#0xc07a"), ("movs", "r1, #0x10"),
        ("movs", "r0, #0x25"), ("bl", "#0xbce4"),
        ("movs", "r1, #0x61"), ("b", "#0xc07c"),
        ("movs", "r1, #0x32"),
        ("movs", "r0, #0x20"), ("bl", "#0xbce4"),
        ("pop", "{r4, pc}"),
    ]
    assert int.from_bytes(candidate[unified.HELPER_REGION_END - 8:
                                    unified.HELPER_REGION_END - 4], "little") == 0x209CD4
    assert int.from_bytes(candidate[unified.HELPER_REGION_END - 4:
                                    unified.HELPER_REGION_END], "little") == 0x209CF4
    # Stock's separate 200 Hz path uses LP3 (0x62); the candidate intentionally
    # selects LP2 (0x61), while retaining that entire neighboring stock path.
    assert base[unified.LIS2DW12_STOCK_200HZ_WRITE:
                unified.LIS2DW12_STOCK_200HZ_WRITE + 8] == \
        candidate[unified.LIS2DW12_STOCK_200HZ_WRITE:
                  unified.LIS2DW12_STOCK_200HZ_WRITE + 8] == \
        bytes.fromhex("62212020fff77df9")
    assert candidate[unified.RAW_TIMER_IMMEDIATE] == 4


def test_raw_start_preserves_original_one_shot_and_never_calls_broad_wake(base, candidate):
    assert base[unified.RAW_START_ONESHOT_CALL:unified.RAW_START_ONESHOT_CALL + 4] \
        == bytes.fromhex("fff780fd")
    assert candidate[unified.RAW_START_ONESHOT_CALL:unified.RAW_START_ONESHOT_CALL + 4] \
        == unified.patch_map()[unified.RAW_START_ONESHOT_CALL]
    helper = _instructions(candidate, unified.RAW_START_CONFIG_HELPER, 32)
    assert [(m, o) for _, m, o in helper] == [
        ("push", "{r4, lr}"), ("ldr", "r4, [pc, #0xb0]"),
        ("movs", "r0, #0"), ("strb", "r0, [r4, #4]"),
        ("movs", "r1, #0x10"), ("movs", "r0, #0x25"),
        ("bl", "#0xbce4"), ("movs", "r1, #0x61"),
        ("movs", "r0, #0x20"), ("bl", "#0xbce4"),
        ("movs", "r0, #0"), ("bl", "#0x1dee"),
        ("pop", "{r4, pc}"),
    ]
    assert not any(target == 0xCB3E for _, mnemonic, operand in helper
                   if mnemonic == "bl" for target in [int(operand.lstrip("#"), 0)])
    # The timer callback and first scheduled callback path remain stock.
    assert candidate[0x223C:0x2250] != base[0x223C:0x2250]  # timer immediate only
    assert candidate[0x22EE:0x22F0] == base[0x22EE:0x22F0] == bytes.fromhex("70e6")


def test_eight_to_one_source_delivery_fifo_headroom_and_exact_range_bits_are_bounded_arithmetic():
    # This is arithmetic from configured rates and the 32-frame data sheet, not
    # physical timing evidence. Eight frames accrue per nominal 40 ms delivery;
    # the FIFO has 160 ms total depth and source age is bounded by 5 ms ideally.
    assert 200 // 25 == 8
    assert 32 * (1000 // 200) == 160
    assert unified.LIS2DW12_STOCK_CTRL6 & 0x30 == 0x10
    assert unified.LIS2DW12_GESTURE_CTRL6 & 0x30 == 0x10  # both +/-4 g
    assert unified.LIS2DW12_STOCK_CTRL6 >> 6 == 1  # stock BW_FILT=ODR/4
    assert unified.LIS2DW12_GESTURE_CTRL6 >> 6 == 0  # widest selected front end
    for phase_ms in range(5):
        last_source = None
        for delivery_ms in range(0, 10_000, 40):
            source = (delivery_ms - phase_ms) // 5
            if last_source is not None:
                assert source - last_source == 8
            last_source = source


def test_v7_is_only_a_four_to_one_100hz_timing_comparison(base):
    candidate = unified.build_v7(base)
    assert candidate == V7_PATH.read_bytes()
    assert hashlib.sha256(candidate).hexdigest() == unified.V7_CANDIDATE_SHA256
    assert 100 // 25 == 4
    # V7 differs from V6 in the version/check fields and exactly one semantic
    # helper immediate: CTRL1 0x61 -> 0x51. No catalog admission follows.
    v6 = unified.build_v6(base)
    semantic = {i for i, (left, right) in enumerate(zip(v6, candidate))
                if left != right and not (0x0C <= i < 0x30)
                and not (0x1C4 <= i < 0x1E4)}
    runtime = set()
    for offset in unified.RUNTIME_RELEASE_OFFSETS:
        runtime.update(range(offset, offset + len(unified.V7_RUNTIME_RELEASE)))
    assert semantic - runtime == {0xC094}
    assert v6[0xC094] == 0x61 and candidate[0xC094] == 0x51


def test_raw_tick_reads_one_latest_value_through_same_stock_reader_shape_as_rt02(base, candidate):
    # The A1/03 producer requests exactly one XYZ triple from cc12. That reader
    # drains the active FIFO first, then indexes backward by requested_count*6,
    # i.e. the newest ring-buffer entry for count one. Neither region is patched.
    assert candidate[0x1EB0:0x1EBC] == base[0x1EB0:0x1EBC]
    assert _instructions(candidate, 0x1EB0, 12) == [
        (0x1EB0, "movs", "r3, #1"),
        (0x1EB2, "add", "r2, sp, #0x14"),
        (0x1EB4, "add", "r1, sp, #0x1c"),
        (0x1EB6, "add", "r0, sp, #0x18"),
        (0x1EB8, "bl", "#0xcc12"),
    ]
    assert candidate[0xCC12:0xCC88] == base[0xCC12:0xCC88]
    reader = _instructions(candidate, 0xCC12, 64)
    assert (0xCC22, "cmp", "r0, #0") in reader
    assert (0xCC26, "bl", "#0xc260") in reader  # active FIFO drain
    assert (0xCC30, "movs", "r1, #6") in reader
    assert (0xCC32, "muls", "r0, r1, r0") in reader

    rt02 = (ROOT / "firmware" / "rt02cr-25hz.bin").read_bytes()
    rt02_reader = _instructions(rt02, 0xCBDA, 64)
    assert [m for _, m, _ in reader[:10]] == [m for _, m, _ in rt02_reader[:10]]


def test_rt02_reference_fully_traces_raw_notifications_to_stk_fifo_data():
    rt02 = (ROOT / "firmware" / "rt02cr-25hz.bin").read_bytes()

    # Exact STK8321 initialization used by the RT02 raw path. POWMODE 0x74 is
    # LOWPOWER + equidistant sampling + 10 ms sleep; FIFO_CONFIG 0xc8 is stream
    # mode, every fourth sample, XYZ; RANGESEL 0x05 is +/-4 g.
    assert _instructions(rt02, 0xBEDC, 58)[:15] == [
        (0xBEDC, "push", "{r4, lr}"),
        (0xBEDE, "movs", "r0, #0x11"),
        (0xBEE0, "movs", "r1, #0x74"),
        (0xBEE2, "bl", "#0xbc46"),
        (0xBEE6, "movs", "r0, #0x10"),
        (0xBEE8, "movs", "r1, #0xf"),
        (0xBEEA, "bl", "#0xbc46"),
        (0xBEEE, "movs", "r0, #0x3e"),
        (0xBEF0, "movs", "r1, #0xc8"),
        (0xBEF2, "bl", "#0xbc46"),
        (0xBEF6, "pop", "{r4, pc}"),
        (0xBEF8, "push", "{r4, lr}"),
        (0xBEFA, "movs", "r1, #0xb6"),
        (0xBEFC, "movs", "r0, #0x14"),
        (0xBEFE, "bl", "#0xbc46"),
    ]
    assert _instructions(rt02, 0xBF0A, 8)[:3] == [
        (0xBF0A, "movs", "r1, #5"),
        (0xBF0C, "movs", "r0, #0xf"),
        (0xBF0E, "bl", "#0xbc46"),
    ]
    assert 0x74 & 0x40 and 0x74 & 0x20
    assert 0xC8 >> 6 == 0b11
    assert (0xC8 >> 2) & 0b11 == 0b10
    assert 0xC8 & 0b11 == 0

    # The A1/03 producer asks the stock reader for one XYZ sample. The active
    # reader first drains hardware through c228, then indexes its newest cached
    # six-byte frame. This is not a direct XOUT1..ZOUT2 read.
    assert _instructions(rt02, 0x1EC0, 12) == [
        (0x1EC0, "movs", "r3, #1"),
        (0x1EC2, "add", "r2, sp, #0x14"),
        (0x1EC4, "add", "r1, sp, #0x1c"),
        (0x1EC6, "add", "r0, sp, #0x18"),
        (0x1EC8, "bl", "#0xcbda"),
    ]
    assert (0xCBEE, "bl", "#0xc228") in _instructions(rt02, 0xCBDA, 32)

    # Chip ID 0x23 selects the STK branch. It reads FIFO status 0x0c, bounds
    # the frame count to 32, multiplies by six, and performs the bulk read from
    # FIFODATA 0x3f through the same I2C read helper at bc12.
    selector = _instructions(rt02, 0xC23C, 22)
    assert (0xC244, "cmp", "r0, #0x23") in selector
    assert (0xC246, "beq", "#0xc2fe") in selector
    fifo = _instructions(rt02, 0xC2FE, 74)
    assert (0xC306, "movs", "r0, #0xc") in fifo
    assert (0xC308, "bl", "#0xbc12") in fifo
    assert (0xC31E, "movs", "r0, #0x20") in fifo
    assert (0xC338, "movs", "r1, #6") in fifo
    assert (0xC33A, "muls", "r0, r1, r0") in fifo
    assert (0xC340, "movs", "r0, #0x3f") in fifo
    assert (0xC342, "bl", "#0xbc12") in fifo


def test_rt02_stk_source_never_selects_the_unfiltered_dataset():
    """The training source uses reset-default DATA_SEL, not the 352 Hz mod."""
    images = (
        ((ROOT / "firmware" / "rt02cr-25hz.bin").read_bytes(), 0xBC46),
        ((ROOT / "firmware" / "rt02cr-stock-3.12.02.bin").read_bytes(), 0xBC9E),
    )
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    for image, write_helper in images:
        calls = []
        for offset in range(0x450, len(image) - 3, 2):
            instruction = next(md.disasm(image[offset:offset + 4], offset, count=1), None)
            if instruction is not None and instruction.mnemonic == "bl" \
                    and int(instruction.op_str.lstrip("#"), 0) == write_helper:
                calls.append(offset)
        assert len(calls) == 41

        # No fixed STK register write loads DATASETUP 0x13 before entering the
        # exact write helper. The sole call whose arguments are not fixed here
        # is the existing host-command dispatcher (ldrb r0/r1), not sensor init.
        for call in calls:
            context = _instructions(image, max(0x450, call - 24), min(28, call - 0x450 + 4))
            assert not any(mnemonic == "movs" and operand.endswith(", #0x13")
                           for _, mnemonic, operand in context)


def test_rt12_stock_activity_inactivity_registers_are_statically_enabled(base):
    def direct_write(call_site: int, register: int, value: int):
        assert _instructions(base, call_site - 4, 8) == [
            (call_site - 4, "movs", f"r1, #{value:#x}" if value > 9 else f"r1, #{value}"),
            (call_site - 2, "movs", f"r0, #{register:#x}"),
            (call_site, "bl", "#0xbce4"),
        ]

    # All fixed stock writes to the three activity/inactivity registers.
    for site, value in ((0xC036, 0x00), (0xC606, 0x20), (0xC644, 0x00),
                        (0xC9FE, 0x00), (0xCA2E, 0x20)):
        direct_write(site, 0x3F, value)
    direct_write(0xCA0A, 0x35, 0x40)
    direct_write(0xCA16, 0x34, 0x41)

    wake_ths, wake_dur, ctrl7 = 0x41, 0x40, 0x20
    assert (wake_ths >> 6) & 1 == 1          # SLEEP_ON
    assert wake_ths & 0x3F == 1              # threshold = FS/64
    assert wake_dur & 0x0F == 0              # SLEEP_DUR
    assert (wake_dur >> 4) & 1 == 0          # STATIONARY
    assert (wake_dur >> 5) & 0x03 == 2       # WAKE_DUR
    assert (ctrl7 >> 5) & 1 == 1             # INTERRUPTS_ENABLE

    # The other stock 0x34 writer clears only bit 7 and therefore preserves the
    # SLEEP_ON bit at bit 6; it does not disable activity/inactivity mode.
    assert _instructions(base, 0xC5CA, 28) == [
        (0xC5CA, "movs", "r4, #0x34"), (0xC5CC, "movs", "r2, #1"),
        (0xC5CE, "mov", "r1, sp"), (0xC5D0, "mov", "r0, r4"),
        (0xC5D2, "bl", "#0xbcb0"), (0xC5D6, "mov", "r2, sp"),
        (0xC5D8, "ldrb", "r0, [r2]"), (0xC5DA, "lsls", "r1, r0, #0x19"),
        (0xC5DC, "lsrs", "r1, r1, #0x19"), (0xC5DE, "strb", "r1, [r2]"),
        (0xC5E0, "mov", "r0, r4"), (0xC5E2, "bl", "#0xbce4"),
    ]


class _HelperHarness:
    """Execute only candidate helpers; all stock callees are strict stubs."""

    STOP = 0x100000
    RAW_STATE = 0x209CD4
    STACK = 0x21FFF0
    CALLEES = {
        BIAS + 0xBCE4: "write",
        BIAS + 0x1DEE: "producer",
        BIAS + 0xDB18: "owner_release",
        BIAS + 0xDB32: "owner_record",
        BIAS + 0x3D40: "timer_stop",
        BIAS + 0x705E: "disconnect",
        BIAS + 0xD408: "motion_set",
        BIAS + 0xC61C: "motion_release",
    }

    def __init__(self, candidate):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self.uc.mem_map(0x100000, 0x1000)
        self.uc.mem_map(0x200000, 0x20000)
        self.uc.mem_map(0x820000, 0x30000)
        self.uc.mem_write(BIAS, candidate)
        self.end = BIAS + len(candidate)
        self.calls = []
        self.stop_addresses = set()
        self.stopped_at = None
        self.motion_mode = 3
        self.uc.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, uc, address, _size, _opaque):
        if address in self.stop_addresses:
            self.stopped_at = address
            uc.emu_stop()
            return
        if address == self.STOP:
            uc.emu_stop()
            return
        name = self.CALLEES.get(address)
        if name is None:
            return
        r0, r1 = uc.reg_read(arm.UC_ARM_REG_R0), uc.reg_read(arm.UC_ARM_REG_R1)
        self.calls.append((name, r0, r1))
        if name == "disconnect":
            # Prove the helper does not rely on caller-clobbered registers
            # surviving the original cleanup.
            for reg in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                        arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3):
                uc.reg_write(reg, 0xDEAD0000 | reg)
        elif name == "write":
            uc.reg_write(arm.UC_ARM_REG_R0, 1)
        elif name == "motion_set":
            requested = bytes(uc.mem_read(r0, 3))
            changed = requested[0] != self.motion_mode
            self.motion_mode = requested[0]
            uc.reg_write(arm.UC_ARM_REG_R0, 0 if changed else 1)
        uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))

    def call(self, offset, r0=0):
        self.calls.clear()
        self.uc.reg_write(arm.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(arm.UC_ARM_REG_LR, self.STOP | 1)
        self.uc.reg_write(arm.UC_ARM_REG_R0, r0)
        saved = {}
        for index, reg in enumerate((arm.UC_ARM_REG_R4, arm.UC_ARM_REG_R5,
                                     arm.UC_ARM_REG_R6, arm.UC_ARM_REG_R7,
                                     arm.UC_ARM_REG_R8, arm.UC_ARM_REG_R9,
                                     arm.UC_ARM_REG_R10, arm.UC_ARM_REG_R11)):
            saved[reg] = 0x41410000 + index
            self.uc.reg_write(reg, saved[reg])
        self.uc.emu_start((BIAS + offset) | 1, self.end, count=100)
        assert self.uc.reg_read(arm.UC_ARM_REG_SP) == self.STACK
        assert {reg: self.uc.reg_read(reg) for reg in saved} == saved
        return list(self.calls)

    def call_start_gate(self, mode: int, lease: int, active: int = 1):
        self.calls.clear()
        self.stopped_at = None
        self.stop_addresses = {BIAS + 0x2240, BIAS + 0x22EE}
        self.uc.mem_write(self.RAW_STATE, bytes([active, mode, 0, 0, lease]))
        self.uc.reg_write(arm.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(arm.UC_ARM_REG_R6, 0)
        self.uc.reg_write(arm.UC_ARM_REG_R7, self.RAW_STATE)
        self.uc.emu_start((BIAS + unified.RAW_START_GATE) | 1, self.end, count=100)
        self.stop_addresses.clear()
        return self.stopped_at - BIAS, list(self.calls)

    def call_with_a1_context(self, offset: int):
        """Call a helper at the audited A1 site where r6=0 and r7=RAW_STATE."""
        self.calls.clear()
        self.uc.reg_write(arm.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(arm.UC_ARM_REG_LR, self.STOP | 1)
        saved = {
            arm.UC_ARM_REG_R4: 0x41410004,
            arm.UC_ARM_REG_R5: 0x41410005,
            arm.UC_ARM_REG_R6: 0,
            arm.UC_ARM_REG_R7: self.RAW_STATE,
            arm.UC_ARM_REG_R8: 0x41410008,
            arm.UC_ARM_REG_R9: 0x41410009,
            arm.UC_ARM_REG_R10: 0x4141000A,
            arm.UC_ARM_REG_R11: 0x4141000B,
        }
        for reg, value in saved.items():
            self.uc.reg_write(reg, value)
        self.uc.emu_start((BIAS + offset) | 1, self.end, count=100)
        assert self.uc.reg_read(arm.UC_ARM_REG_SP) == self.STACK
        assert {reg: self.uc.reg_read(reg) for reg in saved} == saved
        return list(self.calls)


def test_compiled_helpers_choose_filter_rate_preserve_one_shot_and_restore(candidate):
    h = _HelperHarness(candidate)
    for mode in range(256):
        h.uc.mem_write(h.RAW_STATE, bytes([0xA5, mode, 0, 0, 0xE7]))
        calls = h.call(unified.LIS2DW12_CONFIG_HELPER)
        expected = [("write", 0x20, 0x32)]
        if mode == 4:
            expected = [("write", 0x25, 0x10), ("write", 0x20, 0x61)]
        assert calls == expected

    h.uc.mem_write(h.RAW_STATE, bytes([0xA5, 4, 0, 0, 0xE7]))
    assert h.call(unified.RAW_START_CONFIG_HELPER) == [
        ("write", 0x25, 0x10), ("write", 0x20, 0x61),
        ("producer", 0, 0x61)
    ]
    assert h.uc.mem_read(h.RAW_STATE + 4, 1) == b"\0"
    timer_slot = h.RAW_STATE + 0x10
    calls = h.call(unified.RESTORE_STOCK_HELPER, timer_slot)
    assert [call[0] for call in calls] == [
        "owner_release", "timer_stop", "write", "write", "motion_set", "motion_release"
    ]
    assert calls[0][1] == 0x40 and calls[1][1] == timer_slot
    assert [call[1:] for call in calls[2:4]] == [(0x20, 0x32), (0x25, 0x50)]
    assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == b"\0" * 5
    assert h.motion_mode == 0


def test_lp1_candidate_has_same_lifecycle_and_lease_only_gate_with_ctrl1_0x60(base):
    lp1 = unified.build_lp1(base)
    h = _HelperHarness(lp1)
    h.uc.mem_write(h.RAW_STATE, bytes([0xA5, 4, 0, 0, 0xE7]))
    assert h.call(unified.RAW_START_CONFIG_HELPER) == [
        ("write", 0x25, 0x10), ("write", 0x20, 0x60),
        ("producer", 0, 0x60),
    ]
    boundary, calls = h.call_start_gate(mode=4, lease=0xE7)
    assert boundary == 0x22EE
    assert calls == []
    assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == bytes([1, 4, 0, 0, 0])
    calls = h.call(unified.RESTORE_STOCK_HELPER, h.RAW_STATE + 0x10)
    assert [call[0] for call in calls] == [
        "owner_release", "timer_stop", "write", "write", "motion_set", "motion_release"
    ]
    assert [call[1:] for call in calls[2:4]] == [(0x20, 0x32), (0x25, 0x50)]


def test_v6_clears_sleep_on_only_in_gesture_and_restores_exact_stock_on_stop(base):
    v6 = unified.build_v6(base)
    h = _HelperHarness(v6)

    # Health reconfiguration remains exactly the stock CTRL1 write.
    h.uc.mem_write(h.RAW_STATE, bytes([0xA5, 0, 0, 0, 0xE7]))
    assert h.call(unified.LIS2DW12_CONFIG_HELPER) == [("write", 0x20, 0x32)]

    # Gesture reconfiguration clears only SLEEP_ON before retaining V4's LP2
    # filter/ODR values. It does not invoke the one-shot producer.
    h.uc.mem_write(h.RAW_STATE, bytes([0xA5, 4, 0, 0, 0xE7]))
    assert h.call(unified.LIS2DW12_CONFIG_HELPER) == [
        ("write", 0x34, 0x01),
        ("write", 0x25, 0x10),
        ("write", 0x20, 0x61),
    ]

    # First A1 entry has the unchanged r6/r7 handler context and preserves the
    # original producer after the same three writes.
    assert h.call_with_a1_context(unified.V6_RAW_START_CONFIG_HELPER) == [
        ("write", 0x34, 0x01),
        ("write", 0x25, 0x10),
        ("write", 0x20, 0x61),
        ("producer", 0, 0x61),
    ]
    assert h.uc.mem_read(h.RAW_STATE + 4, 1) == b"\0"

    timer_slot = h.RAW_STATE + 0x10
    calls = h.call(unified.V6_RESTORE_STOCK_HELPER, timer_slot)
    assert [call[0] for call in calls] == [
        "owner_release", "timer_stop", "write", "write", "write",
        "motion_set", "motion_release",
    ]
    assert [call[1:] for call in calls[2:5]] == [
        (0x20, 0x32), (0x25, 0x50), (0x34, 0x41),
    ]
    assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == b"\0" * 5


def test_v6_disconnect_and_expiry_share_the_exact_stock_sleep_restore(base):
    v6 = unified.build_v6(base)
    h = _HelperHarness(v6)
    h.uc.mem_write(h.RAW_STATE, bytes([1, 4, 0, 0, 0xE7]))
    disconnect = h.call(unified.V6_DISCONNECT_RESTORE_HELPER)
    assert [call[1:] for call in disconnect if call[0] == "write"] == [
        (0x20, 0x32), (0x25, 0x50), (0x34, 0x41),
    ]

    h.uc.mem_write(h.RAW_STATE, bytes([1, 4, 0, 0, unified.LEASE_TICKS - 1]))
    expiry = h.call(unified.V6_LEASE_TICK_HELPER)
    assert [call[1:] for call in expiry if call[0] == "write"] == [
        (0x20, 0x32), (0x25, 0x50), (0x34, 0x41),
    ]


def test_disconnect_cleanup_is_mode_conditional_and_restores_complete_stock_state(candidate):
    h = _HelperHarness(candidate)
    for mode in range(256):
        h.motion_mode = 3
        h.uc.mem_write(h.RAW_STATE, bytes([0xA5, mode, 0, 0, 0xE7]))
        calls = h.call(unified.DISCONNECT_RESTORE_HELPER)
        assert calls[0][0] == "disconnect"
        if mode == 4:
            assert [call[0] for call in calls[1:]] == [
                "owner_release", "timer_stop", "write", "write", "motion_set", "motion_release"
            ]
            assert calls[2][1] == h.RAW_STATE + 0x10
            assert [call[1:] for call in calls[3:5]] == [(0x20, 0x32), (0x25, 0x50)]
            assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == b"\0" * 5
            assert h.motion_mode == 0
        else:
            assert len(calls) == 1
            assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == bytes([0xA5, mode, 0, 0, 0xE7])
            assert h.motion_mode == 3


def test_keepalive_counter_expires_fail_closed(candidate):
    h = _HelperHarness(candidate)
    h.uc.mem_write(h.RAW_STATE, bytes([1, 4, 0, 0, 0]))
    for tick in range(1, unified.LEASE_TICKS):
        assert h.call(unified.LEASE_TICK_HELPER) == []
        assert h.uc.mem_read(h.RAW_STATE + 4, 1) == bytes([tick])
    calls = h.call(unified.LEASE_TICK_HELPER)
    assert [call[0] for call in calls] == [
        "owner_release", "timer_stop", "write", "write", "motion_set", "motion_release"
    ]
    assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == b"\0" * 5



def test_repeated_a1_04_gate_is_lease_only_and_first_entry_preserves_stock_path(candidate):
    h = _HelperHarness(candidate)
    assert _instructions(candidate, unified.RAW_START_GATE, 22) == [
        (0x21C8, "ldrb", "r0, [r7]"),
        (0x21CA, "cmp", "r0, #1"),
        (0x21CC, "bne", "#0x21d8"),
        (0x21CE, "ldrb", "r0, [r7, #1]"),
        (0x21D0, "cmp", "r0, #4"),
        (0x21D2, "bne", "#0x21d8"),
        (0x21D4, "strb", "r6, [r7, #4]"),
        (0x21D6, "b", "#0x22ee"),
        (0x21D8, "bl", f"#{unified.RAW_FIRST_ENTRY_HELPER:#x}"),
        (0x21DC, "b", "#0x2240"),
    ]

    boundary, calls = h.call_start_gate(mode=4, lease=249)
    assert boundary == 0x22EE
    assert calls == []
    assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == bytes([1, 4, 0, 0, 0])

    for active, mode in ((0, 4), (1, 0), (0, 0)):
        boundary, calls = h.call_start_gate(mode=mode, lease=0xA5, active=active)
        assert boundary == 0x2240
        assert [call[0] for call in calls] == ["owner_release", "owner_record"]
        assert calls[1][1] == 0x40
        assert bytes(h.uc.mem_read(h.RAW_STATE, 5)) == bytes([1, 4, 0, 0, 0xA5])


def test_raw_callback_mode_four_is_hooked_to_lease_tick_and_returns_to_epilogue(base, candidate):
    assert base[unified.RAW_LEASE_BODY:unified.RAW_LEASE_EPILOGUE] == \
        bytes.fromhex("ff21f531642012f019fb")
    assert candidate[unified.RAW_LEASE_BODY:unified.RAW_LEASE_EPILOGUE] == \
        unified.RAW_LEASE_BODY_BYTES
    assert _instructions(candidate, unified.RAW_LEASE_BODY, 10) == [
        (unified.RAW_LEASE_BODY, "bl", f"#{unified.LEASE_TICK_HELPER:#x}"),
        (unified.RAW_LEASE_BODY + 4, "b", f"#{unified.RAW_LEASE_EPILOGUE:#x}"),
        (unified.RAW_LEASE_BODY + 6, "nop", ""),
        (unified.RAW_LEASE_BODY + 8, "nop", ""),
    ]


def test_reclaimed_branch_has_one_stock_edge_no_pointer_and_only_reviewed_new_edges(base, candidate):
    low, high = unified.LIS2DW12_CONFIG_HELPER, 0xC142

    def external_edges(data):
        found = []
        for offset in range(0x450, 0x20CC8 - 1, 2):
            if low <= offset < high:
                continue
            branch = branch_candidate(data, offset, BIAS + offset)
            if branch and BIAS + low <= branch[1] < BIAS + high:
                found.append((offset, branch[0], branch[1] - BIAS))
        return found

    assert external_edges(base) == [(0xBFE2, "bcc", 0xC064)]
    assert external_edges(candidate) == [
        (unified.RAW_LEASE_BODY, "bl", unified.LEASE_TICK_HELPER),
        (unified.RAW_START_GATE + 16, "bl", unified.RAW_FIRST_ENTRY_HELPER),
        (unified.RAW_STOP_CALL, "bl", unified.RESTORE_STOCK_HELPER),
        (unified.RAW_START_ONESHOT_CALL, "bl", unified.RAW_START_CONFIG_HELPER),
        (unified.DISCONNECT_HOOK, "bl", unified.DISCONNECT_RESTORE_HELPER),
        (unified.LIS2DW12_ACTIVE_ODR, "bl", unified.LIS2DW12_CONFIG_HELPER),
    ]
    for data in (base, candidate):
        pointers = []
        for offset in range(len(data) - 3):
            value = struct.unpack_from("<I", data, offset)[0] & ~1
            if BIAS + low <= value < BIAS + high and not low <= offset < high:
                pointers.append((offset, value))
        assert pointers == []

    # WHO_AM_I 0x44 still selects the active LIS branch at c02a; 0x48 can no
    # longer enter the reclaimed block and reaches the branch's stock return.
    selector = _instructions(candidate, 0xBFD8, 14)
    assert (0xBFDE, "beq", "#0xc02a") in selector
    assert (0xBFE2, "beq", "#0xc01e") in selector


def test_v6_reclaimed_region_has_only_reviewed_edges_and_preserves_shared_epilogue(base):
    v6 = unified.build_v6(base)
    low, high = unified.LIS2DW12_CONFIG_HELPER, unified.V6_HELPER_REGION_END
    found = []
    for offset in range(0x450, 0x20CC8 - 1, 2):
        if low <= offset < high:
            continue
        branch = branch_candidate(v6, offset, BIAS + offset)
        if branch and BIAS + low <= branch[1] < BIAS + high:
            found.append((offset, branch[0], branch[1] - BIAS))
    assert found == [
        (unified.RAW_LEASE_BODY, "bl", unified.V6_LEASE_TICK_HELPER),
        (unified.RAW_START_GATE + 16, "bl", unified.V6_RAW_FIRST_ENTRY_HELPER),
        (unified.RAW_STOP_CALL, "bl", unified.V6_RESTORE_STOCK_HELPER),
        (unified.RAW_START_ONESHOT_CALL, "bl", unified.V6_RAW_START_CONFIG_HELPER),
        (unified.DISCONNECT_HOOK, "bl", unified.V6_DISCONNECT_RESTORE_HELPER),
        (unified.LIS2DW12_ACTIVE_ODR, "bl", unified.LIS2DW12_CONFIG_HELPER),
    ]
    # Branches from active stock paths still land at c142. V6 ends at c138 and
    # cannot overwrite that shared stock epilogue.
    assert v6[unified.V6_HELPER_REGION_END:0xC14A] == base[
        unified.V6_HELPER_REGION_END:0xC14A
    ]


def test_runtime_identity_is_consistent_at_every_stock_copy(candidate):
    for offset in unified.RUNTIME_RELEASE_OFFSETS:
        assert candidate[offset:offset + len(unified.LP2_RUNTIME_RELEASE)] == unified.LP2_RUNTIME_RELEASE
    for offset in unified.RUNTIME_DATE_OFFSETS:
        assert candidate[offset:offset + len(unified.RUNTIME_DATE)] == unified.RUNTIME_DATE
    assert candidate.count(unified.LP2_RUNTIME_RELEASE) == 4  # three runtime copies + outer identity
    assert candidate.count(unified.RUNTIME_DATE) == 4  # three runtime copies + outer identity


@pytest.mark.parametrize("fault", ["hash", "size", "hardware", "site"])
def test_builder_rejects_every_nonexact_source(base, fault):
    changed = bytearray(base)
    if fault == "size":
        changed.pop()
    elif fault == "hardware":
        changed[0x30] ^= 1
    elif fault == "site":
        changed[unified.RAW_TIMER_IMMEDIATE] ^= 1
        changed = bytearray(fwbuild.refresh(bytes(changed)))
    else:
        changed[-1] ^= 1
    with pytest.raises(ValueError):
        unified.build(bytes(changed))


def test_patch_map_never_overlaps_header_or_protected_dfu_site():
    covered = {
        offset + index
        for offset, replacement in unified.patch_map().items()
        for index in range(len(replacement))
    }
    assert min(covered) >= fwbuild.PAYLOAD_START
    assert not (covered & set(range(
        fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET,
        fwrt12col.DFU_REASSEMBLY_TIMER_OFFSET + fwrt12col.DFU_REASSEMBLY_TIMER_SIZE,
    )))
    assert not (covered & set(range(0x7480, 0x7520)))
    assert not (covered & set(range(0x1F000, 0x1F224)))
