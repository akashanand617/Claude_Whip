"""Early legacy raw/diagnostic retirement through exact stock callback instructions.

OFF-RING: only emulator memory receives one fixed BL edit. The compiled helper
is unlinked, not a production capability. Ordinary dispatch and ROM logging are
explicit boundaries, not Health/DFU functionality proofs or real GATT delivery.
"""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from probe.unified_build import SOURCES, UNLINKED_CANDIDATES
from tests.test_fwstock_link import STOCK, DESCRIPTOR
from whip.fwcontinuity import BIAS, ProofError
from whip.fwoptical_io import _bl
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwunified import STOCK_SHA256

ROOT = Path(__file__).resolve().parents[1]
SITE = 0x7B0A
ORIGINAL = bytes.fromhex("fef78af8")
MODE, PACKET, STACK, STOP = 0x208C44, 0x220020, 0x22F000, 0x3FFF0
RETIRED = {0xA1, 0xBF, 0xCE, 0xCD}


@pytest.fixture(scope="module")
def legacy_build(tmp_path_factory):
    clang = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    if not clang or not zig:
        pytest.skip("reviewed Clang/Zig required")
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    assert "stock_legacy_gate" not in SOURCES
    assert "stock_legacy_gate" in UNLINKED_CANDIDATES
    files = [Path(__file__), ROOT / "probe/unified_build.py", ROOT / "whip/fwoptical_io.py",
             ROOT / "whip/fwstock_link.py", ROOT / "whip/fwproof_guard.py",
             ROOT / "tests/native/arm_proof.ld",
             *(ROOT / f"firmware/unified/stock_legacy_gate.{ext}" for ext in ("c", "h"))]
    sources = InputSnapshot({str(p.relative_to(ROOT)): p for p in files})
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig)})
    out = tmp_path_factory.mktemp("stock-legacy-gate")
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding",
             "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fstack-usage",
             "-I", str(ROOT / "firmware/unified")]
    obj, repeat = out / "stock_legacy_gate.o", out / "repeat.o"
    for path in (obj, repeat):
        subprocess.run([clang, *flags, "-c", str(ROOT / "firmware/unified/stock_legacy_gate.c"),
                        "-o", str(path)], check=True)
    assert obj.read_bytes() == repeat.read_bytes()
    entry = out / "entry.o"
    subprocess.run([clang, *flags, "-x", "c", "-c", "-", "-o", str(entry)],
                   input="void wr_init(void) {}\n", text=True, check=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out / "cache"), ZIG_LOCAL_CACHE_DIR=str(out / "local"))
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
            "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,-e,wr_init",
            "-Wl,--build-id=none", "-Wl,--no-undefined"]
    target, second = out / "legacy-ARTIFICIAL-NOT-INSTALLABLE.elf", out / "repeat.elf"
    for p, o in ((target, obj), (second, repeat)):
        subprocess.run([*link, "-o", str(p), str(o), str(entry)], env=env, check=True)
    assert target.read_bytes() == second.read_bytes()
    sources.verify(); tools.verify()
    return {"elf": target.read_bytes(), "directory": out}


