"""Strict emulator for the freestanding unified-runtime TEST ELF, never OTA.

Executes the linked ARM code, including the test C memory primitives. It has
no ROM, RTOS, device, Bluetooth or storage mocks. Artificial code/RAM addresses
are deliberately outside the pinned stock layout; they are not safe allocations.
"""
from __future__ import annotations

from io import BytesIO
import struct


class ThumbProofError(RuntimeError):
    pass


class RuntimeThumb:
    CODE = 0x01000000
    RAM = 0x20000000
    CONTEXT = RAM + 0x100
    BATCH = RAM + 0x2000
    OUTPUT = RAM + 0x3000
    STACK = RAM + 0xFF00
    RETURN = CODE + 0xFF00
    CONTEXT_SIZE_SYMBOL = "proof_runtime_size"
    CONTEXT_MAX_BYTES = 1024

    def __init__(self, elf_bytes: bytes):
        import unicorn as u
        from unicorn import arm_const as a
        from elftools.elf.elffile import ELFFile

        elf = ELFFile(BytesIO(elf_bytes))
        if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != \
                (32, True, "EM_ARM", "ET_EXEC"):
            raise ValueError("requires linked ARM32 little-endian test ELF")
        symtab = elf.get_section_by_name(".symtab")
        if not symtab:
            raise ValueError("test ELF must retain symbols")
        self.symbols = {}
        self.executable = []
        for sym in symtab.iter_symbols():
            if sym.name and sym["st_shndx"] == "SHN_UNDEF":
                raise ValueError(f"unresolved test ELF symbol: {sym.name}")
            if sym["st_info"]["type"] == "STT_FUNC" and sym["st_size"]:
                start = sym["st_value"] & ~1
                end = start + sym["st_size"]
                if not sym["st_value"] & 1 or not self.CODE <= start < end <= self.CODE + 0xF000:
                    raise ValueError("function outside artificial Thumb proof region")
                self.symbols[sym.name] = sym["st_value"]
                self.executable.append((start, end))
        if "wr_init" not in self.symbols or elf["e_entry"] != self.symbols["wr_init"]:
            raise ValueError("unexpected test ELF entry")
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(self.CODE, 0x10000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(self.RAM, 0x10000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.loaded_spans = []
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            start, length = seg["p_vaddr"], seg["p_memsz"]
            if not self.CODE <= start <= start + length <= self.CODE + 0xF000 or seg["p_flags"] & 2:
                raise ValueError("test ELF contains unexpected writable/out-of-region segment")
            self.uc.mem_write(start, seg.data())
            self.loaded_spans.append((start, start + length))
        self.context_size = 0
        self.batch_length = 0
        self.returned = False
        self.instruction_count = 0
        self.stack_low = self.STACK
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)
        self.context_size = self.call(self.CONTEXT_SIZE_SYMBOL)
        if (not 0 < self.context_size <= self.CONTEXT_MAX_BYTES or
                self.CONTEXT + self.context_size + 16 >= self.BATCH):
            raise ValueError("unexpected runtime context size")
        self.uc.mem_write(self.CONTEXT - 16, b"\xA5" * (self.context_size + 32))

    def _code(self, uc, address, size, _):
        if address == self.RETURN:
            self.returned = True
            uc.emu_stop()
            return
        if not any(lo <= address and address + size <= hi for lo, hi in self.executable):
            raise ThumbProofError(f"execution outside linked function at {address:#x}")
        self.instruction_count += 1

    def _write(self, uc, access, address, size, value, _):
        spans = ((self.CONTEXT, self.CONTEXT + self.context_size),
                 (self.OUTPUT, self.OUTPUT + 12),
                 (self.STACK - 0x1000, self.STACK + 32))
        if not any(lo <= address and address + size <= hi for lo, hi in spans):
            raise ThumbProofError(f"write outside context/output/stack at {address:#x}")
        if self.STACK - 0x1000 <= address <= self.STACK:
            self.stack_low = min(self.stack_low, address)

    def _read(self, uc, access, address, size, value, _):
        spans = ((self.CONTEXT, self.CONTEXT + self.context_size),
                 (self.BATCH, self.BATCH + self.batch_length),
                 (self.OUTPUT, self.OUTPUT + 12),
                 (self.STACK - 0x1000, self.STACK + 32), *self.loaded_spans)
        if not any(lo <= address and address + size <= hi for lo, hi in spans):
            raise ThumbProofError(f"read outside populated proof memory at {address:#x}")

    def call(self, name: str, *args: int, budget=100_000) -> int:
        if name not in self.symbols or len(args) > 8:
            raise ValueError("unknown linked function or too many arguments")
        a = self.a
        regs = (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)
        saved = (a.UC_ARM_REG_R4, a.UC_ARM_REG_R5, a.UC_ARM_REG_R6, a.UC_ARM_REG_R7,
                 a.UC_ARM_REG_R8, a.UC_ARM_REG_R9, a.UC_ARM_REG_R10, a.UC_ARM_REG_R11)
        for i, reg in enumerate(regs):
            self.uc.reg_write(reg, args[i] if i < len(args) else 0xCCCCCCCC)
        for i, reg in enumerate(saved):
            self.uc.reg_write(reg, 0xAABB0000 + i)
        self.uc.mem_write(self.STACK, b"\xA5" * 32)
        if len(args) > 4:
            self.uc.mem_write(self.STACK, struct.pack("<" + "I" * (len(args) - 4), *args[4:]))
        self.uc.reg_write(a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(a.UC_ARM_REG_LR, self.RETURN | 1)
        self.returned = False
        try:
            self.uc.emu_start(self.symbols[name], 0xFFFFFFFF, count=budget)
        except self.u.UcError as exc:
            raise ThumbProofError(f"invalid/unmapped ARM execution: {exc}") from exc
        if not self.returned:
            raise ThumbProofError("instruction budget exhausted")
        if self.uc.reg_read(a.UC_ARM_REG_SP) != self.STACK or any(
                self.uc.reg_read(reg) != 0xAABB0000 + i for i, reg in enumerate(saved)):
            raise ThumbProofError("AAPCS stack or callee-saved register corruption")
        if self.context_size:
            for start in (self.CONTEXT - 16, self.CONTEXT + self.context_size):
                if bytes(self.uc.mem_read(start, 16)) != b"\xA5" * 16:
                    raise ThumbProofError("runtime context guard corrupted")
        return self.uc.reg_read(a.UC_ARM_REG_R0)

    def invoke(self, name: str, *args: int) -> int:
        return self.call(name, self.CONTEXT, *args)

    def word(self, offset: int) -> int:
        return struct.unpack("<I", self.uc.mem_read(self.CONTEXT + offset, 4))[0]

    def write_word(self, offset: int, value: int):
        if offset < 0 or offset + 4 > self.context_size:
            raise ValueError("fixture write outside context")
        self.uc.mem_write(self.CONTEXT + offset, struct.pack("<I", value))

    def batch(self, values):
        if not 0 < len(values) <= 32:
            raise ValueError("fixture batch must have 1..32 samples")
        self.uc.mem_write(self.BATCH, b"".join(struct.pack("<hhh", *v) for v in values))
        self.batch_length = len(values) * 6
        return self.BATCH

    def raw_input(self, data: bytes):
        """Populate bounded read-only fixture bytes for larger typed receipts."""
        if type(data) is not bytes or not 0 < len(data) <= self.OUTPUT - self.BATCH:
            raise ValueError("fixture input must fit reserved input region")
        self.uc.mem_write(self.BATCH, data)
        self.batch_length = len(data)
        return self.BATCH

    def output(self):
        raw = self.uc.mem_read(self.OUTPUT, 12)
        return struct.unpack_from("<I", raw)[0], struct.unpack_from("<hhh", raw, 4)
