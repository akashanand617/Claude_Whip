"""OFF-RING placement evidence and selected OEM DFU instruction witnesses.

This is neither a firmware builder nor a flash client. Image hashes pin every
executed instruction; synthetic inputs and mocked ROM/RTOS/flash boundaries do
not establish physical geometry, power-loss recovery, or free RAM. No API can
authorize placement or a flash.
"""
from __future__ import annotations

import hashlib
import struct

from . import fwcapacity as c


BIAS = c.BIAS
INIT_MINIMUM = 0x2800
INIT_MAXIMUM = 0x24050
STAGING_BASE = 0x84E000
PARTITION_BYTES = 0x24000
ROM_UUID = "f94c6b7e11c5eb118282f74a0c0cef5b"
PROFILES = {
    c.STOCK_SHA256: dict(size=138016, init=0x841A, data=0x84B2,
        receipt=0x85EA, end=0x8626, after_checksum=0x864A,
        progress=0x8490, erase=0x3630, write=0x3678, shim=0x36D8,
        context_pool=0x86C8, size_pool=0x86E8, staging_pool=0x86EC,
        mutex_pool=0x36EC, calls=(0x927A, 0x9280, 0x9286, 0x928C)),
    c.ORIGINAL_SHA256: dict(size=137540, init=0x81F6, data=0x828E,
        receipt=0x83C4, end=0x8400, after_checksum=0x8424,
        progress=0x826C, erase=0x35A4, write=0x35EC, shim=0x364C,
        context_pool=0x84A0, size_pool=0x84C0, staging_pool=0x84C4,
        mutex_pool=0x3660, calls=(0x905E, 0x9066, 0x906E, 0x9076)),
    c.V2_SHA256: dict(size=137540, init=0x81F6, data=0x828E,
        receipt=0x83C4, end=0x8400, after_checksum=0x8424,
        progress=0x826C, erase=0x35A4, write=0x35EC, shim=0x364C,
        context_pool=0x84A0, size_pool=0x84C0, staging_pool=0x84C4,
        mutex_pool=0x3660, calls=(0x905E, 0x9066, 0x906E, 0x9076)),
}


def _u32(value, name):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be a u32 integer")
    return value


def _bl_destination(image, offset):
    first, second = struct.unpack_from("<HH", image, offset)
    if first & 0xF800 != 0xF000 or second & 0xD000 != 0xD000:
        raise ValueError("expected Thumb BL")
    sign = first >> 10 & 1
    i1 = 1 ^ (second >> 13 & 1) ^ sign
    i2 = 1 ^ (second >> 11 & 1) ^ sign
    delta = (sign << 24 | i1 << 23 | i2 << 22 |
             (first & 0x3FF) << 12 | (second & 0x7FF) << 1)
    if sign:
        delta -= 1 << 25
    return offset + 4 + delta


def audit_image(image: bytes) -> dict:
    if type(image) is not bytes:
        raise ValueError("image must be exact immutable bytes")
    digest = hashlib.sha256(image).hexdigest()
    if digest not in PROFILES or len(image) != PROFILES[digest]["size"]:
        raise ValueError("unreviewed image; exact stock/25Hz/V2 bytes required")
    p = PROFILES[digest]
    word = lambda offset: struct.unpack_from("<I", image, offset)[0]
    if (word(p["size_pool"]) != INIT_MAXIMUM - INIT_MINIMUM + 1 or
            word(p["staging_pool"]) != STAGING_BASE):
        raise ValueError("OEM INIT/staging literal mismatch")
    for site, name in zip(p["calls"], ("init", "data", "receipt", "end")):
        if _bl_destination(image, site) != p[name]:
            raise ValueError("OEM dispatcher call target mismatch")
    if (struct.unpack_from("<H", image, 0x54)[0] != 0x2793 or
            word(0x58) + 0x450 != len(image) or image[0x5C:0x6C].hex() != ROM_UUID):
        raise ValueError("application header/ROM ABI mismatch")
    return {
        "image_sha256": digest, "image_name": c.IMAGE_NAMES[digest],
        "vendor_file_bytes": len(image), "realtek_image_bytes": len(image) - 0x50,
        "image_id": 0x2793, "rom_uuid": ROM_UUID,
        "oem_init_minimum_vendor_bytes": INIT_MINIMUM,
        "oem_init_maximum_vendor_bytes": INIT_MAXIMUM,
        "oem_staging_address": STAGING_BASE,
        "oem_maximum_realtek_bytes": PARTITION_BYTES,
        "sites": dict(p), "context_address": word(p["context_pool"]) - 0x18,
        "buffer_address": word(p["context_pool"]),
        "mutex_address": word(p["mutex_pool"]),
        "code_binding_verified_offline": True,
        "live_image_verified": False, "flash_authorized": False,
    }


