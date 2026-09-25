"""OFF-RING: actual stock wait/branch/waker plus the unattached C wrapper.

The ROM semaphore and seven stock-body callees are explicit contract fixtures,
not captured execution. The strong supervisor provider is proof-only C that
increments an artificial counter; it is NOT wd_tick, a coordinator or Health.
Only one stock BL is changed, in emulator memory. No firmware file is emitted.
"""
from collections import deque
from io import BytesIO
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess

from elftools.elf.elffile import ELFFile
import pytest

from whip.fwoptical_io import _bl
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb, ThumbProofError

ROOT = Path(__file__).resolve().parents[1]
STOCK_PATH = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
STOCK_SHA256 = "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0"
BIAS = 0x825FB0
WAIT_SITE = 0x135C
WAIT_BEFORE = bytes.fromhex("ecf728d8")
MARKER, HANDLE_SLOT, HANDLE = 0x208C88, 0x208C90, 0x221234
BODY = (0x657C, 0xCD60, 0x905C, 0x1202, 0x343A, 0x1279E, 0x3FD2)
BODY_SITES = dict(zip(BODY, (0x1366, 0x136E, 0x1374, 0x137A, 0x1382, 0x138A, 0x1392)))
MARKS = (0, 1, 2, 3, 4, 6, 7, 8)
ABI_SOURCE = "void wr_init(void) {}\nunsigned proof_runtime_size(void) { return 64; }\n"
PROOF_PROVIDER = """
/* TEST ONLY: no scheduler, lifecycle, clock, ROM, RTOS or hardware provider. */
void wuw_supervise(void) { ++*(volatile unsigned *)0x20000100; }
"""


@pytest.fixture(scope="module")
def wake_build(tmp_path_factory):
    clang = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    assert clang and zig, "reviewed Clang/Zig required; never skip"
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    directory = tmp_path_factory.mktemp("supervisor-wake")
    files = [Path(__file__), STOCK_PATH,
             *(ROOT / f"firmware/unified/stock_supervisor_wait.{ext}" for ext in ("c", "h")),
             *(ROOT / p for p in ("whip/fwthumb.py", "whip/fwoptical_io.py",
               "whip/fwproof_guard.py", "whip/fwstock_link.py", "tests/native/arm_proof.ld",
               "firmware/research/2026-09-23/bank0-descriptor/configuration.json"))]
    inputs = InputSnapshot({str(p.relative_to(ROOT)): p for p in files})
    tools = InputSnapshot({"clang": Path(clang), "zig": Path(zig)})
    snapshots, objects = [], []
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
             "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra",
             "-Werror", "-fstack-usage", "-I", str(ROOT / "firmware/unified")]
    for name, source in (("stock_supervisor_wait", None), ("abi", ABI_SOURCE),
                         ("proof_only_supervisor_provider", PROOF_PROVIDER)):
        pair = [directory / (name + suffix) for suffix in (".o", "-repeat.o")]
        for obj in pair:
            command = [clang, *flags]
            if source is None:
                command += ["-c", str(ROOT / "firmware/unified/stock_supervisor_wait.c")]
            else:
                command += ["-x", "c", "-c", "-"]
            subprocess.run([*command, "-o", str(obj)], input=source, text=True, check=True)
            snapshots.append(InputSnapshot({p.name: p for p in (obj, obj.with_suffix(".su"))}))
        assert pair[0].read_bytes() == pair[1].read_bytes()
        objects.append(pair[0])
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(directory / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(directory / "local"))
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
            "-nostdlib", "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
            "-Wl,-e,wr_init", "-Wl,--build-id=none", "-Wl,--no-undefined"]
    missing = directory / "missing-supervisor-REFUSED.elf"
    refused = subprocess.run([*link, "-o", str(missing), *map(str, objects[:2])],
                             env=env, capture_output=True, text=True)
    assert refused.returncode and not missing.exists()
    assert "wuw_supervise" in refused.stderr
    elfs = [directory / name for name in ("supervisor-wake-ARTIFICIAL-NOT-INSTALLABLE.elf", "repeat.elf")]
    for elf in elfs:
        subprocess.run([*link, "-o", str(elf), *map(str, objects)], env=env, check=True)
        snapshots.append(InputSnapshot({elf.name: elf}))
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    for snapshot in (inputs, tools, *snapshots):
        snapshot.verify()
    yield {"elf": elfs[0].read_bytes(), "directory": directory, "refused": refused}
    for snapshot in (inputs, tools, *snapshots):
        snapshot.verify()


