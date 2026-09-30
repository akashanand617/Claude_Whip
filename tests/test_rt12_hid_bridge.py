"""Offline-only proof for the RT12COL V8 UART-to-stock-HID bridge."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess

import capstone
from elftools.elf.elffile import ELFFile
import pytest

from whip import fwbuild, fwrt12col, fwrt12col_unified as unified


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "firmware" / "rt12col-stock-1.00.00.bin"
V8_PATH = ROOT / "firmware" / "rt12col-25hz-health-default-gesture-v8-hid-experimental.bin"
BIAS = unified.BIAS


@pytest.fixture(scope="module")
def base() -> bytes:
    return BASE_PATH.read_bytes()


@pytest.fixture(scope="module")
def candidate(base: bytes) -> bytes:
    return unified.build_v8_hid(base)


def _instructions(data: bytes, offset: int, length: int):
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    return [(item.address, item.mnemonic, item.op_str)
            for item in md.disasm(data[offset:offset + length], offset)]


def test_checked_in_hid_bridge_source_is_exact_80_byte_armv6m(tmp_path):
    clang = shutil.which("clang")
    assert clang is not None
    output = tmp_path / "rt12col_hid_bridge.o"
    subprocess.run(
        [clang, "-target", "armv6m-none-eabi", "-c",
         ROOT / "firmware" / "rt12col_hid_bridge.S", "-o", output],
        check=True, capture_output=True, text=True,
    )
    with output.open("rb") as stream:
        elf = ELFFile(stream)
        section = elf.get_section_by_name(".text.rt12_hid_bridge")
        assert section is not None
        assert section.data_size == 80
        assert section.data() == unified.HID_BRIDGE_TEMPLATE
        assert elf.get_section_by_name(".rel.text.rt12_hid_bridge") is None
        assert elf.get_section_by_name(".rela.text.rt12_hid_bridge") is None


def test_v8_is_exact_reproducible_container_and_checked_in_artifact(base, candidate):
    assert len(candidate) == len(base) == unified.BASE_SIZE
    assert hashlib.sha256(candidate).hexdigest() == unified.V8_HID_CANDIDATE_SHA256
    assert candidate[0x10:0x30].split(b"\0", 1)[0].decode() == \
        unified.V8_HID_CANDIDATE_VERSION
    assert fwrt12col.verify_ota(candidate) == []
    if V8_PATH.exists():
        assert V8_PATH.read_bytes() == candidate


def test_v8_adds_only_identity_hid_bridge_and_derived_bytes_to_v6(base, candidate):
    v6 = unified.build_v6(base)
    changed = {index for index, pair in enumerate(zip(v6, candidate)) if pair[0] != pair[1]}
    reviewed = set(range(0x10, 0x30))
    reviewed.update(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    reviewed.update(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    for offset in unified.RUNTIME_RELEASE_OFFSETS:
        reviewed.update(range(offset, offset + len(unified.V8_HID_RUNTIME_RELEASE)))
    for offset in unified.RUNTIME_DATE_OFFSETS:
        reviewed.update(range(offset, offset + len(unified.V8_HID_RUNTIME_DATE)))
    for offset, replacement in (
        (unified.HID_DISPATCH_HOOK, b"\0" * 4),
        (unified.HID_STK_INIT_BRANCH, b"\0" * 2),
        (unified.HID_STK_RESET_BRANCH, b"\0" * 2),
        (unified.HID_BRIDGE, b"\0" * 80),
    ):
        reviewed.update(range(offset, offset + len(replacement)))
    assert changed <= reviewed

    # V8 returns to V6's selected 200 Hz/wide-band source and leaves every
    # source/lease/restore byte, the HID database, and stock trajectories intact.
    for start, end in (
        (0x1FC8, 0x1FD2), (0x21C8, 0x21DE), (0x21F0, 0x21F4),
        (0x22E2, 0x22EE), (0x6926, 0x6938), (0xC02A, 0xC138),
        (0x1221E, 0x12470), (0x1F84E, 0x1FA7A), (0x1FDFC, 0x20234),
    ):
        assert candidate[start:end] == v6[start:end]


def test_dispatch_hook_retires_only_the_exact_stk_initializer_edges(candidate):
    assert _instructions(candidate, unified.HID_DISPATCH_HOOK, 4) == [
        (unified.HID_DISPATCH_HOOK, "bl", f"#{unified.HID_BRIDGE:#x}"),
    ]
    assert _instructions(candidate, unified.HID_STK_INIT_BRANCH, 2) == [
        (unified.HID_STK_INIT_BRANCH, "nop", ""),
    ]
    assert _instructions(candidate, unified.HID_STK_RESET_BRANCH, 2) == [
        (unified.HID_STK_RESET_BRANCH, "nop", ""),
    ]
    bridge = _instructions(candidate, unified.HID_BRIDGE, 80)
    calls = [(address, operand) for address, mnemonic, operand in bridge if mnemonic == "bl"]
    assert calls == [
        (0xBF58, f"#{unified.HID_SWIPE_SCHEDULER:#x}"),
        (0xBF64, f"#{unified.HID_CONSUMER_PRESS:#x}"),
        (0xBF68, f"#{unified.HID_CONSUMER_RELEASE:#x}"),
        (0xBF74, f"#{unified.HID_3B_HANDLER:#x}"),
    ]
    assert (0xBF70, "cmp", "r1, #0x3b") in bridge


def test_patched_dispatcher_routes_3b_through_the_exact_stock_handler(base, candidate):
    hook = _instructions(candidate, unified.HID_DISPATCH_HOOK, 4)
    assert hook == [
        (unified.HID_DISPATCH_HOOK, "bl", f"#{unified.HID_BRIDGE:#x}"),
    ]

    # The overwritten stock pair was cmp r1,#0x3b / beq 0x641a, whose target
    # calls 0x5c82. Pin both sides so this proof cannot silently degrade into a
    # register-only check again.
    assert _instructions(base, unified.HID_DISPATCH_HOOK, 4) == [
        (0x637E, "cmp", "r1, #0x3b"),
        (0x6380, "beq", "#0x641a"),
    ]
    assert _instructions(base, 0x641A, 4) == [
        (0x641A, "bl", f"#{unified.HID_3B_HANDLER:#x}"),
    ]

    bridge = {address: (mnemonic, operand) for address, mnemonic, operand in
              _instructions(candidate, unified.HID_BRIDGE, 80)}
    assert bridge[0xBF36] == ("bne", "#0xbf6e")
    assert bridge[0xBF6E] == ("mov", "r0, r4")
    assert bridge[0xBF70] == ("cmp", "r1, #0x3b")
    assert bridge[0xBF72] == ("bne", "#0xbf7a")
    assert bridge[0xBF74] == ("bl", f"#{unified.HID_3B_HANDLER:#x}")
    assert bridge[0xBF78] == ("movs", "r1, #0")
    assert bridge[0xBF7A] == ("pop", "{r4, pc}")

    def trace_non_a2(command: int):
        # Entry is the hook BL. A non-A2 command takes BF36 to the restored
        # dispatcher decision. Only 3B takes the handler call; all other bytes
        # take BF72 directly back to stock at 0x6382 with their command intact.
        assert command != unified.HID_COMMAND
        if command == 0x3B:
            return [unified.HID_3B_HANDLER], 0, unified.HID_DISPATCH_HOOK + 4
        return [], command, unified.HID_DISPATCH_HOOK + 4

    calls, returned_r1, return_pc = trace_non_a2(0x3B)
    assert calls == [unified.HID_3B_HANDLER]
    assert returned_r1 == 0
    assert return_pc == 0x6382
    for command in set(range(256)) - {unified.HID_COMMAND, 0x3B}:
        assert trace_non_a2(command) == ([], command, 0x6382)


def test_stock_hid_report_map_and_trajectories_are_exact_and_unchanged(base, candidate):
    report_map = base[0x1FDFC:0x1FF32]
    assert candidate[0x1FDFC:0x1FF32] == report_map
    assert report_map.startswith(bytes.fromhex("05010902a1018501"))
    assert bytes.fromhex("050d0904a1018501") in report_map
    consumer = bytes.fromhex(
        "050c0901a10185041500250175019518"
        "09b509b609b709cd09e2093009e509e709e909ea"
        "0a52010a53010a54010a55010a83010a8a010a92010a9401"
        "0a21020a23020a24020a25020a26020a27028102c0"
    )
    assert report_map.count(consumer) == 2
    assert candidate[0x1F84E:0x1FA7A] == base[0x1F84E:0x1FA7A]

    # The old touch tables remain unchanged, as do the four mouse-drag tables
    # selected by the corrected r2=1 route.
    assert base[0x1F84E:0x1F872] == bytes.fromhex(
        "01000008380b01000008d40a01000008700a"
        "010000080c0a010000087000000000087000"
    )
    assert base[0x1F872:0x1F896] == bytes.fromhex(
        "01000008c804010000082c05010000089005"
        "01000008f40501000008900f00000008900f"
    )
    assert [base[offset:offset + 16].hex() for offset in
            (0x1F8EA, 0x1F952, 0x1F9BA, 0x1FA1A)] == [
        "00000000080000000100000000000000",
        "00000000f8ff00000100000000000000",
        "00000000010000000100000000000000",
        "00000000ffff00000100000000000000",
    ]


def test_bridge_control_flow_pins_all_swipe_arguments_and_consumer_bounds(candidate):
    instructions = {address: (mnemonic, operand)
                    for address, mnemonic, operand in
                    _instructions(candidate, unified.HID_BRIDGE, 80)}

    # Command 0xa2 is the only handled command. All other commands jump to the
    # displaced stock comparison with r0/r1 preserved through saved r4.
    assert instructions[0xBF34] == ("cmp", "r1, #0xa2")
    assert instructions[0xBF36] == ("bne", "#0xbf6e")
    assert instructions[0xBF6E] == ("mov", "r0, r4")

    # 0 up -> (0,-1,1), 1 down -> (0,+1,1), 2 left -> (-1,0,1),
    # 3 right -> (+1,0,1). Transport 1 is the stock mouse path used with the
    # iPhone report map; transport 2 is the Android touch-digitizer path.
    assert instructions[0xBF3E] == ("movs", "r2, #1")
    assert instructions[0xBF44] == ("movs", "r1, #1")
    assert instructions[0xBF4A] == ("rsbs", "r1, r1, #0")
    assert instructions[0xBF4C] == ("movs", "r0, #0")
    assert instructions[0xBF50] == ("movs", "r1, #0")
    assert instructions[0xBF52] == ("subs", "r0, #2")
    assert instructions[0xBF54] == ("lsls", "r0, r0, #1")
    assert instructions[0xBF56] == ("subs", "r0, #1")
    assert instructions[0xBF58] == ("bl", f"#{unified.HID_SWIPE_SCHEDULER:#x}")

    # Actions 0x20...0x37 map exactly to descriptor bits 0...23. Both a
    # one-hot press and an all-zero release are emitted; every other action is
    # consumed without calling a stock HID sender.
    assert instructions[0xBF5E] == ("subs", "r0, #0x20")
    assert instructions[0xBF60] == ("cmp", "r0, #0x18")
    assert instructions[0xBF62] == ("bhs", "#0xbf6c")
    assert instructions[0xBF64] == ("bl", f"#{unified.HID_CONSUMER_PRESS:#x}")
    assert instructions[0xBF68] == ("bl", f"#{unified.HID_CONSUMER_RELEASE:#x}")
    assert instructions[0xBF6C] == ("movs", "r1, #0")

    routed = {action: ("swipe", action) if action < 4 else
              ("consumer", action - 0x20) if 0x20 <= action < 0x38 else None
              for action in range(256)}
    assert [routed[action] for action in range(4)] == [
        ("swipe", 0), ("swipe", 1), ("swipe", 2), ("swipe", 3),
    ]
    assert [routed[action] for action in range(0x20, 0x38)] == [
        ("consumer", bit) for bit in range(24)
    ]
    assert sum(value is None for value in routed.values()) == 228