def assess_placement(image: bytes, capture: dict, *, proposed_vendor_file_size=None) -> dict:
    """Bind configured extents to pinned code; never promote supplied provenance.

    A proposed size is arithmetic only, not a reviewed candidate binary. The
    current capture may describe V2 while the image under study is stock: this
    deliberate comparison must not be presented as a full live stock attestation.
    """
    audit = audit_image(image)
    size = len(image) if proposed_vendor_file_size is None else proposed_vendor_file_size
    report = c.analyze_capture(capture, vendor_file_size=size)
    if report["missing_descriptor_banks"] or not report["banks"]:
        raise ValueError("exact bank descriptor is required for placement comparison")
    bank = next((b for b in report["banks"] if b["bank"] == "bank0"), None)
    if bank is None:
        raise ValueError("reviewed route requires bank0 descriptor")
    app = next(p for p in bank["partitions"] if p["name"] == "app")
    tmp = next(r for r in report["flash_regions"] if r["name"] == "ota_tmp")
    agreement = (app["address"] == c.APP_FLASH_BASE and app["size"] == PARTITION_BYTES
                 and tmp["address"] == STAGING_BASE and tmp["size"] == PARTITION_BYTES)
    required = c.minimum_partition_bytes(size)
    fit = (agreement and INIT_MINIMUM <= size <= INIT_MAXIMUM and
           required <= min(app["size"], tmp["size"]))
    return {
        "schema": "whip.placement.audit.v1", "image_audit": audit,
        "capture_assessment": report,
        "proposed_vendor_file_bytes": size, "required_realtek_bytes": required,
        "configured_app": app, "configured_staging": tmp,
        "descriptor_and_oem_limits_agree": agreement,
        "configured_and_oem_size_fit": fit,
        "configured_capacity_margin_bytes": min(app["size"], tmp["size"]) - required,
        "transfer_receipt_is_flash_verification": False,
        "physical_chip_geometry_verified": False, "boot_copy_recovery_verified": False,
        "ram_ownership_verified": False, "candidate_binary_verified": False,
        "placement_approved": False, "flash_authorized": False,
        "remaining_blockers": [
            "Physical JEDEC/SFDP identity and actual erase/program geometry are not captured.",
            "Boot-ROM staging selection/copy/recovery and interrupted-copy behavior are not executed.",
            "OEM DATA credit does not propagate flash-write failure or bound each final chunk.",
            "Stock overlay tail is occupied; safe linked-code extension/metadata remains unproved.",
            "Nominal RAM slack is not an indirect-writer or future-heap-reserve proof.",
        ],
    }


class ProofError(RuntimeError):
    pass


