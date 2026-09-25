"""Strict OFFLINE execution of the pinned, repeated 6076-byte ROM capture.

No BLE, image writer or hardware access. Missing code/data fail closed rather
than becoming zero-filled evidence. Every substituted callee is recorded; SRAM,
queue contents, header bytes and timing are explicitly synthetic fixtures.
"""
from dataclasses import dataclass
import hashlib
import json
import struct

from whip.fwrom_integration import WINDOWS
from whip.fwstock_link import StockAppendThumb
from whip.fwthumb import ThumbProofError

CAPTURE_SHA256 = "d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b"


class ROMBoundaryError(RuntimeError):
    pass


class ROMAssertion(ROMBoundaryError):
    pass


def captured_windows(raw):
    if hashlib.sha256(raw).hexdigest() != CAPTURE_SHA256:
        raise ValueError("requires the exact successful repeated ROM capture")
    capture = json.loads(raw)
    if capture["repeated_equal"] is not True or capture["flash_authorized"] is not False:
        raise ValueError("invalid capture/evidence flags")
    result = {}
    for name, address, size in WINDOWS:
        window = capture["windows"][name]
        data = bytes.fromhex(window["data_hex"])
        if (window["address"] != address or len(data) != size or
                hashlib.sha256(data).hexdigest() != window["sha256"]):
            raise ValueError("invalid captured window")
        result[address] = data
    return result


@dataclass(frozen=True)
class MockCall:
    address: int
    name: str
    registers: tuple[int, ...]