class LegacyThumb:
    """Only callback, original gate and compiled helper may execute.

    Reaching the legacy dispatcher is recorded and returns a fixture. No
    dispatcher prelude, diagnostic handler, queue or sensor call is admitted.
    This witnesses which commands reach that boundary, not their downstream
    behavior. The original stock runner supplies the comparison for callback
    errors and all non-retired opcodes.
    """
    def __init__(self, raw, *, patched=True):
        import unicorn as u
        from unicorn import arm_const as a
        assert hashlib.sha256(STOCK).hexdigest() == STOCK_SHA256
        assert hashlib.sha256(STOCK[0x7ACE:0x7B22]).hexdigest() == \
            "5532f52924e801f3769c205100ce0e5f2201e1f106b281a0ea3a0dcfeac1d36b"
        assert hashlib.sha256(STOCK[0x5C22:0x5C32]).hexdigest() == \
            "8a59a3917bd9679488905527b5ea3f887f841a2d2bac1697d8c47c6074925883"
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, STOCK)
        self.uc.mem_map(0x200000, 0x30000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x1000000, 0x10000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        elf = ELFFile(BytesIO(raw))
        for s in elf.iter_segments():
            if s["p_type"] != "PT_LOAD" or not s["p_memsz"]: continue
            lo, size = s["p_vaddr"], s["p_memsz"]
            assert 0x1000000 <= lo < lo + size <= 0x1010000
            assert not s["p_flags"] & 2 and s["p_filesz"] == size
            self.uc.mem_write(lo, s.data())
        helper = next(s for s in elf.get_section_by_name(".symtab").iter_symbols()
                      if s.name == "wlg_receive")
        self.helper, self.helper_size = helper["st_value"], helper["st_size"]
        assert self.helper & 1 and self.helper_size > 0
        if patched:
            assert STOCK[SITE:SITE + 4] == ORIGINAL
            self.uc.mem_write(BIAS + SITE, _bl(BIAS + SITE, self.helper))
        self.dispatches, self.logs, self.reads, self.writes, self.executed = [], [], [], [], []
        self.dfu_receives = []
        self.flip_on_gate = None
        self.returned, self.stack_low = False, STACK
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)
        self.uc.mem_write(MODE, b"\0")
        self.uc.mem_write(PACKET - 8, b"\xa5" * 32)

    def _return(self, result):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, result)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _code(self, uc, address, size, _):
        self.stack_low = min(self.stack_low, uc.reg_read(self.a.UC_ARM_REG_SP))
        self.executed.append(address)
        if address == STOP:
            self.returned = True
            uc.emu_stop(); return
        if address == BIAS + 0x5C22 and self.flip_on_gate is not None:
            uc.mem_write(MODE, bytes([self.flip_on_gate]))
        if address == BIAS + 0x5882:
            self.dispatches.append((uc.reg_read(self.a.UC_ARM_REG_R0),
                                    uc.reg_read(self.a.UC_ARM_REG_R1)))
            self._return(0xD00DFEED)  # explicit dispatcher boundary, no prelude
            return
        if address == BIAS + 0x823E:
            self.dfu_receives.append((uc.reg_read(self.a.UC_ARM_REG_R0),
                                     uc.reg_read(self.a.UC_ARM_REG_R1)))
            self._return(0xD00DFEED)  # separate BC reassembly boundary, NOT OTA proof
            return
        if address == 0x5AA8:
            self.logs.append(tuple(uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0,
                self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2, self.a.UC_ARM_REG_R3)))
            self._return(0xACCE55); return  # explicit ROM logging boundary
        lo = self.helper & ~1
        if lo <= address < address + size <= lo + self.helper_size: return
        if any(BIAS + lo <= address < address + size <= BIAS + hi
               for lo, hi in ((0x7ACE, 0x7B22), (0x5C22, 0x5C32), (0x79B6, 0x7A0C))): return
        raise ProofError(f"unreviewed legacy execution {address:#x}")

    def _read(self, uc, access, address, size, value, _):
        self.reads.append((address, size))
        if ((BIAS <= address < address + size <= BIAS + len(STOCK)) or
                (0x1000000 <= address < address + size <= 0x1010000) or
                (STACK - 128 <= address < address + size <= STACK + 16) or
                (address == MODE and size == 1) or (address == PACKET and size == 1)):
            return
        raise ProofError(f"unexpected legacy data read {address:#x}/{size}")

    def _write(self, uc, access, address, size, value, _):
        self.writes.append((address, size))
        if not STACK - 128 <= address < address + size <= STACK:
            raise ProofError(f"legacy wrote outside stack {address:#x}/{size}")

    def run(self, opcode, *, length=16, pointer=PACKET, attribute=2, mode=0, mask=0,
            direct=False, dfu=False):
        a, uc = self.a, self.uc
        uc.mem_write(PACKET, bytes([opcode]) + bytes(range(1, 16)))
        uc.mem_write(MODE, bytes([mode]))
        before = bytes(uc.mem_read(PACKET - 8, 32))
        uc.mem_write(STACK, struct.pack("<4I", length, pointer, 0xFACE1234, 0xABCDEF01))
        registers = (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)
        for reg, val in zip(registers, (pointer, length, attribute, 0x2468)):
            uc.reg_write(reg, val)
        saved = [getattr(a, f"UC_ARM_REG_R{i}") for i in range(4, 12)]
        for i, reg in enumerate(saved): uc.reg_write(reg, 0x33440000 + i)
        uc.reg_write(a.UC_ARM_REG_PRIMASK, mask)
        uc.reg_write(a.UC_ARM_REG_SP, STACK)
        uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
        assert not (direct and dfu)
        target = self.helper if direct else BIAS + (0x79B6 if dfu else 0x7ACE) + 1
        try:
            uc.emu_start(target, 0xFFFFFFFF, count=5000)
        except self.u.UcError as exc:
            raise ProofError(f"unmapped/invalid legacy instruction: {exc}") from exc
        assert self.returned and uc.reg_read(a.UC_ARM_REG_SP) == STACK
        if dfu:
            assert not self.dispatches and (self.helper & ~1) not in self.executed
        else:
            assert not self.dfu_receives
        assert [uc.reg_read(r) for r in saved] == [0x33440000 + i for i in range(8)]
        # On supported attribute 2 the stock callback restores its saved R3.
        # Error/logging paths reuse that slot; R3 is caller-saved there.
        if not direct and attribute == 2: assert uc.reg_read(a.UC_ARM_REG_R3) == 0x2468
        assert uc.reg_read(a.UC_ARM_REG_PRIMASK) == mask
        assert bytes(uc.mem_read(PACKET - 8, 32)) == before
        assert bytes(uc.mem_read(STACK, 16)) == struct.pack("<4I", length, pointer, 0xFACE1234, 0xABCDEF01)
        return uc.reg_read(a.UC_ARM_REG_R0)


