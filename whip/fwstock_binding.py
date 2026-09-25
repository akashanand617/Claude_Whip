"""Exact-stock OFFLINE binding witnesses, not a device driver or deploy path.

Runs original queue dispatch, timer wrappers and optical I2C packaging/status.
ROM scheduling/allocation and peripheral transaction results are explicit
fixtures. A recorded bus success is NOT a physical emitter-off measurement.
"""
from __future__ import annotations

from collections import deque
from io import BytesIO
import struct

from whip.fwcontinuity import BIAS, ProofError
from whip.fwhealth_lifecycle import (
    HUB_QUEUE_SLOT, MOCK_QUEUE_HANDLE, StockLifecycleHarness,
)

MUTEX_SLOT = 0x208C98
MOCK_MUTEX = 0x220180
MOCK_HEAP = 0x220800
MOCK_TIMER = 0x220300
DELAY_STUB = 0x30000  # explicit fixture target for stock indirect delay pointer

BINDING_RANGES = (
    (0x1420, 0x14DE),          # hub dispatcher/task/create/post
    (0x3AC4, 0x3C16),         # indicator brightness/pattern callbacks
    (0x3CAC, 0x3CD2),         # indicator cancellation
    (0x3E04, 0x3E48),         # timer start/restart/stop/delete wrappers
    (0xDAF0, 0xDBFA),         # bus status/recovery prefix, TX, allocation/copy
    (0xDC30, 0xDC40),         # TX cleanup after literal island
    (0xDD38, 0xDD50), (0xDD6C, 0xDD8E),  # optical message dispatch
    (0xEE12, 0xEE4A),         # optical write mutex/status wrapper
    (0xF7BA, 0xF7CE),         # direct indicator optical stop
    (0xF812, 0xF824),         # brightness wrapper to driver entry
    (0xF934, 0xF936),         # optical hub subtype 3 is literally bx lr
    (0x12948, 0x12958), (0x129F4, 0x129FC),  # allocator wrappers
)