class ROMHarness:
    """Selected captured instructions, explicit fixtures and named boundaries.

    The constructor grants NO executable/readable SRAM by default. fixture()
    admits only the supplied interval; select() admits reviewed function spans
    contained in the capture. Mock functions must be registered explicitly.
    This is not boot/RTOS emulation or physical timing/queue-ownership proof.
    """
    STACK = 0x304000
    STACK_BYTES = 2048
    RETURN = 0x4FFF0

    def __init__(self, capture):
        import unicorn as u
        from unicorn import arm_const as a

        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x50000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x200000, 0x18000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x300000, 0x5000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.windows = captured_windows(capture)
        for start, data in self.windows.items(): self.uc.mem_write(start, data)
        self.readable = [(a, a + len(b)) for a, b in self.windows.items()]
        self.readable.append((self.STACK - self.STACK_BYTES, self.STACK + 32))
        self.writable = [(self.STACK - self.STACK_BYTES, self.STACK + 32)]
        self.executable, self.mocks, self.calls, self.writes = [], {}, [], []
        self.returned = False
        self.steps = 0
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, self._memory)

    @staticmethod
    def contains(spans, address, size):
        return any(lo <= address and address + size <= hi for lo, hi in spans)

    def select(self, start, end):
        if (start & 1 or end & 1 or start >= end or
                not any(a <= start < end <= a + len(b) for a, b in self.windows.items())):
            raise ValueError("function must lie inside the captured ROM windows")
        self.executable.append((start, end))

    def fixture(self, address, data, *, writable=False):
        if not data or not self.contains(((0x200000, 0x218000), (0x300000, self.STACK - self.STACK_BYTES)),
                                         address, len(data)):
            raise ValueError("fixture outside synthetic RAM/header space")
        self.uc.mem_write(address, bytes(data))
        self.readable.append((address, address + len(data)))
        if writable: self.writable.append((address, address + len(data)))

    def word(self, address):
        if not self.contains(self.readable, address, 4): raise ROMBoundaryError("unpopulated fixture word")
        return struct.unpack("<I", self.uc.mem_read(address, 4))[0]

    def mock(self, address, name, handler):
        if address & 1 or address in self.mocks: raise ValueError("duplicate or noncanonical boundary")
        self.mocks[address] = name, handler

    def return_value(self, value=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _code(self, uc, pc, size, _):
        self.steps += 1
        if pc == self.RETURN:
            self.returned = True
            uc.emu_stop()
        elif pc == 0x208:
            raise ROMAssertion("captured ROM entered its unread assertion handler")
        elif pc in self.mocks:
            name, handler = self.mocks[pc]
            regs = tuple(uc.reg_read(r) for r in (self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1,
                                                self.a.UC_ARM_REG_R2, self.a.UC_ARM_REG_R3))
            self.calls.append(MockCall(pc, name, regs))
            handler(self, regs)
        elif not self.contains(self.executable, pc, size):
            raise ROMBoundaryError(f"unreviewed or uncaptured instruction at {pc:#x}")

    def _memory(self, uc, access, address, size, value, _):
        writing = access == self.u.UC_MEM_WRITE
        if not self.contains(self.writable if writing else self.readable, address, size):
            verb = "write" if writing else "read"
            raise ROMBoundaryError(f"{verb} outside admitted evidence/fixtures at {address:#x}")
        if writing and address < self.STACK - self.STACK_BYTES:
            # Unicorn may expose the entire source register for STRB/STRH.
            # Record the bytes actually stored, not the untruncated register.
            self.writes.append((address, size, value & ((1 << (size * 8)) - 1)))

    def call(self, address, *args, budget=5000):
        if address & 1 or len(args) > 8: raise ValueError("canonical entry and at most eight arguments required")
        a = self.a
        for index, register in enumerate((a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)):
            self.uc.reg_write(register, args[index] if index < len(args) else 0xCCCCCCCC)
        saved = (a.UC_ARM_REG_R4, a.UC_ARM_REG_R5, a.UC_ARM_REG_R6, a.UC_ARM_REG_R7,
                 a.UC_ARM_REG_R8, a.UC_ARM_REG_R9, a.UC_ARM_REG_R10, a.UC_ARM_REG_R11)
        for index, register in enumerate(saved): self.uc.reg_write(register, 0xABC00000 + index)
        self.uc.mem_write(self.STACK - self.STACK_BYTES - 16, b"\xA5" * 16)
        self.uc.mem_write(self.STACK, b"\xA5" * 48)
        if len(args) > 4: self.uc.mem_write(self.STACK, struct.pack("<" + "I" * (len(args) - 4), *args[4:]))
        self.uc.reg_write(a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(a.UC_ARM_REG_LR, self.RETURN | 1)
        self.returned = False
        try:
            self.uc.emu_start(address | 1, 0xFFFFFFFF, count=budget)
        except self.u.UcError as exc:
            pc = self.uc.reg_read(a.UC_ARM_REG_PC)
            raise ROMBoundaryError(f"invalid/protected ROM execution at {pc:#x}: {exc}") from exc
        if not self.returned: raise ROMBoundaryError("instruction budget exhausted")
        if self.uc.reg_read(a.UC_ARM_REG_SP) != self.STACK or any(
                self.uc.reg_read(register) != 0xABC00000 + index for index, register in enumerate(saved)):
            raise ROMBoundaryError("AAPCS stack/register corruption")
        if (bytes(self.uc.mem_read(self.STACK - self.STACK_BYTES - 16, 16)) != b"\xA5" * 16 or
                bytes(self.uc.mem_read(self.STACK + 32, 16)) != b"\xA5" * 16):
            raise ROMBoundaryError("stack canary changed")
        return self.uc.reg_read(a.UC_ARM_REG_R0)


class ROMFenceHarness(StockAppendThumb):
    """Compiled actual-address fence -> captured ROM -> compiled callback.

    ONLY the kernel queue send/receive bodies are substituted here. Their FIFO,
    capacity, task scheduling and completion timings are synthetic assumptions,
    not measured facts. No timer-object operation, hub or physical STOP is run.
    The timer queue slot is synthetic; no on-device RAM is accessed.
    """
    QUEUE_SLOT = 0x201478
    QUEUE = 0x300800
    EARLY_RETURN = 0x4FFE0

    def __init__(self, elf, stock, descriptor, capture):
        from collections import deque

        super().__init__(elf, stock, descriptor)
        windows = captured_windows(capture)
        self.uc.mem_map(0, 0x50000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        self.uc.mem_map(0x201000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_write(self.QUEUE_SLOT, struct.pack("<I", self.QUEUE))
        for address, data in windows.items():
            self.uc.mem_write(address, data)
            self.loaded_spans.append((address, address + len(data)))
        # Exclude all positive-command paths and the embedded jump table.
        self.executable.extend(((0x10D5E, 0x10D98), (0x1099E, 0x109BA), (0x10A82, 0x10A96)))
        self.symbols["captured_timer_dispatch"] = 0x1099F
        self.messages, self.boundaries, self.callbacks = deque(), [], []
        self.send_result, self.early = 1, False
        self.remaining = None
        self.early_return_to = None
        self.invoke("wf_init")

    def _read(self, uc, access, address, size, value, opaque):
        if address == self.QUEUE_SLOT and size == 4: return
        super()._read(uc, access, address, size, value, opaque)

    def _kernel_return(self, value):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _code(self, uc, pc, size, opaque):
        a = self.a
        regs = tuple(uc.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                                             a.UC_ARM_REG_R2, a.UC_ARM_REG_R3))
        if pc == 0x208: raise ROMAssertion("timer pend reached ROM assertion")
        if pc in (0xEAB2, 0xEFAE):
            handle, message, wait, position = regs
            if handle != self.QUEUE or wait or uc.reg_read(a.UC_ARM_REG_PRIMASK):
                raise ThumbProofError("incorrect queue binding/context")
            if not self.STACK - 0x1000 <= message <= self.STACK - 16:
                raise ThumbProofError("queue message outside current synthetic stack")
            self.boundaries.append((pc, regs))
            if pc == 0xEAB2:
                if position: raise ThumbProofError("expected send-to-back")
                packet = bytes(uc.mem_read(message, 16))
                command, callback, context, ticket = struct.unpack("<4I", packet)
                if (command, callback, context) != (0xFFFFFFFF, self.symbols["timer_passed"], self.CONTEXT):
                    raise ThumbProofError("incorrect captured pend marshalling")
                if self.send_result == 1: self.messages.append(packet)
                if self.early and self.send_result == 1:
                    self.early_return_to = uc.reg_read(a.UC_ARM_REG_LR)
                    uc.reg_write(a.UC_ARM_REG_LR, self.EARLY_RETURN | 1)
                    uc.reg_write(a.UC_ARM_REG_PC, self.symbols["captured_timer_dispatch"])
                    return
                self._kernel_return(self.send_result)
            else:
                if not self.messages or self.remaining == 0:
                    self._kernel_return(0)
                    return
                packet = self.messages.popleft()
                if len(packet) != 16: raise ThumbProofError("incorrect fixture queue-message length")
                uc.mem_write(message, packet)
                if self.remaining is not None: self.remaining -= 1
                self._kernel_return(1)
            return
        if pc == self.EARLY_RETURN:
            if self.early_return_to is None: raise ThumbProofError("unsolicited early return")
            uc.reg_write(a.UC_ARM_REG_R0, self.send_result & 0xFFFFFFFF)
            uc.reg_write(a.UC_ARM_REG_PC, self.early_return_to)
            self.early_return_to = None
            return
        if pc == (self.symbols["timer_passed"] & ~1):
            self.callbacks.append((regs[0], regs[1], bytes(uc.mem_read(self.CONTEXT + 9, 1))[0]))
        super()._code(uc, pc, size, opaque)

    def dispatch(self, limit=None):
        if limit is not None and (type(limit) is not int or limit < 0): raise ValueError("invalid fixture limit")
        self.remaining = limit
        try: self.call("captured_timer_dispatch")
        finally: self.remaining = None
