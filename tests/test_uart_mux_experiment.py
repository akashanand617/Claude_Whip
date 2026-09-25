"""ARM routing proof for the non-installable existing-UART mux experiment."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from tests.test_stock_legacy_gate import (LegacyThumb, PACKET, RETIRED, STACK,
                                         STOP, BIAS)
from tests.test_fwstock_link import STOCK, DESCRIPTOR
from whip.fwstock_link import inspect_elf

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware/unified/experiments/stock_uart_mux.c"
POST = 0x5000


@pytest.fixture(scope="module")
def uart_mux_build(tmp_path_factory):
    clang = shutil.which("clang")
    zig = shutil.which(os.environ.get("WHIP_ZIG", "zig"))
    if not clang or not zig:
        pytest.skip("reviewed Clang/Zig required")
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    out = tmp_path_factory.mktemp("uart-mux-experiment")
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
             "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall",
             "-Wextra", "-Werror", "-fstack-usage", "-I", str(ROOT / "firmware/unified")]
    objects = []
    for index in range(2):
        obj = out / f"mux-{index}.o"
        subprocess.run([clang, *flags, "-c", str(SOURCE), "-o", str(obj)], check=True)
        objects.append(obj)
    assert objects[0].read_bytes() == objects[1].read_bytes()
    binding = out / "binding.o"
    subprocess.run([clang, *flags, "-x", "c", "-c", "-", "-o", str(binding)],
                   input='__asm__(".global wum_post20\\n.set wum_post20,0x5001");\n'
                         'void wr_init(void) {}\n', text=True, check=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(out / "local"))
    elfs = []
    for index, obj in enumerate(objects):
        target = out / f"mux-{index}.elf"
        subprocess.run([zig, "cc", "-target", "thumb-freestanding-eabi",
                        "-mcpu=cortex_m0plus", "-nostdlib",
                        "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
                        "-Wl,-e,wr_init", "-Wl,--build-id=none", "-Wl,--no-undefined",
                        "-o", str(target), str(obj), str(binding)], env=env, check=True)
        elfs.append(target)
    assert elfs[0].read_bytes() == elfs[1].read_bytes()
    return elfs[0].read_bytes()


class UARTMuxThumb(LegacyThumb):
    def __init__(self, raw, *, patched=True):
        self.posts = []
        super().__init__(raw, patched=patched)

    def _code(self, uc, address, size, user):
        if address == POST:
            pointer = uc.reg_read(self.a.UC_ARM_REG_R0)
            self.posts.append(bytes(uc.mem_read(pointer, 20)))
            self._return(0)
            return
        super()._code(uc, address, size, user)

    def _read(self, uc, access, address, size, value, user):
        if PACKET <= address < address + size <= PACKET + 20:
            self.reads.append((address, size))
            return
        super()._read(uc, access, address, size, value, user)

    def run_packet(self, packet, *, mode=0, mask=0):
        assert len(packet) == 20
        a, uc = self.a, self.uc
        uc.mem_write(PACKET, packet)
        uc.mem_write(0x208C44, bytes([mode]))
        before = bytes(uc.mem_read(PACKET - 8, 36))
        uc.mem_write(STACK, struct.pack("<4I", 20, PACKET, 0xFACE1234, 0xABCDEF01))
        for reg, value in zip((a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                               a.UC_ARM_REG_R2, a.UC_ARM_REG_R3),
                              (PACKET, 20, 2, 0x2468), strict=True):
            uc.reg_write(reg, value)
        saved = [getattr(a, f"UC_ARM_REG_R{i}") for i in range(4, 12)]
        for index, reg in enumerate(saved):
            uc.reg_write(reg, 0x33440000 + index)
        uc.reg_write(a.UC_ARM_REG_PRIMASK, mask)
        uc.reg_write(a.UC_ARM_REG_SP, STACK)
        uc.reg_write(a.UC_ARM_REG_LR, STOP | 1)
        uc.emu_start(BIAS + 0x7ACE + 1, 0xFFFFFFFF, count=5000)
        assert self.returned and uc.reg_read(a.UC_ARM_REG_SP) == STACK
        assert [uc.reg_read(reg) for reg in saved] == [0x33440000 + i for i in range(8)]
        assert uc.reg_read(a.UC_ARM_REG_PRIMASK) == mask
        assert bytes(uc.mem_read(PACKET - 8, 36)) == before
        return uc.reg_read(a.UC_ARM_REG_R0)


def test_mux_is_reproducible_92_byte_experiment_and_not_production(uart_mux_build):
    elf = ELFFile(BytesIO(uart_mux_build))
    symbol = next(s for s in elf.get_section_by_name(".symtab").iter_symbols()
                  if s.name == "wlg_receive")
    assert symbol["st_size"] == 92
    with pytest.raises(ValueError):
        inspect_elf(uart_mux_build, STOCK, DESCRIPTOR)


@pytest.mark.parametrize("mode", [0, 1, 255])
@pytest.mark.parametrize("part", [0, 1])
def test_versioned_twenty_byte_request_is_copied_to_mux_only(uart_mux_build, mode, part):
    packet = bytes([0x57, 1, 1, part]) + bytes(range(4, 20))
    h = UARTMuxThumb(uart_mux_build)
    assert h.run_packet(packet, mode=mode) == 0
    assert h.posts == [packet] and not h.dispatches and not h.logs


@pytest.mark.parametrize("field,value", [(0, 0x56), (1, 0), (1, 2), (2, 2), (2, 3)])
@pytest.mark.parametrize("mode", [0, 1, 255])
def test_nonmatching_twenty_byte_packet_never_posts_or_dispatches(
        uart_mux_build, field, value, mode):
    packet = bytearray([0x57, 1, 1, 0] + list(range(4, 20)))
    packet[field] = value
    h = UARTMuxThumb(uart_mux_build)
    assert h.run_packet(bytes(packet), mode=mode) == 0
    assert not h.posts and not h.dispatches and not h.logs


@pytest.mark.parametrize("mode", [0, 1, 255])
def test_all_legacy_opcodes_retain_existing_gate_policy(uart_mux_build, mode):
    for opcode in range(256):
        h = UARTMuxThumb(uart_mux_build)
        baseline = LegacyThumb(uart_mux_build, patched=False)
        assert h.run(opcode, mode=mode) == baseline.run(opcode, mode=mode) == 0
        assert h.dispatches == ([] if opcode in RETIRED else baseline.dispatches)
        assert h.dispatches == ([(PACKET, 16)] if mode != 1 and opcode not in RETIRED else [])
        assert not h.posts


@pytest.mark.parametrize("opcode", sorted(RETIRED) + [0x15, 0x16, 0x43, 0x69, 0x6A])
def test_dfu_payload_never_enters_uart_mux(uart_mux_build, opcode):
    h = UARTMuxThumb(uart_mux_build)
    baseline = LegacyThumb(uart_mux_build, patched=False)
    assert h.run(opcode, dfu=True) == baseline.run(opcode, dfu=True) == 0
    assert h.dfu_receives == baseline.dfu_receives == [(PACKET, 16)]
    assert not h.posts and not h.dispatches
