"""Offline structural proof for experimental V10 keyboard-primary HID maps."""

from __future__ import annotations

import hashlib
from pathlib import Path

from whip import fwbuild, fwrt12col, fwrt12col_unified as unified


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "firmware" / "rt12col-stock-1.00.00.bin"
ARTIFACT = (
    ROOT / "firmware" /
    "rt12col-25hz-health-default-gesture-v10-hid-keyboard-primary-experimental.bin"
)


def _hid_items(data: bytes):
    cursor = 0
    while cursor < len(data):
        prefix = data[cursor]
        assert prefix != 0xFE
        size = (0, 1, 2, 4)[prefix & 3]
        end = cursor + 1 + size
        assert end <= len(data)
        yield (prefix >> 2) & 3, prefix >> 4, int.from_bytes(
            data[cursor + 1:end], "little"
        )
        cursor = end
    assert cursor == len(data)


def test_v10_reproduces_exact_container_and_preserves_v9_artifact():
    base = BASE.read_bytes()
    v9_before = (
        ROOT / "firmware" /
        "rt12col-25hz-health-default-gesture-v9-hid-experimental.bin"
    ).read_bytes()
    v9 = unified.build_v9_hid(base)
    v10 = unified.build_v10_hid(base)

    assert v9 == v9_before
    assert hashlib.sha256(v9).hexdigest() == unified.V9_HID_CANDIDATE_SHA256
    assert v10 == ARTIFACT.read_bytes()
    assert hashlib.sha256(v10).hexdigest() == unified.V10_HID_CANDIDATE_SHA256
    assert len(v10) == len(v9) == len(base) == unified.BASE_SIZE
    assert fwrt12col.verify_ota(v10) == []
    assert v10[0x10:0x30].split(b"\0", 1)[0].decode() == \
        unified.V10_HID_CANDIDATE_VERSION