class WakeThumb(RuntimeThumb):
    """Minimal extension: exact loop/waker and named external boundaries only."""

    def __init__(self, elf, *, patched=True):
        self.trace, self.markers = [], []
        self.take_results = deque()
        self.take_context = self.poll_context = None
        self.poll_return = None
        self.loop_limit = self.loop_tops = 0
        self.loop_stopped = self.body_blocked = False
        self.block_body = None
        self.give_result = 1
        self.patched = patched
        super().__init__(elf)
        self.write_word(0, 0)
        self.stock = STOCK_PATH.read_bytes()
        assert hashlib.sha256(self.stock).hexdigest() == STOCK_SHA256
        assert self.stock[WAIT_SITE:WAIT_SITE + 4] == WAIT_BEFORE
        assert self.stock[0x1356:0x135C] == bytes.fromhex("0021c943a068")
        assert self.stock[0x1360:0x1364] == bytes.fromhex("0028f8d0")
        self.uc.mem_map(0x820000, 0x30000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, self.stock)
        self.uc.mem_map(0x208000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_map(0x13000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        self.uc.mem_write(HANDLE_SLOT, struct.pack("<I", HANDLE))
        self.uc.mem_write(MARKER, b"\xA5")
        self.edit = _bl(BIAS + WAIT_SITE, self.symbols["wuw_take"]) if patched else WAIT_BEFORE
        self.uc.mem_write(BIAS + WAIT_SITE, self.edit)
        expected = self.stock[:WAIT_SITE] + self.edit + self.stock[WAIT_SITE + 4:]
        assert bytes(self.uc.mem_read(BIAS, len(self.stock))) == expected
        self.symbols["proof_stock_waker"] = BIAS + 0x1179

    def context(self):
        return (self.uc.reg_read(self.a.UC_ARM_REG_IPSR),
                self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK))

    def set_context(self, context):
        self.uc.reg_write(self.a.UC_ARM_REG_IPSR, context[0])
        self.uc.reg_write(self.a.UC_ARM_REG_PRIMASK, context[1])

    def fixture_return(self, value):
        for reg in (self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2, self.a.UC_ARM_REG_R3):
            self.uc.reg_write(reg, 0xDEADC0DE)
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _code(self, uc, address, size, opaque):
        if self.poll_return == address:
            self.poll_return = None
            if self.poll_context is not None:
                self.set_context(self.poll_context)
        if address == (self.symbols.get("wuw_supervise", 0) & ~1):
            assert self.context() == (0, 0)
            self.trace.append(("proof-only supervisor counter",))
            self.poll_return = uc.reg_read(self.a.UC_ARM_REG_LR) & ~1
        if address == 0x13360:
            assert self.take_results, "unexpected additional semaphore take"
            args = (uc.reg_read(self.a.UC_ARM_REG_R0), uc.reg_read(self.a.UC_ARM_REG_R1))
            assert args == (HANDLE, 100 if self.patched else 0xFFFFFFFF)
            self.trace.append(("ROM take contract fixture", *args))
            result = self.take_results.popleft()
            if self.take_context is not None:
                self.set_context(self.take_context)
            self.fixture_return(result)
            return
        if address == 0x13388:
            assert uc.reg_read(self.a.UC_ARM_REG_R0) == HANDLE
            assert uc.reg_read(self.a.UC_ARM_REG_LR) == (BIAS + 0x1186) | 1
            self.trace.append(("ROM give contract fixture", HANDLE))
            self.fixture_return(self.give_result)
            return
        if address - BIAS in BODY:
            target = address - BIAS
            assert uc.reg_read(self.a.UC_ARM_REG_LR) == (BIAS + BODY_SITES[target] + 4) | 1
            self.trace.append(("stock body call boundary fixture", target,
                               bytes(uc.mem_read(MARKER, 1))[0]))
            if target == self.block_body:
                self.body_blocked = True
                uc.emu_stop()
            else:
                self.fixture_return(0xCAFEBABE)
            return
        if address == BIAS + 0x1356 and self.loop_limit:
            self.loop_tops += 1
            if self.loop_tops == self.loop_limit + 1:
                self.loop_stopped = True
                uc.emu_stop()
                return
        if any(lo <= address and address + size <= hi for lo, hi in
               ((BIAS + 0x1350, BIAS + 0x139C), (BIAS + 0x1178, BIAS + 0x1188))):
            self.instruction_count += 1
            return
        super()._code(uc, address, size, opaque)

    def _read(self, uc, access, address, size, value, opaque):
        if (address, size) in ((BIAS + 0x13EC, 4), (HANDLE_SLOT, 4)):
            return
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        if (address, size) == (MARKER, 1):
            self.markers.append(value)
            return
        super()._write(uc, access, address, size, value, opaque)

    def loop(self, results):
        assert results
        self.take_results.extend(results)
        self.loop_limit = len(results)
        self.loop_tops = 0
        self.loop_stopped = self.body_blocked = False
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_R5, 3)  # original task prologue value
        self.uc.emu_start((BIAS + 0x1350) | 1, 0xFFFFFFFF, count=10000)
        assert self.loop_stopped or self.body_blocked, "bounded stock witness did not stop"
        assert self.uc.reg_read(self.a.UC_ARM_REG_SP) == self.STACK
        if not self.body_blocked:
            assert not self.take_results
        self.loop_limit = 0

    def body_trace(self):
        return [item for item in self.trace if item[0] == "stock body call boundary fixture"]


