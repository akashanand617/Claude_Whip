"""Exact-image proofs for the small Health-default/raw-Gesture candidate."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from whip import fwbuild, fwoptical_unified as unified
from whip.fwindicator import branch_candidate

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "firmware/rt02cr-25hz.bin").read_bytes()
BIAS = unified.BIAS


@pytest.fixture(scope="module")
def candidate():
    return unified.build(BASE)


def test_candidate_is_size_neutral_reproducible_and_container_valid(candidate):
    assert len(candidate) == len(BASE) == unified.BASE_SIZE
    assert unified.build(BASE) == candidate
    assert fwbuild.verify(candidate) == []
    assert hashlib.sha256(candidate).hexdigest() == \
        "7e2b3e2e61906031f5b79262ca39022fc34518ab421f814a586f9e49f8691243"
    assert candidate[0x2248:0x224E] == BASE[0x2248:0x224E]  # 25 Hz timer
    assert candidate[0xBF0A:0xBF0E] == BASE[0xBF0A:0xBF0E]  # ±4 g range
    assert candidate[0x7ED4:0x7EE0] == BASE[0x7ED4:0x7EE0]  # DFU reassembly


def test_only_exact_hooks_retired_database_and_derived_fields_change(candidate):
    patches = unified.patch_map()
    edited = {offset + i for offset, value in patches.items() for i in range(len(value))}
    derived = set(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))
    derived |= set(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    changed = {i for i, (a, b) in enumerate(zip(BASE, candidate)) if a != b}
    assert changed <= edited | derived
    for offset, value in patches.items():
        assert candidate[offset:offset + len(value)] == value
    assert len(unified.HELPER_BLOB) == 184 <= unified.HELPER_CAPACITY
    assert candidate[unified.HELPER_OFFSET + len(unified.HELPER_BLOB):
                     unified.HELPER_OFFSET + unified.HELPER_CAPACITY] == \
        BASE[unified.HELPER_OFFSET + len(unified.HELPER_BLOB):
             unified.HELPER_OFFSET + unified.HELPER_CAPACITY]


def test_helper_assembly_rebuilds_byte_exactly(tmp_path):
    clang = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    if not clang or not zig:
        pytest.skip("reviewed Clang/Zig required")
    obj, elf = tmp_path / "helpers.o", tmp_path / "helpers.elf"
    subprocess.run([clang, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus",
                    "-mthumb", "-ffreestanding", "-c",
                    str(ROOT / "firmware/unified/experiments/unified_mode_helpers.S"),
                    "-o", str(obj)], check=True)
    subprocess.run([zig, "ld.lld", "-T",
                    str(ROOT / "firmware/unified/experiments/unified_mode_helpers.ld"),
                    "--build-id=none", "-o", str(elf), str(obj)], check=True)
    parsed = ELFFile(BytesIO(elf.read_bytes()))
    assert parsed.get_section_by_name(".text").data() == unified.HELPER_BLOB
    symbols = parsed.get_section_by_name(".symtab")
    for name, delta in unified.HELPERS.items():
        symbol, = symbols.get_symbol_by_name(name)
        assert symbol["st_value"] == (BIAS + unified.HELPER_OFFSET + delta) | 1


def test_retired_fee7_database_has_one_known_registration_call_and_no_stored_pointer():
    lo, hi = unified.HELPER_OFFSET, unified.HELPER_OFFSET + unified.HELPER_CAPACITY
    branches, pointers = [], []
    for offset in range(0x450, len(BASE) - 3, 2):
        found = branch_candidate(BASE, offset, BIAS + offset)
        if found and BIAS + lo <= found[1] < BIAS + hi and not lo <= offset < hi:
            branches.append((offset, found[0], found[1] - BIAS))
    for offset in range(len(BASE) - 3):
        value = int.from_bytes(BASE[offset:offset + 4], "little") & ~1
        if BIAS + lo <= value < BIAS + hi and not lo <= offset < hi:
            pointers.append((offset, value - BIAS))
    # Halfword scanning through attribute data produces false conditional
    # candidates, but there is no executable external branch or stored pointer
    # to the database. Registration reaches the FEE7 add function at file
    # 0x7b3a; the candidate replaces that setup BL before overwriting the DB.
    assert not [row for row in branches if row[0] < 0x1E000]
    assert not pointers
    assert BASE[unified.FEE7_SETUP_CALL:unified.FEE7_SETUP_CALL + 4] == bytes.fromhex("00f040fb")


def test_uart_dfu_dis_and_hid_registration_and_uart_callbacks_are_untouched(candidate):
    expected = {
        0x749A: 0x791C,  # UART
        0x74A6: 0x7806,  # DFU
        0x74AE: 0x76EA,  # DIS
        0x74BE: 0x142B8, # HID
    }
    for site, target in expected.items():
        decoded = branch_candidate(candidate, site, BIAS + site)
        assert decoded == ("bl", BIAS + target)
        assert candidate[site:site + 4] == BASE[site:site + 4]
    assert candidate[0x1F074:0x1F128] == BASE[0x1F074:0x1F128]
    assert candidate[0x1F11C:0x1F128] == bytes.fromhex(
        "31d882005bd88200afd88200"
    )


def test_retired_fee7_callbacks_and_add_function_have_no_hidden_callers():
    expected_pointers = {0x79D2: [0x1F224], 0x7A7C: [0x1F228], 0x7AEA: [0x1F22C]}
    for target, expected in expected_pointers.items():
        branches = []
        for offset in range(0x450, len(BASE) - 3, 2):
            found = branch_candidate(BASE, offset, BIAS + offset)
            if found and (found[1] & ~1) == BIAS + target:
                branches.append(offset)
        pointers = [offset for offset in range(len(BASE) - 3)
                    if (int.from_bytes(BASE[offset:offset + 4], "little") & ~1)
                    == ((BIAS + target) & ~1)]
        assert branches == []
        assert pointers == expected

    callers = []
    for offset in range(0x450, len(BASE) - 3, 2):
        found = branch_candidate(BASE, offset, BIAS + offset)
        if found and (found[1] & ~1) == BIAS + 0x7B3A:
            callers.append((offset, found[0]))
    assert callers == [(unified.FEE7_SETUP_CALL, "bl")]


class Harness:
    STOP = 0x30000
    STACK = 0x21F000
    SENSOR_SETUP = 0x829C58
    CHIP_WRITE = 0x834C92
    ORIGINAL_DISCONNECT = 0x82CFF2
    TIMER_STOP = 0x829CE8

    def __init__(self, image):
        import unicorn as u
        from unicorn import arm_const as a
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, image)
        self.uc.mem_map(0x200000, 0x20000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.calls, self.stops, self.points = [], [], set()
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)

    def _return(self, value=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _code(self, uc, address, size, _):
        if address == self.STOP or address in self.points:
            self.stops.append(address); uc.emu_stop(); return
        if address == self.CHIP_WRITE:
            r0 = uc.reg_read(self.a.UC_ARM_REG_R0)
            r1 = uc.reg_read(self.a.UC_ARM_REG_R1)
            r2 = uc.reg_read(self.a.UC_ARM_REG_R2)
            self.calls.append((address, r0, r2, bytes(uc.mem_read(r1, r2))))
            self._return(0x1234); return
        if address in (self.SENSOR_SETUP, self.ORIGINAL_DISCONNECT, self.TIMER_STOP):
            self.calls.append((address, uc.reg_read(self.a.UC_ARM_REG_R0)))
            self._return(); return

    def call(self, offset, *args, mode=0, link=2, r4=0, r7=None, points=()):
        a, uc = self.a, self.uc
        uc.mem_write(0x209CAC, bytes([mode]))
        uc.mem_write(0x209E09, bytes([link]))
        for register, value in zip((a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                                    a.UC_ARM_REG_R2, a.UC_ARM_REG_R3),
                                   (*args, 0, 0, 0, 0)):
            uc.reg_write(register, value)
        for i, register in enumerate((a.UC_ARM_REG_R4, a.UC_ARM_REG_R5,
                                      a.UC_ARM_REG_R6, a.UC_ARM_REG_R7)):
            value = r4 if i == 0 else (r7 if i == 3 and r7 is not None else 0xA500 + i)
            uc.reg_write(register, value)
        uc.reg_write(a.UC_ARM_REG_SP, self.STACK)
        uc.reg_write(a.UC_ARM_REG_LR, self.STOP | 1)
        self.calls.clear(); self.stops.clear(); self.points = set(points)
        uc.emu_start((BIAS + offset) | 1, 0xFFFFFFFF, count=5000)
        return uc.reg_read(a.UC_ARM_REG_R0)


@pytest.mark.parametrize("operation", [0, 1, 2, 3, 255])
@pytest.mark.parametrize("mode", [0, 1, 3, 5, 255])
def test_non_gesture_chip_control_is_exactly_stock(candidate, operation, mode):
    original, patched = Harness(BASE), Harness(candidate)
    assert patched.call(unified.CHIP_CONTROL, operation, mode=mode) == \
        original.call(unified.CHIP_CONTROL, operation, mode=mode)
    assert patched.calls == original.calls
    assert patched.uc.reg_read(patched.a.UC_ARM_REG_SP) == patched.STACK


def test_gesture_mode_maps_only_chip_run_to_stop(candidate):
    for operation, expected in ((0, 0), (1, 0), (2, 0xA5), (3, None)):
        h = Harness(candidate)
        result = h.call(unified.CHIP_CONTROL, operation, mode=4)
        if expected is None:
            assert result == 1 and not h.calls
        else:
            assert h.calls == [(h.CHIP_WRITE, 0x7B, 1, bytes([expected]))]
            assert result == 0x1234


@pytest.mark.parametrize("mode", [0, 1, 3, 5, 255])
def test_sensor_gate_recreates_stock_prologue_outside_gesture(candidate, mode):
    h = Harness(candidate)
    h.call(unified.SENSOR_ENTRY, 0x40, mode=mode, points=(BIAS + 0xF694,))
    assert h.calls == [(h.SENSOR_SETUP, 0x40)] and h.stops == [BIAS + 0xF694]
    assert h.uc.reg_read(h.a.UC_ARM_REG_R4) == 0x40
    assert h.uc.reg_read(h.a.UC_ARM_REG_SP) == h.STACK - 24
    assert int.from_bytes(h.uc.mem_read(h.STACK - 4, 4), "little") == h.STOP | 1


def test_sensor_gate_returns_without_optical_work_in_gesture(candidate):
    h = Harness(candidate)
    h.call(unified.SENSOR_ENTRY, 0xFFFF, mode=4)
    assert not h.calls and h.stops == [h.STOP]
    assert h.uc.reg_read(h.a.UC_ARM_REG_SP) == h.STACK


@pytest.mark.parametrize("mode", [0, 4, 255])
@pytest.mark.parametrize("link", [0, 2, 3])
@pytest.mark.parametrize("pending", [0, 1, 255])
def test_idle_guard_changes_only_connected_gesture(candidate, mode, link, pending):
    state = 0x20BDC4
    h = Harness(candidate)
    h.uc.mem_write(state + 6, bytes([pending]))
    result = h.call(unified.HELPER_OFFSET + unified.HELPERS["idle_guard"],
                    mode=mode, link=link, r4=state)
    assert result == (0 if mode == 4 and link == 2 else pending)
    assert bytes(h.uc.mem_read(state + 6, 1)) == bytes([pending])


@pytest.mark.parametrize("mode", [0, 1, 3, 5, 255])
def test_disconnect_preserves_non_gesture_modes(candidate, mode):
    h = Harness(candidate)
    h.call(unified.DISCONNECT_HOOK, mode=mode, points=(BIAS + 0x6922,))
    assert h.calls == [(h.ORIGINAL_DISCONNECT, 0)]
    assert bytes(h.uc.mem_read(0x209CAC, 1)) == bytes([mode])


def test_disconnect_clears_gesture_and_stops_its_timer(candidate):
    h = Harness(candidate)
    h.call(unified.DISCONNECT_HOOK, mode=4, points=(BIAS + 0x6922,))
    assert h.calls == [(h.ORIGINAL_DISCONNECT, 0), (h.TIMER_STOP, 0x209CBC)]
    assert bytes(h.uc.mem_read(0x209CAC, 1)) == b"\0"


def test_raw_start_sets_mode_before_existing_wake(candidate):
    h = Harness(candidate)
    wake = BIAS + 0xCB06
    h.points = {wake}
    h.call(unified.RAW_START, mode=0, r7=0x209CAC, points=(wake,))
    assert h.stops == [wake]
    assert bytes(h.uc.mem_read(0x209CAC, 1)) == b"\x04"