def test_candidate_is_unlinked_reproducible_and_rejected_by_production_verifier(legacy_build):
    raw = legacy_build["elf"]
    with pytest.raises(ValueError): inspect_elf(raw, STOCK, DESCRIPTOR)
    e = ELFFile(BytesIO(raw))
    assert all(not s["sh_flags"] & 1 for s in e.iter_sections() if s["sh_flags"] & 2 and s["sh_size"])


def test_exactly_one_complete_uart_bl_changes_only_in_emulator_memory(legacy_build):
    h = LegacyThumb(legacy_build["elf"])
    expected = STOCK[:SITE] + _bl(BIAS + SITE, h.helper) + STOCK[SITE + 4:]
    assert bytes(h.uc.mem_read(BIAS, len(STOCK))) == expected
    # Actual source file and shared rejection entry remain untouched.
    assert (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes() == STOCK
    assert bytes(h.uc.mem_read(BIAS + 0x5C2E, 4)) == bytes.fromhex("28e67047")


@pytest.mark.parametrize("opcode", sorted(RETIRED))
@pytest.mark.parametrize("mode", [0, 1, 255])
def test_same_payload_bytes_on_separate_dfu_callback_do_not_enter_uart_filter(legacy_build, opcode, mode):
    h = LegacyThumb(legacy_build["elf"])
    baseline = LegacyThumb(legacy_build["elf"], patched=False)
    assert h.run(opcode, mode=mode, dfu=True) == baseline.run(opcode, mode=mode, dfu=True) == 0
    assert h.dfu_receives == baseline.dfu_receives == [(PACKET, 16)]
    assert not h.dispatches and not h.logs
    assert (h.helper & ~1) not in h.executed and BIAS + SITE not in h.executed


@pytest.mark.parametrize("mode", [0, 1, 2, 255])
def test_all_256_opcodes_keep_original_callback_behavior_except_four_retired(legacy_build, mode):
    for opcode in range(256):
        baseline = LegacyThumb(legacy_build["elf"], patched=False)
        h = LegacyThumb(legacy_build["elf"])
        expected = baseline.run(opcode, mode=mode)
        assert h.run(opcode, mode=mode) == expected == 0
        assert h.logs == baseline.logs == []
        assert h.dispatches == ([] if opcode in RETIRED else baseline.dispatches)
        assert h.dispatches == ([(PACKET, 16)] if mode != 1 and opcode not in RETIRED else [])
        if opcode in RETIRED or mode == 1:
            assert BIAS + 0x5882 not in h.executed
        if mode == 1: assert (PACKET, 1) not in h.reads


@pytest.mark.parametrize("opcode", [pytest.param(0x15, id="heart-rate-history"),
    pytest.param(0x16, id="heart-rate-settings"), pytest.param(0x43, id="steps-history"),
    pytest.param(0x69, id="realtime-start"), pytest.param(0x6A, id="realtime-measurement")])
def test_retained_ordinary_health_history_settings_reach_original_dispatch_only(legacy_build, opcode):
    h = LegacyThumb(legacy_build["elf"])
    baseline = LegacyThumb(legacy_build["elf"], patched=False)
    assert h.run(opcode) == baseline.run(opcode) == 0
    assert h.dispatches == baseline.dispatches == [(PACKET, 16)]
    assert BIAS + 0x5C22 in h.executed and BIAS + 0x5882 in h.executed
    # Dispatcher itself is a fixture: no stateful prelude, checksum processing,
    # command handler, history result, scheduling or Health operation is proved.
    assert BIAS + 0x5890 not in h.executed and BIAS + 0x8112 not in h.executed


@pytest.mark.parametrize("length", [0, 1, 15, 17, 255, 256, 0x10010, 0xFFFF0010, 0xFFFFFFFF])
@pytest.mark.parametrize("opcode", [*sorted(RETIRED), 0x16])
def test_rejected_full_width_lengths_never_dereference_packet(legacy_build, length, opcode):
    h = LegacyThumb(legacy_build["elf"])
    # Unmapped non-null pointer: merely readable fixture RAM would hide an
    # accidentally early opcode load or a narrowed 16-bit length comparison.
    assert h.run(opcode, length=length, pointer=0xDEAD0010) == 0
    assert not h.dispatches and not h.logs


@pytest.mark.parametrize("length", [0, 16, 0x10010])
def test_stock_mode_one_rejects_before_any_opcode_access(legacy_build, length):
    h = LegacyThumb(legacy_build["elf"])
    assert h.run(0x16, length=length, pointer=0xDEAD0010, mode=1) == 0
    assert not h.dispatches


@pytest.mark.parametrize("pointer,attribute,result", [(0, 2, 0x40D), (PACKET, 0, 0x40A),
    (PACKET, 1, 0x40A), (PACKET, 3, 0x40A), (PACKET, 7, 0), (PACKET, 0x10002, 0x40A)])
def test_callback_null_and_attribute_paths_are_unchanged(legacy_build, pointer, attribute, result):
    for opcode in (0xA1, 0xBF, 0x16):
        h = LegacyThumb(legacy_build["elf"])
        baseline = LegacyThumb(legacy_build["elf"], patched=False)
        assert h.run(opcode, pointer=pointer, attribute=attribute) == result
        assert baseline.run(opcode, pointer=pointer, attribute=attribute) == result
        assert h.logs == baseline.logs and not h.dispatches
        assert h.uc.reg_read(h.a.UC_ARM_REG_R3) == baseline.uc.reg_read(baseline.a.UC_ARM_REG_R3)
        assert h.helper & ~1 not in h.executed and (PACKET, 1) not in h.reads


def test_direct_helper_null_is_defensive_without_inventing_a_callback_error(legacy_build):
    h = LegacyThumb(legacy_build["elf"])
    h.run(0x16, pointer=0, direct=True)
    assert not h.dispatches and not h.logs and (PACKET, 1) not in h.reads


def test_delegation_retains_original_mode_recheck_without_claiming_serialization(legacy_build):
    h = LegacyThumb(legacy_build["elf"]); h.flip_on_gate = 1
    assert h.run(0x16) == 0
    assert (PACKET, 1) in h.reads and not h.dispatches
    assert BIAS + 0x5C22 in h.executed


@pytest.mark.parametrize("opcode", sorted(RETIRED))
@pytest.mark.parametrize("mask", [0, 1])
def test_denial_does_not_change_interrupt_mask_or_touch_nonstack_state(legacy_build, opcode, mask):
    h = LegacyThumb(legacy_build["elf"])
    assert h.run(opcode, mask=mask) == 0
    assert not h.dispatches and not h.logs
    assert all(STACK - 128 <= address < STACK for address, _ in h.writes)


@pytest.mark.parametrize("opcode", sorted(RETIRED))
def test_restoring_original_call_mutant_exposes_raw_or_diagnostic_dispatch(legacy_build, opcode):
    h = LegacyThumb(legacy_build["elf"])
    h.uc.mem_write(BIAS + SITE, ORIGINAL)  # mutant in emulator memory only
    assert h.run(opcode) == 0
    assert h.dispatches == [(PACKET, 16)]
    with pytest.raises(AssertionError): assert not h.dispatches