def test_reproduced_candidate_requires_strong_provider_and_is_not_production(wake_build):
    obj = ELFFile(BytesIO((wake_build["directory"] / "stock_supervisor_wait.o").read_bytes()))
    provider = obj.get_section_by_name(".symtab").get_symbol_by_name("wuw_supervise")
    assert len(provider) == 1
    assert provider[0]["st_shndx"] == "SHN_UNDEF"
    assert provider[0]["st_info"]["bind"] == "STB_GLOBAL"
    assert not any(s["sh_size"] and s["sh_flags"] & 3 == 3 for s in obj.iter_sections())
    assert wake_build["refused"].returncode != 0
    with pytest.raises(ValueError):
        inspect_elf(wake_build["elf"], STOCK_PATH.read_bytes(),
                    (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes())


@pytest.mark.parametrize("result", [0, 1, 2, 0x80000000, 0xFFFFFFFF])
def test_exact_stock_single_bl_edit_polls_and_preserves_original_body_branch(wake_build, result):
    old = WakeThumb(wake_build["elf"], patched=False)
    new = WakeThumb(wake_build["elf"])
    old.loop([result]); new.loop([result])
    assert new.word(0) == 1 and old.word(0) == 0
    assert new.body_trace() == old.body_trace()
    assert new.markers == old.markers == (list(MARKS) if result else [])
    assert [item[1] for item in new.body_trace()] == (list(BODY) if result else [])
    assert new.trace[:2] == [("ROM take contract fixture", HANDLE, 100),
                             ("proof-only supervisor counter",)]
    assert new.context() == old.context() == (0, 0)


@pytest.mark.parametrize("result", [0, 1, 2, 0x80000000, 0xFFFFFFFF])
def test_wrapper_returns_raw_take_word_unchanged(wake_build, result):
    h = WakeThumb(wake_build["elf"])
    h.take_results.append(result)
    assert h.call("wuw_take", HANDLE, 0xFFFFFFFF) == result
    assert h.word(0) == 1 and len(h.trace) == 2


def test_persistent_idle_and_signal_sequence_has_no_body_on_failed_take(wake_build):
    h = WakeThumb(wake_build["elf"])
    h.loop([0, 0, 1, 0, 2, 0])
    assert h.word(0) == 6
    assert h.markers == list(MARKS) * 2
    assert [item[1] for item in h.body_trace()] == list(BODY) * 2
    # Zero is only a failed-take fixture: no elapsed-time or timeout assertion.
    assert sum(item[0] == "ROM take contract fixture" for item in h.trace) == 6


@pytest.mark.parametrize("handle,wait,context", [
    (0, 0xFFFFFFFF, (0, 0)), (HANDLE, 0, (0, 0)),
    (HANDLE, 100, (0, 0)), (HANDLE, 0xFFFFFFFE, (0, 0)),
    (HANDLE, 0xFFFFFFFF, (0, 1)), (HANDLE, 0xFFFFFFFF, (1, 0)),
    (HANDLE, 0xFFFFFFFF, (15, 1)),
])
def test_invalid_original_contract_calls_neither_rom_nor_supervisor(wake_build, handle, wait, context):
    h = WakeThumb(wake_build["elf"])
    h.set_context(context)
    assert h.call("wuw_take", handle, wait) == 0
    assert h.context() == context and h.word(0) == 0 and not h.trace


@pytest.mark.parametrize("context", [(0, 1), (15, 0), (15, 1)])
@pytest.mark.parametrize("where", ["take", "supervisor"])
def test_changed_context_fails_closed_without_mask_repair_or_stock_body(wake_build, where, context):
    h = WakeThumb(wake_build["elf"])
    if where == "take":
        h.take_context = context
    else:
        h.poll_context = context
    h.loop([1])
    assert h.context() == context and not h.body_trace() and not h.markers
    assert h.word(0) == int(where == "supervisor")
    assert len(h.trace) == 1 + int(where == "supervisor")


@pytest.mark.parametrize("handle,given", [(0, 0), (HANDLE, 0), (HANDLE, 1), (HANDLE, 0xFFFFFFFF)])
def test_original_waker_null_guard_and_raw_give_return_are_unchanged(wake_build, handle, given):
    h = WakeThumb(wake_build["elf"])
    h.uc.mem_write(HANDLE_SLOT, struct.pack("<I", handle))
    h.give_result = given
    assert h.call("proof_stock_waker") == (given if handle else 0)
    assert h.trace == ([("ROM give contract fixture", HANDLE)] if handle else [])
    assert h.word(0) == 0 and not h.markers


def test_blocking_stock_body_still_prevents_the_next_supervisor_poll(wake_build):
    h = WakeThumb(wake_build["elf"])
    h.block_body = BODY[1]
    h.loop([1, 0])
    assert h.body_blocked and not h.loop_stopped
    assert h.word(0) == 1 and list(h.take_results) == [0]
    assert h.markers == [0, 1]
    assert [item[1] for item in h.body_trace()] == list(BODY[:2])


def test_harness_rejects_unadmitted_execution_and_data(wake_build):
    h = WakeThumb(wake_build["elf"])
    with pytest.raises(ThumbProofError):
        h._code(h.uc, BIAS + 0x139C, 2, None)
    with pytest.raises(ThumbProofError):
        h._read(h.uc, 0, HANDLE_SLOT + 4, 4, 0, None)
    with pytest.raises(ThumbProofError):
        h._write(h.uc, 0, MARKER + 1, 1, 0, None)
