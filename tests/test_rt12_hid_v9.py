"""Offline structural proof for experimental V9 wheel and hybrid HID."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from whip import fwbuild, fwrt12col, fwrt12col_unified as unified
from whip.fwoptical_io import _bl


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "firmware" / "rt12col-stock-1.00.00.bin"
ARTIFACT = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v9-hid-experimental.bin"


def _section_bytes(dump: str, name: str) -> bytes:
    section = dump.split(f"Contents of section {name}:\n", 1)[1].split(
        "Contents of section ", 1
    )[0]
    words = []
    for line in section.splitlines():
        parts = line.split()
        if not parts or not re.fullmatch(r"[0-9a-f]{4,8}", parts[0]):
            continue
        words.extend(part for part in parts[1:5]
                     if re.fullmatch(r"(?:[0-9a-f]{2}){1,4}", part))
    return bytes.fromhex("".join(words))


def test_v9_assembly_exactly_fits_reviewed_spans(tmp_path):
    clang, objdump = shutil.which("clang"), shutil.which("objdump")
    if clang is None or objdump is None:
        pytest.skip("ARM assembler/objdump unavailable")
    output = tmp_path / "v9.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-c",
         str(ROOT / "firmware" / "rt12col_hid_bridge_v9.S"), "-o", str(output)],
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    dump = subprocess.run([objdump, "-s", str(output)], check=True,
                          capture_output=True, text=True).stdout
    assert _section_bytes(dump, ".text.rt12_hid_wheel") == unified.V9_WHEEL_TEMPLATE
    assert _section_bytes(dump, ".text.rt12_hid_bridge_v9") == unified.V9_BRIDGE_TEMPLATE
    relocations = subprocess.run([objdump, "-r", str(output)], check=True,
                                 capture_output=True, text=True).stdout
    assert "RELOCATION RECORDS" not in relocations
    assert len(unified.V9_WHEEL_TEMPLATE) == 28
    assert len(unified.V9_BRIDGE_TEMPLATE) == 80

    sender = tmp_path / "sender.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-c",
         str(ROOT / "firmware" / "rt12col_hid_sender_v9.S"), "-o", str(sender)],
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    sender_dump = subprocess.run([objdump, "-s", str(sender)], check=True,
                                 capture_output=True, text=True).stdout
    assert _section_bytes(sender_dump, ".text.rt12_hid_sender_v9") == \
        unified.V9_HYBRID_SENDER_TEMPLATE
    assert len(unified.V9_HYBRID_SENDER_TEMPLATE) == 82
    assert "RELOCATION RECORDS" not in subprocess.run(
        [objdump, "-r", str(sender)], check=True,
        capture_output=True, text=True,
    ).stdout


def test_v9_reproduces_exact_ota_and_only_reviewed_v8_delta():
    base = BASE.read_bytes()
    v8 = unified.build_v8_hid(base)
    v9 = unified.build_v9_hid(base)
    assert ARTIFACT.read_bytes() == v9
    assert len(v9) == len(base) == unified.BASE_SIZE
    assert hashlib.sha256(v9).hexdigest() == unified.V9_HID_CANDIDATE_SHA256
    assert fwrt12col.verify_ota(v9) == []
    assert v9[0x10:0x30].split(b"\0", 1)[0].decode() == \
        unified.V9_HID_CANDIDATE_VERSION

    allowed = set(range(0x10, 0x30))
    allowed.update(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    allowed.update(range(fwbuild.SHA256_OFFSET,
                         fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    for offset in unified.RUNTIME_RELEASE_OFFSETS:
        allowed.update(range(offset, offset + 9))
    allowed.update(range(unified.HID_WHEEL_HELPER, unified.HID_WHEEL_HELPER_END))
    allowed.update(range(unified.HID_BRIDGE, unified.HID_BRIDGE_END))
    allowed.update(range(unified.HID_HYBRID_PRESS, unified.HID_HYBRID_SENDER_END))
    for offset in unified.HID_HYBRID_REPORT_MAPS:
        allowed.update(range(offset, offset + 81))
    for site in unified.HID_NATIVE_RELEASE_CALLS:
        allowed.update(range(site, site + 4))
    assert {i for i, (a, b) in enumerate(zip(v8, v9)) if a != b} <= allowed
    assert v9[0x3D70:0x3E1E] == v8[0x3D70:0x3E1E]
    assert v9[0x3E70:0x3E80] == v8[0x3E70:0x3E80]
    for offset in unified.HID_HYBRID_REPORT_MAPS:
        assert v9[offset:offset + 81] == unified.V9_HYBRID_REPORT_DESCRIPTOR


def test_bounded_wheel_and_exact_hid_calls():
    base = BASE.read_bytes()
    v9 = unified.build_v9_hid(base)
    # Stock mouse sender 0x3d70 saves r0 at entry and restores it on return.
    # The wheel helper returns sentinel 0x30 after mouse delivery or action 9.
    # Bridge -0x20 makes 0x10, rejected by the hybrid sender.
    assert base[0x3D70:0x3D72] == bytes.fromhex("1fb5")
    assert base[0x3D8A:0x3D8C] == bytes.fromhex("6373")  # wheel byte <- r3
    assert base[0x3DA4:0x3DA6] == bytes.fromhex("1fbd")
    assert v9[0xBF26:0xBF2A] == _bl(
        unified.BIAS + 0xBF26, (unified.BIAS + unified.HID_MOUSE_SEND) | 1
    )
    assert v9[0xBF3E:0xBF42] == _bl(
        unified.BIAS + 0xBF3E, (unified.BIAS + unified.HID_WHEEL_HELPER) | 1
    )
    for site, target in (
        (0xBF44, unified.HID_HYBRID_PRESS),
        (0xBF48, unified.HID_HYBRID_RELEASE),
        (0xBF68, unified.HID_SWIPE_SCHEDULER),
        (0xBF74, unified.HID_3B_HANDLER),
    ):
        assert v9[site:site + 4] == _bl(
            unified.BIAS + site, (unified.BIAS + target) | 1
        )
    assert v9[0xBF42:0xBF44] == bytes.fromhex("2038")
    assert v9[0xBF14:0xBF20] == bytes.fromhex("10b50f2808d209231b1a04d0")
    assert v9[0xBF2A:0xBF2C] == bytes.fromhex("3020")
    for action in range(256):
        wheel = 9 - action if 4 <= action <= 14 and action != 9 else None
        if wheel is not None:
            assert -5 <= wheel <= 5 and wheel != 0
        if action >= 15:
            assert wheel is None


def test_stk_helper_has_only_retired_direct_caller():
    base = BASE.read_bytes()
    bias = unified.BIAS
    direct = [site for site in range(0, len(base) - 3, 2)
              if base[site:site + 4] == _bl(
                  bias + site, (bias + unified.HID_WHEEL_HELPER) | 1)]
    assert direct == [0xBF7A]
    callers = [site for site in range(0, len(base) - 3, 2)
               if base[site:site + 4] == _bl(
                   bias + site, (bias + unified.HID_BRIDGE) | 1)]
    assert callers == [0xC020, 0xC232]
    v9 = unified.build_v9_hid(base)
    assert v9[unified.HID_STK_INIT_BRANCH:unified.HID_STK_INIT_BRANCH + 2] == \
        bytes.fromhex("00bf")
    assert v9[unified.HID_STK_RESET_BRANCH:unified.HID_STK_RESET_BRANCH + 2] == \
        bytes.fromhex("00bf")


def _hid_items(data: bytes):
    cursor = 0
    while cursor < len(data):
        prefix = data[cursor]
        assert prefix != 0xFE  # no long items in the pinned 81-byte replacement
        size = (0, 1, 2, 4)[prefix & 3]
        value = int.from_bytes(data[cursor + 1:cursor + 1 + size], "little")
        assert cursor + 1 + size <= len(data)
        yield (prefix >> 2) & 3, prefix >> 4, value
        cursor += 1 + size
    assert cursor == len(data)


def test_both_id4_descriptors_parse_as_24_bit_keyboard_array_report():
    base = BASE.read_bytes()
    v9 = unified.build_v9_hid(base)
    assert all(v9[offset:offset + 81] == unified.V9_HYBRID_REPORT_DESCRIPTOR
               for offset in unified.HID_HYBRID_REPORT_MAPS)
    assert all(base[offset:offset + 81] != unified.V9_HYBRID_REPORT_DESCRIPTOR
               for offset in unified.HID_HYBRID_REPORT_MAPS)

    global_state = {"page": None, "size": None, "count": None,
                    "logical_min": None, "logical_max": None, "id": None}
    stack: list[dict] = []
    local: list[int] = []
    inputs = []
    collections = []
    for kind, tag, value in _hid_items(unified.V9_HYBRID_REPORT_DESCRIPTOR):
        if kind == 1:
            if tag in (0, 1, 2, 7, 8, 9):
                global_state[{0: "page", 1: "logical_min", 2: "logical_max",
                              7: "size", 8: "id", 9: "count"}[tag]] = value
            elif tag == 10:
                stack.append(global_state.copy())
            elif tag == 11:
                global_state = stack.pop()
        elif kind == 2:
            local.append((tag, value))
        elif kind == 0:
            if tag == 10:
                collections.append((global_state["page"], local.copy(), value))
            elif tag == 8:
                inputs.append((global_state.copy(), local.copy(), value))
            elif tag == 12:
                assert collections.pop() == (1, [(0, 6)], 1)
            local.clear()
    assert not stack and not collections
    assert len(inputs) == 3
    assert [(part[0]["size"], part[0]["count"], part[2]) for part in inputs] == [
        (1, 10, 0x02), (6, 1, 0x03), (8, 1, 0x00),
    ]
    assert all(part[0]["id"] == 4 for part in inputs)
    assert inputs[0][0]["page"] == 0x0C
    assert inputs[0][1] == [(0, usage) for usage in
                            (0xB5, 0xB6, 0xB7, 0xCD, 0xE2,
                             0x221, 0x223, 0x224, 0xE9, 0xEA)]
    assert inputs[2][0]["page"] == 0x07
    assert inputs[2][0]["logical_min"] == 0
    assert inputs[2][0]["logical_max"] == 0x65
    assert inputs[2][1] == [(1, 0), (2, 0x65)]
    assert sum(part[0]["size"] * part[0]["count"] for part in inputs) == 24


def test_sender_preserves_native_media_and_uses_stock_three_byte_gatt_path():
    base = BASE.read_bytes()
    v9 = unified.build_v9_hid(base)
    # All stock direct press paths use only bit 3 or 9. Existing meanings are
    # Play/Pause and Volume Down in the revised Consumer field.
    assert base[0x12250:0x12252] == bytes.fromhex("0320")
    assert base[0x122D0:0x122D6] == bytes.fromhex("092000e00320")
    assert base[0x1244A:0x12450] == bytes.fromhex("092000e00320")
    for site in unified.HID_NATIVE_RELEASE_CALLS:
        assert base[site:site + 4] == _bl(
            unified.BIAS + site, (unified.BIAS + unified.HID_CONSUMER_RELEASE) | 1
        )
        assert v9[site:site + 4] == _bl(
            unified.BIAS + site, (unified.BIAS + unified.HID_HYBRID_RELEASE) | 1
        )

    sender = v9[unified.HID_HYBRID_PRESS:unified.HID_HYBRID_SENDER_END]
    assert sender[:4] == bytes.fromhex("00e0ff20")  # press/release entries
    assert sender[0x4A:0x4E] == _bl(
        unified.BIAS + 0x3E68, (unified.BIAS + unified.HID_REPORT_SEND) | 1
    )
    assert sender[0x36:0x3E] == bytes.fromhex("0320009001200190")
    # The three PC-relative loads still point to the stock HID-enabled byte,
    # attribute and connection pointers, which are unchanged after 0x3e70.
    assert sender[0x2E:0x30] == bytes.fromhex("0b48")
    assert sender[0x3E:0x42] == bytes.fromhex("05480649")
    assert v9[0x3E74:0x3E80] == base[0x3E74:0x3E80] == bytes.fromhex(
        "209e20003f9e20006fcc2000"
    )
    assert sender[0x32:0x36] == bytes.fromhex("00280bd0")  # HID-enabled gate
    assert sender[0x1A:0x22] == bytes.fromhex("012181406a461181")  # 10-bit press
    assert sender[0x24:0x2E] == bytes.fromhex("20304006400e6a469072")  # array key


def test_action_ranges_fail_closed_to_reviewed_three_byte_reports():
    # Each A2 action reaches the sender after the wheel helper and -0x20
    # bridge transform. Native callers pass Consumer indices 3 or 9 directly.
    def report(action: int):
        if action < 4:
            return "swipe"
        if 4 <= action <= 14:
            return "wheel" if action != 9 else None
        encoded = (action - 0x20) & 0xFFFFFFFF
        if encoded <= 9:
            return (1 << encoded).to_bytes(2, "little") + b"\0"
        if 0x80 <= encoded <= 0xB2:
            return b"\0\0" + bytes([(encoded + 0x20) & 0x7F])
        return None

    assert [report(0x20 + bit) for bit in range(10)] == [
        (1 << bit).to_bytes(2, "little") + b"\0" for bit in range(10)
    ]
    assert report(0xA8) == bytes.fromhex("000028")  # Enter
    assert report(0xAC) == bytes.fromhex("00002c")  # Space
    assert report(0xD2) == bytes.fromhex("000052")  # Up arrow
    assert report(0x09) is None
    assert all(report(action) is None for action in
               list(range(0x0F, 0x20)) + list(range(0x2A, 0xA0)) +
               list(range(0xD3, 0x100)))