def test_v10_changes_only_version_full_maps_and_derived_container_fields_from_v9():
    base = BASE.read_bytes()
    v9 = unified.build_v9_hid(base)
    v10 = unified.build_v10_hid(base)
    allowed = set(range(0x10, 0x30))
    allowed.update(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    allowed.update(range(fwbuild.SHA256_OFFSET,
                         fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    for offset in unified.RUNTIME_RELEASE_OFFSETS:
        allowed.update(range(offset, offset + len(unified.V10_HID_RUNTIME_RELEASE)))
    for offset, replacement in unified.V10_KEYBOARD_FIRST_REPORT_MAPS.items():
        allowed.update(range(offset, offset + len(replacement)))
    changed = {i for i, pair in enumerate(zip(v9, v10)) if pair[0] != pair[1]}
    assert changed <= allowed

    # V10 is deliberately a descriptor-only correction on top of V9.  The
    # action bridge, sender, release calls and motion/lease firmware stay exact.
    assert v10[unified.HID_WHEEL_HELPER:unified.HID_WHEEL_HELPER_END] == \
        v9[unified.HID_WHEEL_HELPER:unified.HID_WHEEL_HELPER_END]
    assert v10[unified.HID_BRIDGE:unified.HID_BRIDGE_END] == \
        v9[unified.HID_BRIDGE:unified.HID_BRIDGE_END]
    assert v10[unified.HID_HYBRID_PRESS:unified.HID_HYBRID_SENDER_END] == \
        v9[unified.HID_HYBRID_PRESS:unified.HID_HYBRID_SENDER_END]
    for site in unified.HID_NATIVE_RELEASE_CALLS:
        assert v10[site:site + 4] == v9[site:site + 4]


def _parse_applications_and_inputs(descriptor: bytes):
    state = {"page": None, "size": None, "count": None, "id": None}
    globals_stack: list[dict] = []
    collections: list[tuple[int, int, int]] = []
    applications: list[tuple[int, int]] = []
    locals_: list[tuple[int, int]] = []
    inputs: list[tuple[dict, int, tuple[int, int]]] = []
    for kind, tag, value in _hid_items(descriptor):
        if kind == 1:
            if tag in (0, 7, 8, 9):
                key = {0: "page", 7: "size", 8: "id", 9: "count"}[tag]
                state[key] = value
            elif tag == 10:
                globals_stack.append(state.copy())
            elif tag == 11:
                state = globals_stack.pop()
        elif kind == 2:
            locals_.append((tag, value))
        elif kind == 0:
            if tag == 10:
                usage = next(value for local_tag, value in locals_
                             if local_tag == 0)
                collections.append((state["page"], usage, value))
                if value == 1:
                    applications.append((state["page"], usage))
            elif tag == 8:
                assert collections
                app = next((page, usage) for page, usage, collection_type
                           in reversed(collections) if collection_type == 1)
                inputs.append((state.copy(), value, app))
            elif tag == 12:
                collections.pop()
            locals_.clear()

    assert not globals_stack and not collections
    return applications, inputs


def test_v10_makes_keyboard_the_primary_usage_of_both_complete_maps():
    mouse_map = unified.V10_KEYBOARD_FIRST_REPORT_MAPS[
        unified.HID_FULL_REPORT_MAPS[0]
    ]
    touch_map = unified.V10_KEYBOARD_FIRST_REPORT_MAPS[
        unified.HID_FULL_REPORT_MAPS[1]
    ]
    assert mouse_map == (unified.V9_HYBRID_REPORT_DESCRIPTOR +
                         unified.V10_MOUSE_REPORT_PREFIX)
    assert touch_map == (unified.V9_HYBRID_REPORT_DESCRIPTOR +
                         unified.V10_TOUCH_REPORT_PREFIX)

    mouse_apps, mouse_inputs = _parse_applications_and_inputs(mouse_map)
    touch_apps, touch_inputs = _parse_applications_and_inputs(touch_map)
    assert mouse_apps == [(0x01, 0x06), (0x01, 0x02)]
    assert touch_apps == [(0x01, 0x06), (0x0D, 0x04)]

    # The first application in each complete selectable map is Keyboard. Its
    # three ID4 inputs remain the exact V9 10-bit Consumer, 6-bit constant and
    # 8-bit Array fields. The original ID1 transport follows byte-for-byte.
    for inputs in (mouse_inputs, touch_inputs):
        keyboard = [entry for entry in inputs if entry[2] == (0x01, 0x06)]
        assert [(entry[0]["id"], entry[0]["size"], entry[0]["count"], entry[1])
                for entry in keyboard] == [
            (4, 1, 10, 0x02), (4, 6, 1, 0x03), (4, 8, 1, 0x00),
        ]
        assert sum(entry[0]["size"] * entry[0]["count"]
                   for entry in keyboard) == 24


def test_both_complete_maps_are_reordered_and_keep_one_id4_input_reference():
    base = BASE.read_bytes()
    v10 = unified.build_v10_hid(base)
    for offset, replacement in unified.V10_KEYBOARD_FIRST_REPORT_MAPS.items():
        assert v10[offset:offset + len(replacement)] == replacement

    # Stock has one input Report characteristic with reference [ID 4, Input].
    # Both report-map variants feed that same characteristic; V10 neither adds
    # a duplicate ID/type nor edits the service database.
    assert base[0x20210:0x20212] == v10[0x20210:0x20212] == b"\x04\x01"
    assert v10[0x1FF80:0x20230] == base[0x1FF80:0x20230]


def test_boot_mouse_characteristic_is_explicitly_not_repurposed():
    base = BASE.read_bytes()
    v10 = unified.build_v10_hid(base)
    # UUID 0x2A33 at 0x20112 is the existing Boot Mouse Input characteristic.
    # It is not needed for Report-Mode keyboard delivery, and changing it would
    # remove stock boot-mouse behavior without physical evidence that it fixes
    # iOS classification.  Keep it byte-exact for this bounded experiment.
    assert base[0x20112:0x20114] == bytes.fromhex("332a")
    assert v10[0x20112:0x20114] == base[0x20112:0x20114]
    assert v10[0x200B0:0x20140] == base[0x200B0:0x20140]