class ThumbProof:
    """Real pinned Thumb; synthetic RAM; mocked flash, RTOS and unavailable ROM.

    Never executes a flash operation, even in the emulator. Records its arguments
    at the ROM boundary instead. Continued DATA excludes first-chunk header work;
    receipt and END witnesses are separate, explicitly bounded experiments.
    """
    STOP, CALLBACK = 0x3FFF0, 0x3FFE0
    PACKET, STACK = 0x300000, 0x301000

    def __init__(self, image: bytes):
        self.audit = audit_image(image)
        self.p = self.audit["sites"]
        self.context = self.audit["context_address"]
        self.buffer = self.audit["buffer_address"]
        import unicorn as u
        from unicorn import arm_const as a
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x800000, 0x20000, u.UC_PROT_READ)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, image)
        self.uc.mem_map(0x200000, 0x18000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x300000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.image_end = BIAS + len(image)
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)

    def _reset(self, *, total=138016, written=0, state=3, index=1):
        self.calls, self.executed, self.callbacks = [], set(), []
        self.finished = False
        self.packet_bytes = 0
        self.mutex_ok = self.flash_ok = self.checksum_ok = True
        self.mode = ""
        self.uc.mem_write(self.context, struct.pack("<BBHHHIIII", 4, state, 0, 0,
                           index, total, written, 0, self.CALLBACK | 1))
        self.uc.mem_write(self.audit["mutex_address"], struct.pack("<I", 0x1234))
        self.uc.mem_write(self.STACK - 256, b"\xa5" * 256)
        for register in (self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1,
                         self.a.UC_ARM_REG_R2, self.a.UC_ARM_REG_R3,
                         self.a.UC_ARM_REG_R4, self.a.UC_ARM_REG_R5,
                         self.a.UC_ARM_REG_R6, self.a.UC_ARM_REG_R7):
            self.uc.reg_write(register, 0)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, self.STOP | 1)

    def _return(self, value=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _write(self, uc, access, address, size, value, _):
        if self.STACK - 256 <= address < address + size <= self.STACK:
            return
        if self.context <= address < address + size <= self.context + 0x14:
            return
        raise ProofError(f"unexpected store outside synthetic context/stack: {address:#x}")

    def _read(self, uc, access, address, size, value, _):
        allowed = ((BIAS, self.image_end), (self.context, self.context + 24),
                   (self.audit["mutex_address"], self.audit["mutex_address"] + 4),
                   (self.PACKET, self.PACKET + self.packet_bytes),
                   (self.STACK - 256, self.STACK))
        if self.mode == "resolver":
            allowed += ((0x802198, 0x8021E8),)
        if not any(lo <= address < address + size <= hi for lo, hi in allowed):
            raise ProofError(f"unexpected load outside pinned image/bounded fixtures: {address:#x}")

    def _code(self, uc, address, size, _):
        p, a = self.p, self.a
        regs = [uc.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1,
                                        a.UC_ARM_REG_R2, a.UC_ARM_REG_R3)]
        r0, r1, r2, _r3 = regs
        if address == self.STOP or (self.mode == "end" and address == BIAS + p["after_checksum"]):
            self.finished = True
            uc.emu_stop()
            return
        if address == self.CALLBACK:
            self.callbacks.append((r0, r1))
            self._return()
            return
        if address in (0x53A4, 0x8A82, 0x8AE2):
            if self.mode != "resolver":
                raise ProofError("unexpected boot resolver ROM boundary")
            if address == 0x53A4:
                self.calls.append(("active_bank_MOCK",))
                self._return(0x802000)
            elif address == 0x8AE2:
                if r0 != 0x2793:
                    raise ProofError("unexpected header image id")
                self.calls.append(("header_address_MOCK", r0))
                self._return(c.APP_FLASH_BASE)
            elif (r0, r1) == (0x802000, 0x2790):
                self.calls.append(("bank_header_valid_MOCK", r0, r1))
                self._return(int(self.bank_header_ok))
            elif (r0, r1) == (c.APP_FLASH_BASE, 0x2793):
                self.calls.append(("app_header_valid_MOCK", r0, r1))
                self._return(int(self.app_header_ok))
            else:
                raise ProofError("unexpected header-valid arguments")
            return
        if address == BIAS + p["progress"]:
            self.calls.append(("progress_helper",))
            self._return(0)
            return
        if address == 0x3F848:
            if (self.mode != "data" or r0 != self.buffer or r1 != self.PACKET + 2
                    or r2 != self.payload_length):
                raise ProofError("unexpected memcpy; only bounded continued DATA is modeled")
            uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
            self.calls.append(("memcpy", r0, r1, r2))
            self._return(r0)
            return
        if address in (0x133F4, 0x1341C):
            if r0 != 0x1234 or (address == 0x133F4 and r1 != 500):
                raise ProofError("unexpected mutex arguments")
            self.calls.append(("mutex_take" if address == 0x133F4 else "mutex_give",))
            self._return(int(self.mutex_ok) if address == 0x133F4 else 1)
            return
        if address == 0x81A0:
            if r0 != 2:
                raise ProofError("expected SDK sector erase selector 2")
            self.calls.append(("flash_erase_NOT_EXECUTED", r0, r1))
            self._return(int(self.flash_ok))
            return
        if address == 0x8600:
            if r2 != self.buffer or not 0 <= r1 <= 1536:
                raise ProofError("unexpected flash write source or length")
            self.calls.append(("flash_write_NOT_EXECUTED", r0, r1, r2))
            self._return(int(self.flash_ok))
            return
        if address in (0x8B94, 0x8B7A, 0x8A5C, 0x3ED1A, 0x5AA8,
                       BIAS + 0xD30, BIAS + 0xD62):
            if address == 0x8B94:
                if r0 != 0x2793:
                    raise ProofError("expected APP image id")
                self.calls.append(("get_temp_address_MOCK", r0))
                self._return(STAGING_BASE)
            elif address == 0x8B7A:
                self.calls.append(("bank_switch_MOCK",))
                self._return(0)
            elif address == 0x8A5C:
                if r0 != STAGING_BASE:
                    raise ProofError("unexpected checksum address")
                self.calls.append(("checksum_MOCK", r0))
                self._return(int(self.checksum_ok))
            elif address == 0x3ED1A:
                if r0 != STAGING_BASE:
                    raise ProofError("unexpected ready address")
                self.calls.append(("set_ready_NOT_EXECUTED", r0))
                self._return()
            else:
                self.calls.append(("log_MOCK" if address == 0x5AA8 else "flash_lock_MOCK", address))
                self._return()
            return
        offset = address - BIAS
        allowed = {
            "init": [(p["init"], p["init"] + 0x76)],
            "data": [(p["data"], p["receipt"]), (p["erase"], p["erase"] + 0x24),
                     (p["write"], p["write"] + 0x2A), (p["shim"], p["shim"] + 0x12)],
            "shim": [(p["write"], p["write"] + 0x2A), (p["shim"], p["shim"] + 0x12)],
            "receipt": [(p["receipt"], p["end"])],
            "end": [(p["end"], p["after_checksum"]), (0xF66, 0xFD8)],
            "resolver": [(0x4E0, 0x52E)],
        }[self.mode]
        if not any(lo <= offset < offset + size <= hi for lo, hi in allowed):
            raise ProofError(f"execution left reviewed {self.mode} slices: {address:#x}")
        self.executed.add(offset)

    def _run(self, entry, *, r0=0, r1=0, r2=0, budget=1000):
        if type(budget) is not int or not 1 <= budget <= 10000:
            raise ValueError("instruction budget must be 1..10000")
        for register, value in ((self.a.UC_ARM_REG_R0, r0), (self.a.UC_ARM_REG_R1, r1),
                                (self.a.UC_ARM_REG_R2, r2)):
            self.uc.reg_write(register, value)
        self.uc.emu_start((BIAS + entry) | 1, 0, count=budget)
        if not self.finished:
            raise ProofError("instruction budget exhausted")
        if self.mode != "end" and self.uc.reg_read(self.a.UC_ARM_REG_SP) != self.STACK:
            raise ProofError("stack not restored")
        context = bytes(self.uc.mem_read(self.context, 24))
        return {"return_or_boundary_r0": self.uc.reg_read(self.a.UC_ARM_REG_R0),
                "context_state": context[1], "stored_vendor_file_bytes": struct.unpack_from("<I", context, 8)[0],
                "credited_bytes": struct.unpack_from("<I", context, 12)[0],
                "packet_index": struct.unpack_from("<H", context, 6)[0],
                "callbacks": list(self.callbacks), "calls_not_executed": list(self.calls),
                "executed_file_offsets": sorted(self.executed), "flash_authorized": False}

    def init_request(self, vendor_file_size, *, init_type=4, packet_length=9, budget=1000):
        _u32(vendor_file_size, "vendor file size")
        _u32(packet_length, "packet length")
        if type(init_type) is not int or not 0 <= init_type <= 255:
            raise ValueError("init type must be a byte")
        self._reset(state=0)
        self.mode = "init"
        self.packet_bytes = 9
        self.uc.mem_write(self.PACKET, struct.pack("<BIHH", init_type, vendor_file_size, 0x1234, 0x5678))
        return self._run(self.p["init"], r0=self.PACKET, r1=packet_length, budget=budget)

    def continued_data(self, *, total, written, payload_length, mutex_ok=True, flash_ok=True, budget=1000):
        for name, value in (("total", total), ("written", written), ("payload_length", payload_length)):
            _u32(value, name)
        if not 1 <= payload_length <= 1536:
            raise ValueError("proof covers bounded nonempty continued chunks only")
        if type(mutex_ok) is not bool or type(flash_ok) is not bool:
            raise ValueError("mock result must be bool")
        self._reset(total=total, written=written)
        self.mode, self.payload_length = "data", payload_length
        self.packet_bytes = payload_length + 2
        self.mutex_ok, self.flash_ok = mutex_ok, flash_ok
        self.uc.mem_write(self.PACKET, b"\x02\x00" + b"\x5a" * payload_length)
        return self._run(self.p["data"], r0=self.PACKET, r1=payload_length + 2, budget=budget)

    def write_shim(self, *, mutex_ok=True, flash_ok=True):
        if type(mutex_ok) is not bool or type(flash_ok) is not bool:
            raise ValueError("mock result must be bool")
        self._reset()
        self.mode = "shim"
        self.mutex_ok, self.flash_ok = mutex_ok, flash_ok
        return self._run(self.p["shim"], r0=STAGING_BASE, r1=self.buffer, r2=1024)

    def receipt_check(self, *, total, written, state=3):
        for name, value in (("total", total), ("written", written)):
            _u32(value, name)
        if type(state) is not int or not 0 <= state <= 255:
            raise ValueError("state must be a byte")
        self._reset(total=total, written=written, state=state)
        self.mode = "receipt"
        return self._run(self.p["receipt"])

    def end_checksum_boundary(self, *, checksum_ok):
        """Stop BEFORE END's first subsequent helper; never run reset/activation.

        The genuine END caller and f7a checksum helper run together. All ROM
        checks/ready/locks are explicit mocks. This shows continuation even when
        the checksum helper returns false, not that bad bytes become bootable.
        """
        if type(checksum_ok) is not bool:
            raise ValueError("mock checksum result must be bool")
        self._reset(state=4)
        self.mode, self.checksum_ok = "end", checksum_ok
        return self._run(self.p["end"])

    def resolve_app_header(self, descriptor: bytes, *, bank_header_ok=True, app_header_ok=True):
        """Real startup descriptor lookup; active-bank/header-valid ROM is mocked.

        Only the supplied 80-byte descriptor and pinned APP header are readable.
        No returned pointer is followed outside those fixed fixtures. A zero
        APP size is deliberately accepted as a negative instruction-test input.
        """
        if type(descriptor) is not bytes or len(descriptor) != 80:
            raise ValueError("descriptor witness requires exactly 80 bytes")
        if type(bank_header_ok) is not bool or type(app_header_ok) is not bool:
            raise ValueError("mock header results must be bool")
        self._reset()
        self.mode = "resolver"
        self.bank_header_ok, self.app_header_ok = bank_header_ok, app_header_ok
        self.uc.mem_write(0x802198, descriptor)
        return self._run(0x4E0, r0=0x2793)
