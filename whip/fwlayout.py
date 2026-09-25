"""Pinned-stock memory/overlay audit; never grants an allocation or builds OTA.

The selected-instruction harness executes the stock overlay loader, not full
boot or the ROM allocator. Its RAM and stack are a synthetic test fixture.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import asdict, dataclass

from whip.fwunified import STOCK_SHA256

BIAS = 0x825FB0
OVERLAY_TABLE_FILE = 0x21578
OVERLAY_TABLE_RAM = 0x2084B0
OVERLAY_STAMP_RAM = 0x208C72
OVERLAY_LOADER_FILE = 0xA34
OVERLAY_QUERY_FILE = 0xA7E
SDK_SOURCE_COMMIT = "49301d9b75816ccde1cc9657b827fdadf5736937"


def _pinned(data: bytes) -> None:
    if hashlib.sha256(data).hexdigest() != STOCK_SHA256:
        raise ValueError("layout audit requires the exact pinned stock SHA-256")


@dataclass(frozen=True)
class Overlay:
    index: int
    stamp_flash: int
    code_flash: int
    data_flash: int
    code_ram: int
    data_ram: int
    bss_ram: int
    code_size: int
    data_size: int
    bss_size: int

    def as_dict(self) -> dict:
        result = asdict(self)
        result["code_file"] = self.code_flash - BIAS
        result["code_ram_end_exclusive"] = self.code_ram + self.code_size
        return result


def overlays(data: bytes) -> tuple[Overlay, ...]:
    """Decode the table consumed by 0xa34, only after whole-image identity."""
    _pinned(data)
    return tuple(Overlay(i, *struct.unpack_from("<9I", data, OVERLAY_TABLE_FILE + 36 * i))
                 for i in range(3))


def audit_layout(data: bytes) -> dict:
    """Report established ownership, separately from unresolved allocation."""
    _pinned(data)
    return {
        "stock_sha256": STOCK_SHA256,
        "rom_uuid": data[0x5C:0x6C].hex(),
        "safe_static_allocation": None,
        "safe_flash_allocation": None,
        "runtime_minus_file": BIAS,
        "occupied_application_ram": [
            {"kind": "permanent RAM code", "start": 0x207C00, "end_exclusive": 0x2084B0},
            {"kind": "initialized data", "start": 0x2084B0, "end_exclusive": 0x208990},
            {"kind": "BSS", "start": 0x208990, "end_exclusive": 0x20E734},
            {"kind": "startup overlay", "start": 0x20E734, "end_exclusive": 0x20E7FC},
        ],
        "overlay_table_file": OVERLAY_TABLE_FILE,
        "overlay_loader_file": OVERLAY_LOADER_FILE,
        "overlay_query_file": OVERLAY_QUERY_FILE,
        "overlay_boot_load_call_file": 0x670,
        "overlay_boot_execute_call_file": 0x6A4,
        "overlays": [item.as_dict() for item in overlays(data)],
        "file_tail": {"start": 0x21A58, "end_exclusive": len(data),
                      "classification": "overlay-zero executable code and literal pool, not padding"},
        "flash_extent": {"realtek_header_start": 0x826000,
                         "payload_start": 0x826400, "end_exclusive": 0x847AD0,
                         "header_and_payload_bytes": len(data) - 0x50,
                         "partition_capacity": None,
                         "ota_bounds_check_file": 0x10A2,
                         "ota_app_descriptor_offset": 0x1A8,
                         "minimum_capacity_formula": "new_vendor_container_size - 0x50; plus any separately proven alignment allowance",
                         "warning": "payload length is not the active or temporary OTA partition capacity"},
        "future_read_only_data_plan": {
            "authorized_or_executed": False,
            "app_ram_config": {"address": 0x200380, "length": 16},
            "flash_layout_config": {"address": 0x2003E4, "length": 48},
            "ota_descriptors": "from each validated bank base + 0x198; app address/size at +0x1a8/+0x1ac",
            "warning": "no generic OTP dump; CD01 has stateful dispatch prelude; requires image-specific audit and coordinated idle connection",
        },
        "startup_stack_top": 0x203800,
        "ram_layout_rom": {"thumb_address": 0x4A79, "call_file": 0x6EE,
                           "r0": 0x7000, "r1": 0x7400, "r2": 0,
                           "argument_names": ["app_global_size", "data_heap_size", "share_cache_ram_size"],
                           "abi_evidence": "SDK-derived header plus matching ROM symbol and stock call registers",
                           "sdk_source_commit": SDK_SOURCE_COMMIT,
                           "rom_implementation_executed": False},
        "nominal_static_headroom": {"start": 0x20E7FC, "end_exclusive": 0x20EC00,
                                    "bytes": 1028, "approved_for_use": False,
                                    "basis": "stock copies + overlay + documented 28 KiB APP reservation",
                                    "missing": "exact live OTP/ROM-patch ownership and indirect-write closure"},
        "allocator": {"alloc_thumb": 0x12C31, "zalloc_thumb": 0x12C8B,
                      "free_thumb": 0x12D4D,
                      "stock_malloc_wrapper_file": 0x12948,
                      "stock_calloc_wrapper_file": 0x12958,
                      "observed_registers": "r0=0; r1=byte count; r2=caller string; r3=line",
                      "allocation_and_failure_isolation_proven": False},
        "task_create_arguments": [
            {"call_file": 0x8E2, "entry_file": 0x854, "stack_bytes": 0x400, "priority": 2},
            {"call_file": 0x13E6, "entry_file": 0x131E, "stack_bytes": 0xE00, "priority": 1},
            {"call_file": 0x14B6, "entry_file": 0x1466, "stack_bytes": 0xA00, "priority": 2},
        ],
        "warning": "known occupied intervals only; no proof of spare capacity, retention, stack margin or live RTOS serialization",
    }


class LayoutProofError(RuntimeError):
    pass


class StockOverlayHarness:
    """Execute the actual loader/query instructions with strict memory mocks.

    ROM memcpy/memcmp/memclr have explicit byte semantics. No other ROM calls
    are implemented. All writes are checked against the exact selected path.
    The vector initializer may execute after loading, with explicit VTOR and
    ROM initialization/logging mocks. No real interrupt or ROM patch executes.
    """

    STOP = 0x3FFF0
    STACK = 0x301000  # fixture-only stack, deliberately outside real chip RAM

    def __init__(self, data: bytes):
        _pinned(data)
        import unicorn as u
        from unicorn import arm_const as a

        self.u, self.a = u, a
        self.image = data
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, data)
        self.uc.mem_map(0x200000, 0x18000, u.UC_PROT_ALL)
        self.uc.mem_map(0x300000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0xE000E000, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_write(0xE000ED08, struct.pack("<I", 0x200000))
        # Model only the startup data copy required before the overlay loader.
        self.uc.mem_write(OVERLAY_TABLE_RAM, data[0x21578:0x21A58])
        self.operations: list[tuple] = []
        self.executed: set[int] = set()
        self.vector_writes: list[tuple[int, int]] = []
        self.layout_arguments = None
        self.allocator_result = 0
        self.returned = False
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)

    def _return(self, value=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _write(self, uc, access, address, size, value, _):
        # Loader/query instructions only write their own call stack. Memory
        # copies use the separately validated mocked ROM functions below.
        pc = uc.reg_read(self.a.UC_ARM_REG_PC)
        if self.STACK - 256 <= address <= address + size <= self.STACK:
            return
        if pc == 0x20E7C6 and size == 4 and 0x200008 <= address <= 0x2000E4 and address % 4 == 0:
            self.vector_writes.append((address, value))
            return
        if BIAS + 0x6D4 <= pc < BIAS + 0x6EE and size == 4 and address in (0x2011D4, 0x2011D8, 0x201514):
            return
        raise LayoutProofError("unexpected direct write outside reviewed stack/vector/setup slots")

    def _code(self, uc, address, size, _):
        if address == self.STOP:
            self.returned = True
            uc.emu_stop()
            return
        r0, r1, r2 = [uc.reg_read(reg) for reg in
                      (self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1, self.a.UC_ARM_REG_R2)]
        if address == 0x4A78:  # stop BEFORE unknown ROM memory-layout implementation
            self.layout_arguments = (r0, r1, r2)
            self.returned = True
            uc.emu_stop()
            return
        if address in (0x12C30, 0x12C8A):  # observe ABI, do not emulate heap ownership
            r3 = uc.reg_read(self.a.UC_ARM_REG_R3)
            if r0 != 0 or not (r2, r3) in ((0x845A74, 0x4D1), (0x845A7B, 0x4D6)):
                raise LayoutProofError("unexpected allocator ABI")
            self.operations.append(("alloc" if address == 0x12C30 else "zalloc", r0, r1, r2, r3))
            self._return(self.allocator_result)
            return
        if address == 0x2A8:  # overlay vector initializer's __aeabi_memcpy4
            permitted = ((self.STACK - 84, 0x845A8C, 0x40),
                         (self.STACK - 252, 0x845ACC, 0xA8))
            if (r0, r1, r2) not in permitted:
                raise LayoutProofError("unexpected vector scratch copy")
            self.operations.append(("vector_scratch_copy", r0, r1, r2))
            uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
            self._return(r0)
            return
        if address == 0x34D0:  # RamVectorTableInit: explicit synthetic ROM table
            self.operations.append(("vector_init_mock",))
            uc.mem_write(0x200000, struct.pack("<I", 0x47E7) * 58)
            uc.mem_write(0xE000ED08, struct.pack("<I", 0x200000))
            self._return()
            return
        if address == 0x5E6A:  # trace_string: only logs, does not own stock state
            self._return(r1)
            return
        if address == 0x5AA8:  # log_buffer: explicitly ignored output boundary
            self._return()
            return
        if address == 0x3F7A8:  # ROM memcmp, overlay identity only
            if r2 != 8 or r1 != OVERLAY_STAMP_RAM or r0 not in (0x8467E8, 0x8467D8, 0x8467E0):
                raise LayoutProofError("unexpected overlay memcmp")
            lhs, rhs = bytes(uc.mem_read(r0, r2)), bytes(uc.mem_read(r1, r2))
            self.operations.append(("compare", r0, r1, r2))
            self._return((lhs > rhs) - (lhs < rhs))
            return
        if address == 0x3F848:  # ROM memcpy
            permitted = (
                (0x20E734, 0x847A08, 0xC8),
                (0x20E7FC, 0x847AD0, 0),
                (0x20E734, 0x847AD0, 0),
                *((OVERLAY_STAMP_RAM, source, 8) for source in (0x8467E8, 0x8467D8, 0x8467E0)),
            )
            if (r0, r1, r2) not in permitted:
                raise LayoutProofError("unexpected overlay memcpy")
            self.operations.append(("copy", r0, r1, r2))
            if r2:
                uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
            self._return(r0)
            return
        if address == 0x3F914:  # ROM __rt_memclr
            if r0 not in (0x20E734, 0x20E7FC) or r1 != 0:
                raise LayoutProofError("unexpected overlay clear")
            self.operations.append(("clear", r0, r1))
            self._return(r0)
            return
        offset = address - BIAS
        allowed = (OVERLAY_LOADER_FILE <= offset < 0xAA6 or
                   0x6D4 <= offset < 0x6F2 or 0x12948 <= offset < 0x1296C or
                   0x20E734 <= address < 0x20E7DC)
        if not allowed:
            raise LayoutProofError(f"unreviewed layout execution at {address:#x}")
        self.executed.add(offset)

    def call(self, offset: int, argument=0, *, second=0, budget=3000) -> int:
        if offset not in (OVERLAY_LOADER_FILE, OVERLAY_QUERY_FILE, 0x6D4,
                          0x12948, 0x12958, 0x20E734 - BIAS):
            raise LayoutProofError("only the reviewed loader/query/setup/wrapper entries may execute")
        self.uc.reg_write(self.a.UC_ARM_REG_R0, argument)
        self.uc.reg_write(self.a.UC_ARM_REG_R1, second)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, self.STOP | 1)
        self.returned = False
        try:
            self.uc.emu_start((BIAS + offset) | 1, 0xFFFFFFFF, count=budget)
        except self.u.UcError as exc:
            raise LayoutProofError(f"unmapped/invalid overlay execution: {exc}") from exc
        if not self.returned:
            raise LayoutProofError("overlay instruction budget exhausted")
        if self.uc.reg_read(self.a.UC_ARM_REG_SP) != self.STACK:
            raise LayoutProofError("overlay stack not restored")
        return self.uc.reg_read(self.a.UC_ARM_REG_R0)