class StockBindingHarness(StockLifecycleHarness):
    """One reviewed fixture, with genuine app instructions and bounded mocks.

The default bus fixture permits TX and reports transaction success. It does not
map I2C registers or emulate optical physics. Failures can be injected at mutex,
allocation, readiness, activity and transfer boundaries independently.
"""

    def __init__(self, image: bytes):
        self.mutex_available = True
        self.mutex_give_ok = True
        self.mutex_events = []
        self.allocate_ok = True
        self.allocations = []
        self.freed = []
        self.bus_ready = True
        self.bus_busy = False
        self.transfer_result = 0
        self.transfer_results = deque()
        self.transfers = []
        self.delay_calls = []
        self.target_addresses = []
        self.timer_calls = []
        self.timer_create_ok = True
        self.timer_start_ok = True
        self.timer_restart_ok = True
        self.timer_stop_ok = True
        self.timer_delete_ok = True
        self.pending = deque()
        self.received = []
        self.hub_running = False
        self.queue_creates = []
        self.task_creates = []
        self.indicator_requests = []
        self.other_hub_requests = []
        self.shim_functions = {}
        self.shim_spans = []
        super().__init__(image)
        self.uc.mem_write(MUTEX_SLOT, struct.pack("<I", MOCK_MUTEX))
        self.uc.mem_write(0x20011C, struct.pack("<I", DELAY_STUB | 1))

    def _code(self, uc, address, size, opaque):
        r0, r1, r2, r3 = [uc.reg_read(r) for r in self.registers]
        offset = address - BIAS
        if address in (0x133F4, 0x1341C):
            if r0 != MOCK_MUTEX or (address == 0x133F4 and r1 != 100):
                raise ProofError("unexpected optical mutex ABI")
            self.mutex_events.append("take" if address == 0x133F4 else "give")
            self._return(self.mutex_available if address == 0x133F4 else self.mutex_give_ok)
            return
        if address == 0x12C30:  # os_mem_alloc_intern
            if r0 != 0 or r1 != 12:
                raise ProofError("unreviewed optical allocation size/type")
            self.allocations.append(r1)
            self._return(MOCK_HEAP if self.allocate_ok else 0)
            return
        if address == 0x12D4C:  # os_mem_free
            if r0 != MOCK_HEAP:
                raise ProofError("unexpected optical free pointer")
            self.freed.append(r0)
            self._return()
            return
        if offset == 0xDFF8:
            if r0 != 0x40015000 or r1 not in (4, 0x20):
                raise ProofError("unreviewed bus status request")
            self._return(self.bus_ready if r1 == 4 else self.bus_busy)
            return
        if address == DELAY_STUB:
            if r0 != 10:
                raise ProofError("unexpected indirect delay")
            self.delay_calls.append(r0)
            self._return()
            return
        if offset == 0xDFE4:
            if r0 != 0x40015000 or r1 != 0x33:
                raise ProofError("unexpected optical bus target")
            self.target_addresses.append(r1)
            self._return()
            return
        if offset == 0x1364A:
            if r0 != 0x40015000 or r2 != 2:
                raise ProofError("unexpected optical bus transfer")
            self._ram_span(r1, r2)
            self.transfers.append(bytes(uc.mem_read(r1, r2)))
            self._return(self.transfer_results.popleft() if self.transfer_results else self.transfer_result)
            return
        if address in (0x13634, 0x13670, 0x13694, 0x136BC, 0x136E0):
            self._ram_span(r0, 4)
            names = {0x13634: "create", 0x13670: "start", 0x13694: "restart",
                     0x136BC: "stop", 0x136E0: "delete"}
            name = names[address]
            args = (r0,)
            if name == "create":
                repeat, callback = struct.unpack("<II", uc.mem_read(uc.reg_read(self.a.UC_ARM_REG_SP), 8))
                args = (r0, r2, r3, repeat, callback)
                if self.timer_create_ok:
                    uc.mem_write(r0, struct.pack("<I", MOCK_TIMER))
            if name == "restart":
                args = (r0, r1)
            self.timer_calls.append((name, *args))
            # Intentionally do NOT mutate/delete handles or deliver callbacks:
            # those ROM side effects are outside this app-code proof.
            self._return(getattr(self, "timer_" + name + "_ok"))
            return
        if address == 0x12ED6:  # os_msg_send_intern
            if r0 != MOCK_QUEUE_HANDLE or r2 != 0:
                raise ProofError("unreviewed hub queue post")
            self._ram_span(r1, 8)
            message = struct.unpack("<HHI", uc.mem_read(r1, 8))
            self.post_attempts.append(message)
            if self.queue_accepts:
                self.messages.append(message)
                self.pending.append(message)
            self._return(self.queue_accepts)
            return
        if address == 0x12F32:  # os_msg_recv_intern; blocking fixture boundary
            if not self.hub_running or r0 != MOCK_QUEUE_HANDLE or r2 != 0xFFFFFFFF:
                raise ProofError("unexpected hub receive ABI/context")
            self._ram_span(r1, 8)
            if not self.pending:
                self.hub_running = False
                uc.emu_stop()  # task would block; this is NOT a fence receipt
                return
            message = self.pending.popleft()
            self.received.append(message)
            uc.mem_write(r1, struct.pack("<HHI", *message))
            self._return(1)
            return
        if address == 0x12DE0:  # os_msg_queue_create_intern
            if r0 != HUB_QUEUE_SLOT or (r1, r2) != (32, 8):
                raise ProofError("unexpected hub queue creation")
            self.queue_creates.append((r0, r1, r2))
            uc.mem_write(r0, struct.pack("<I", MOCK_QUEUE_HANDLE))
            self._return(1)
            return
        if address == 0x13468:  # os_task_create, stack bytes and priority on stack
            stack_bytes, priority = struct.unpack("<II", uc.mem_read(uc.reg_read(self.a.UC_ARM_REG_SP), 8))
            if (r0, r2, r3, stack_bytes, priority) != (0x208CA4, BIAS + 0x1467, 0, 2560, 2):
                raise ProofError("unexpected hub task creation")
            self.task_creates.append((r0, r2, stack_bytes, priority))
            self._return(1)
            return
        if offset == 0x11246:  # indicator's direct lower-driver request
            last = struct.unpack("<I", uc.mem_read(uc.reg_read(self.a.UC_ARM_REG_SP), 4))[0]
            self.indicator_requests.append((r0, r1, r2, r3, last))
            self._return()  # no physical RUN is asserted
            return
        if offset in (0xD024, 0xD518):
            self.other_hub_requests.append((offset, r0, r1))
            self._return()
            return
        if any(lo <= address and address + size <= hi for lo, hi in self.shim_spans):
            return
        if any(lo <= offset < hi for lo, hi in BINDING_RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def run_hub_until_fixture_empty(self, budget=100_000):
        """Execute the actual never-returning task up to its next mocked wait."""
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.hub_running = True
        try:
            self.uc.emu_start(BIAS + 0x1467, 0xFFFFFFFF, count=budget)
        except self.u.UcError as exc:
            raise ProofError(f"invalid hub execution: {exc}") from exc
        if self.hub_running or self.pending:
            raise ProofError("hub fixture budget exhausted")
        if self.uc.reg_read(self.a.UC_ARM_REG_SP) != self.STACK - 16:
            raise ProofError("unexpected blocked hub task stack")

    def load_test_shim(self, data: bytes):
        """Load compiled ABI shim at artificial addresses, never patch stock."""
        from elftools.elf.elffile import ELFFile

        elf = ELFFile(BytesIO(data))
        if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != \
                (32, True, "EM_ARM", "ET_EXEC"):
            raise ValueError("requires ARM32 little-endian linked test shim")
        if self.shim_spans:
            raise ValueError("test shim already loaded")
        self.uc.mem_map(0x01000000, 0x10000, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        loaded = []
        for segment in elf.iter_segments():
            if segment["p_type"] != "PT_LOAD":
                continue
            start, size = segment["p_vaddr"], segment["p_memsz"]
            if segment["p_flags"] & 2 or not 0x01000000 <= start <= start + size <= 0x01010000:
                raise ValueError("unexpected writable/out-of-region shim segment")
            self.uc.mem_write(start, segment.data())
            loaded.append((start, start + size))
        symbols = elf.get_section_by_name(".symtab")
        if not symbols:
            raise ValueError("shim symbols required")
        entry_symbols = {}
        for sym in symbols.iter_symbols():
            if sym.name and sym["st_shndx"] == "SHN_UNDEF":
                raise ValueError("unresolved shim symbol")
            if sym["st_info"]["type"] == "STT_FUNC" and sym["st_size"]:
                start, size = sym["st_value"] & ~1, sym["st_size"]
                if not sym["st_value"] & 1 or not any(lo <= start < start + size <= hi for lo, hi in loaded):
                    raise ValueError("shim function outside loaded Thumb span")
                if sym.name in ("wr_init", "wb_stock_stop_writes"):
                    entry_symbols[sym.name] = sym["st_value"]
                # A guarded unified test ELF can contain other components, but
                # this observer does NOT widen execution to those functions.
                if sym.name == "wb_stock_stop_writes":
                    self.shim_functions[sym.name] = sym["st_value"]
                    self.shim_spans.append((start, start + size))
        if not self.shim_spans or elf["e_entry"] not in entry_symbols.values():
            raise ValueError("unexpected shim entry")

    def call_shim(self, name: str, *args: int):
        if name not in self.shim_functions:
            raise ValueError("unknown test shim entry")
        saved = [getattr(self.a, f"UC_ARM_REG_R{i}") for i in range(4, 12)]
        for index, register in enumerate(saved):
            self.uc.reg_write(register, 0xABCDE000 + index)
        result = self.call((self.shim_functions[name] & ~1) - BIAS, *args)
        if any(self.uc.reg_read(register) != 0xABCDE000 + index
               for index, register in enumerate(saved)):
            raise ProofError("shim/stock ABI clobbered a callee-saved register")
        return result


class StockProducerHarness(StockBindingHarness):
    """Remaining realtime/activity entry witnesses with explicit result mocks.

Notification enqueue, activity aggregation, algorithm parameter setters and
float conversion are boundary mocks. This does not execute history persistence,
the gesture model or optical algorithm and cannot validate measured Health.
"""

    PRODUCER_RANGES = (
        (0x3FE8, 0x4002),  # packet checksum
        (0x40D6, 0x416C),  # realtime early-failure publication/cancel branches
        (0x4518, 0x473E),  # mode6 callback and actual shared timer dispatcher
        (0xA880, 0xA948), (0xAA00, 0xAA32),  # activity start/stop wrappers
        (0xF736, 0xF75C),
    )

    def __init__(self, image: bytes):
        self.notifications = []
        self.algorithm_parameters = []
        self.activity_aggregations = []
        self.float_conversions = []
        super().__init__(image)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        r0, r1, _, _ = [uc.reg_read(r) for r in self.registers]
        if offset == 0x7E30:
            self._ram_span(r0, 16)
            packet = bytes(uc.mem_read(r0, 16))
            if packet[0] != 0x69 or packet[15] != sum(packet[:15]) % 256:
                raise ProofError("unexpected realtime result packet")
            self.notifications.append(packet)
            self._return()
            return
        if offset in (0x18D6C, 0x18CF4):
            self.float_conversions.append((offset, r0))
            if offset == 0x18D6C:
                signed = (r0 + 0x80000000) % 0x100000000 - 0x80000000
                self._return(struct.unpack("<I", struct.pack("<f", signed))[0])
            else:
                self._return(int(struct.unpack("<f", struct.pack("<I", r0))[0]))
            return
        if offset in (0x1AF4, 0xB7B8, 0xB7C0):
            self.mock_calls.append(offset)
            self._return({0x1AF4: 123, 0xB7B8: 100, 0xB7C0: 200}[offset])
            return
        if offset == 0x1DD6C:
            self.algorithm_parameters.append((r0, r1))
            self._return()
            return
        if offset == 0xA948:
            self.activity_aggregations.append(r0)
            self._return()
            return
        if any(lo <= offset < hi for lo, hi in self.PRODUCER_RANGES):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)
