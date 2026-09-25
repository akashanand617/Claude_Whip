"""Offline-only bank/configuration evidence checks; never authorizes a flash.

Input claims and self-supplied hashes are not physical attestation. Synthetic
fixtures can pass structural checks but cannot close a device safety gate.
No BLE client, arbitrary memory reader, patcher or image writer exists here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import struct


SCHEMA = "whip.capacity.capture.v1"
RAM_CONFIG_ADDRESS = 0x200380
FLASH_CONFIG_ADDRESS = 0x2003E4
DESCRIPTOR_OFFSET = 0x198
DESCRIPTOR_BYTES = 80
FLASH_BASE = 0x800000
# Syntactic address envelope only, NOT measured physical chip capacity.
FLASH_ADDRESS_LIMIT = 0x1000000
APP_FLASH_BASE = 0x826000
RAM_LIMIT = 0x218000
BIAS = 0x825FB0
STOCK_SHA256 = "b58fd30355d9c88ff7a8331c83e4c3d2808fa0463d8f03f27f4d7191a5b750b0"
ORIGINAL_SHA256 = "f13e63d3fdef3b10aa20fd4e0672077b66f60bb19c689ef64053840e4d35d3d9"
V2_SHA256 = "0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c"
IMAGE_NAMES = {STOCK_SHA256: "stock", ORIGINAL_SHA256: "original25Hz", V2_SHA256: "optical_off_v2"}
REGION_NAMES = ("bank0", "bank1", "ftl", "ota_tmp", "backup1", "backup2")
IMAGE_NAMES_IN_BANK = ("secure_boot", "rom_patch", "app", "app_data1", "app_data2",
                       "app_data3", "app_data4", "app_data5", "app_data6", "upperstack")


def _integer(value, name, maximum=0xFFFFFFFF):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an unsigned integer <= {maximum}")
    return value


def _exact_bytes(data, length):
    if type(data) is not bytes or len(data) != length:
        raise ValueError(f"requires exactly {length} bytes")


@dataclass(frozen=True)
class Region:
    name: str
    address: int
    size: int

    @property
    def end(self):
        return self.address + self.size

    def as_dict(self):
        return {**asdict(self), "end_exclusive": self.end}


def _region(name, address, size, *, lower=FLASH_BASE, upper=FLASH_ADDRESS_LIMIT):
    """Conservative 4 KiB partition policy, not a claim about erase geometry."""
    _integer(address, "region address")
    _integer(size, "region size")
    if address % 0x1000 or size % 0x1000:
        raise ValueError(f"{name}: partition is not 4 KiB aligned; needs separate review")
    if size == 0:
        # SDK configurations also use the next-region address for empty slots.
        if address != 0 and not lower <= address <= upper:
            raise ValueError(f"{name}: invalid empty-slot address")
    elif not lower <= address < address + size <= upper:
        raise ValueError(f"{name}: extent outside allowed address envelope")
    return Region(name, address, size)


def _nonoverlap(regions):
    occupied = sorted((r for r in regions if r.size), key=lambda r: r.address)
    for a, b in zip(occupied, occupied[1:]):
        if a.end > b.address:
            raise ValueError(f"overlapping regions: {a.name} / {b.name}")


def parse_ram_config(data: bytes) -> dict:
    _exact_bytes(data, 16)
    app, size, data_heap, buffer_heap = struct.unpack("<4I", data)
    if any(x % 4 for x in (app, size, data_heap, buffer_heap)):
        raise ValueError("RAM configuration is not word aligned")
    if not size or not 0x200000 <= app < app + size <= RAM_LIMIT:
        raise ValueError("application RAM extent is outside RAM")
    if app + size + data_heap > RAM_LIMIT or buffer_heap > RAM_LIMIT - 0x200000:
        raise ValueError("heap configuration exceeds conservative RAM bounds")
    return {"app_address": app, "app_bytes": size, "app_end_exclusive": app + size,
            "data_heap_bytes": data_heap, "buffer_heap_bytes": buffer_heap,
            "matches_nominal_stock_reservation": (app, size, data_heap) == (0x207C00, 0x7000, 0x7400),
            "free_bytes_proven": None, "allocation_approved": False}


def parse_flash_config(data: bytes) -> tuple[Region, ...]:
    _exact_bytes(data, 48)
    words = struct.unpack("<12I", data)
    regions = tuple(_region(name, words[2 * i], words[2 * i + 1])
                    for i, name in enumerate(REGION_NAMES))
    _nonoverlap(regions)
    if not any(r.size for r in regions[:2]):
        raise ValueError("no configured OTA bank")
    return regions


def inspect_flash_config(data: bytes, *, image_sha256: str) -> dict:
    """Separate validated primary ranges from a known virtual/opaque override.

    The two pinned 25 Hz images WRITE backup1=(0x01000000,0x00800000) at
    startup. That declaration lies outside this audit's primary flash envelope.
    Recognizing the exact instruction result does not establish external flash,
    an alias, physical capacity or a usable read target. Never return it as a
    validated Region. The strict parse_flash_config API deliberately still
    rejects it. Every other out-of-envelope declaration remains an error.
    """
    _exact_bytes(data, 48)
    words = struct.unpack("<12I", data)
    known_override = (image_sha256 in (ORIGINAL_SHA256, V2_SHA256)
                      and words[8:10] == (0x01000000, 0x00800000))
    if not known_override:
        return {"regions": parse_flash_config(data), "unresolved": [], "complete": True}
    regions = tuple(_region(name, words[2 * i], words[2 * i + 1])
                    for i, name in enumerate(REGION_NAMES) if i != 4)
    _nonoverlap(regions)
    if not any(r.size for r in regions[:2]):
        raise ValueError("no configured OTA bank")
    return {"regions": regions, "complete": False, "unresolved": [{
        "name": "backup1", "declared_address": words[8], "declared_size": words[9],
        "reason": "exact application-written declaration outside reviewed primary-flash envelope",
        "startup_store_files": [0x6FA, 0x6FE], "physical_capacity_verified": False,
        "read_target_approved": False,
    }]}


def parse_bank_descriptors(data: bytes, bank: Region) -> tuple[Region, ...]:
    _exact_bytes(data, DESCRIPTOR_BYTES)
    if type(bank) is not Region or bank.name not in ("bank0", "bank1"):
        raise ValueError("descriptor parent must be an OTA bank")
    checked = _region(bank.name, bank.address, bank.size)
    if not checked.size:
        raise ValueError("cannot inspect an absent bank")
    words = struct.unpack("<20I", data)
    regions = tuple(_region(name, words[2 * i], words[2 * i + 1],
                            lower=bank.address, upper=bank.end)
                    for i, name in enumerate(IMAGE_NAMES_IN_BANK))
    _nonoverlap(regions)
    for r in regions:
        if r.size and r.address < bank.address + 0x400:
            raise ValueError(f"{r.name}: overlaps bank header")
    if not regions[2].size:
        raise ValueError("bank descriptor has no application partition")
    return regions


def minimum_partition_bytes(vendor_file_size: int) -> int:
    _integer(vendor_file_size, "vendor file size")
    if vendor_file_size < 0x450:
        raise ValueError("file is too short for vendor and Realtek headers")
    return vendor_file_size - 0x50


def _keys(obj, names, description):
    if type(obj) is not dict or set(obj) != set(names):
        raise ValueError(f"{description}: unexpected or missing keys")


def _window(obj):
    _keys(obj, ("address", "data_hex", "sha256"), "window")
    address = _integer(obj["address"], "window address")
    raw = obj["data_hex"]
    if type(raw) is not str or not re.fullmatch(r"(?:[0-9a-f]{2}){1,80}", raw):
        raise ValueError("window must contain 1..80 bytes of canonical lowercase hex")
    data = bytes.fromhex(raw)
    if obj["sha256"] != hashlib.sha256(data).hexdigest():
        raise ValueError("window content hash mismatch")
    return address, data


def analyze_capture(capture: dict, *, vendor_file_size: int) -> dict:
    """Validate narrowly scoped supplied data; claims never become attestation.

    A declared device_capture is still unauthenticated. Raw packet correlation,
    exact live image, capture chronology and chip identity need independent
    review. This API intentionally has no option to turn those checks green.
    """
    _keys(capture, ("schema", "evidence_kind", "session_id", "image_sha256", "windows"), "capture")
    if capture["schema"] != SCHEMA:
        raise ValueError("unsupported capture schema")
    if capture["evidence_kind"] not in ("synthetic_fixture", "device_capture"):
        raise ValueError("unknown declared evidence kind")
    if type(capture["session_id"]) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", capture["session_id"]):
        raise ValueError("invalid session identifier")
    if type(capture["image_sha256"]) is not str or capture["image_sha256"] not in IMAGE_NAMES:
        raise ValueError("unreviewed declared image hash")
    if type(capture["windows"]) is not list or not 2 <= len(capture["windows"]) <= 4:
        raise ValueError("requires two configuration windows and at most two bank windows")
    windows = {}
    for item in capture["windows"]:
        address, data = _window(item)
        if address in windows:
            raise ValueError("duplicate window address")
        windows[address] = data
    if not {RAM_CONFIG_ADDRESS, FLASH_CONFIG_ADDRESS} <= windows.keys():
        raise ValueError("missing exact RAM/flash configuration windows")
    ram = parse_ram_config(windows[RAM_CONFIG_ADDRESS])
    inspected = inspect_flash_config(windows[FLASH_CONFIG_ADDRESS], image_sha256=capture["image_sha256"])
    flash = inspected["regions"]
    allowed = {RAM_CONFIG_ADDRESS, FLASH_CONFIG_ADDRESS}
    allowed.update(r.address + DESCRIPTOR_OFFSET for r in flash[:2] if r.size)
    if not windows.keys() <= allowed:
        raise ValueError("unreviewed memory window; no arbitrary or full OTP input")
    required = minimum_partition_bytes(vendor_file_size)
    banks, missing, app_matches = [], [], []
    for bank in flash[:2]:
        if not bank.size:
            continue
        address = bank.address + DESCRIPTOR_OFFSET
        if address not in windows:
            missing.append(bank.name)
            continue
        parts = parse_bank_descriptors(windows[address], bank)
        app = parts[2]
        if app.address == APP_FLASH_BASE:
            app_matches.append(bank.name)
        banks.append({"bank": bank.name, "partitions": [p.as_dict() for p in parts],
                      "configured_app_fit": required <= app.size,
                      "configured_app_margin_bytes": app.size - required,
                      "active_bank_verified": False})
    return {
        "schema": SCHEMA, "session_id": capture["session_id"],
        "declared_evidence_kind": capture["evidence_kind"],
        "declared_image": IMAGE_NAMES[capture["image_sha256"]],
        "declared_image_sha256": capture["image_sha256"],
        "window_hashes": {hex(a): hashlib.sha256(b).hexdigest() for a, b in sorted(windows.items())},
        "ram_configuration": ram, "flash_regions": [r.as_dict() for r in flash],
        "complete_flash_map_validated": inspected["complete"],
        "unresolved_flash_declarations": inspected["unresolved"],
        "banks": banks, "missing_descriptor_banks": missing,
        "banks_describing_known_app_base": app_matches,
        "minimum_partition_bytes": required,
        "ota_tmp_configured_fit": next(r for r in flash if r.name == "ota_tmp").size >= required,
        "physical_evidence_verified": False, "live_image_verified": False,
        "staging_route_verified": False, "flash_chip_capacity_verified": False,
        "placement_approved": False, "flash_authorized": False,
        "limitations": ["configuration values are not chip capacity or live-image attestation",
                        "active bank, OTA route, header validity and erase/program geometry remain unverified",
                        "RAM ownership, indirect writers, retention and heap reserve remain unverified",
                        "self-supplied hashes detect content mismatch, not provenance or request correlation"],
    }


def load_capture(text: str) -> dict:
    """Reject duplicate JSON keys instead of silently keeping the final value."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    if type(text) is not str or len(text) > 8192:
        raise ValueError("capture must be a bounded JSON document")
    result = json.loads(text, object_pairs_hook=unique,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if type(result) is not dict:
        raise ValueError("capture must be a JSON object")
    return result


def audit_cd_image(data: bytes) -> dict:
    """Image-specific CD01 path; exact archives, not proof of installed image."""
    digest = hashlib.sha256(data).hexdigest()
    if digest not in (ORIGINAL_SHA256, V2_SHA256) or len(data) != 137540:
        raise ValueError("CD audit requires exact pinned original25Hz or V2 image")
    return {"image": IMAGE_NAMES[digest], "sha256": digest,
            "rom_uuid": data[0x5C:0x6C].hex(),
            "callback_file": 0x78AA, "length_gate_file": 0x59D8,
            "dispatcher_file": 0x564A, "prelude_call_file": 0x5658,
            "prelude_file": 0x7EEE, "state_getter_file": 0x94CC,
            "state_byte_ram": 0x20BBF0, "unconditional_flag_ram": 0x20A664,
            "conditional_states": [2, 3], "timer_restart_file": 0x7ECA,
            "policy_helper_file": 0x9276, "cd_handler_file": 0x4B16,
            "reply_helper_file": 0x7C0C, "max_data_bytes": 14,
            "side_effect_free": False, "hardware_session_authorized": False,
            "warning": "prelude helper bodies, ROM and BLE/RTOS effects are not fully modeled"}


class CDProofError(RuntimeError):
    pass


class CDReadHarness:
    """Actual 25Hz/V2 dispatcher + prelude + CD01 Thumb witness.

    Timer-restart and policy-helper bodies are explicit observation boundaries.
    ROM memcpy is bounded to the fixture's one non-secret RAM data window. The
    stock checksum executes, but TX is captured before its queue side effects.
    Synthetic packet/stack RAM is outside real ring RAM. Never talks to hardware.
    """
    STOP = 0x3FFF0
    STACK = 0x301000
    PACKET = 0x300000

    def __init__(self, image: bytes):
        self.audit = audit_cd_image(image)
        import unicorn as u
        from unicorn import arm_const as a
        self.u, self.a = u, a
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0, 0x40000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(BIAS, image)
        self.uc.mem_map(0x200000, 0x18000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_map(0x300000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)
        self.calls, self.writes, self.executed = [], [], set()
        self.reply = None
        self.returned = False
        self.backup_setup = False

    def _return(self, value=0):
        self.uc.reg_write(self.a.UC_ARM_REG_R0, value)
        self.uc.reg_write(self.a.UC_ARM_REG_PC, self.uc.reg_read(self.a.UC_ARM_REG_LR))

    def _write(self, uc, access, address, size, value, _):
        if self.backup_setup:
            expected = {(BIAS + 0x6FA, 0x200404, 4, 0x01000000),
                        (BIAS + 0x6FE, 0x200408, 4, 0x00800000)}
            if (uc.reg_read(self.a.UC_ARM_REG_PC), address, size, value) not in expected:
                raise CDProofError("unexpected backup declaration store")
            self.writes.append((address, value))
            return
        if self.STACK - 128 <= address < address + size <= self.STACK:
            return
        if (uc.reg_read(self.a.UC_ARM_REG_PC), address, size, value) == (BIAS + 0x7F12, 0x20A664, 1, 1):
            self.writes.append((address, value))
            return
        raise CDProofError("unexpected write outside reviewed stack/prelude flag")

    def _code(self, uc, address, size, _):
        if self.backup_setup:
            if address == BIAS + 0x700:
                self.returned = True
                uc.emu_stop()
                return
            if not BIAS + 0x6F2 <= address < address + size <= BIAS + 0x700:
                raise CDProofError("execution left backup declaration setup slice")
            self.executed.add(address - BIAS)
            return
        if address == self.STOP:
            self.returned = True
            uc.emu_stop()
            return
        a = self.a
        r0, r1, r2 = [uc.reg_read(r) for r in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2)]
        if address in (BIAS + 0x7ECA, BIAS + 0x9276):
            if address == BIAS + 0x9276 and (r0, r1) != (0, 0):
                raise CDProofError("unexpected policy-helper arguments")
            self.calls.append(address - BIAS)
            self._return()
            return
        if address == 0x3F848:
            if (r1, r2) != (RAM_CONFIG_ADDRESS, self.copy_length) or r0 != self.STACK - 32 + 1:
                raise CDProofError("unexpected memcpy outside fixture window/reply")
            uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
            self._return(r0)
            return
        if address == BIAS + 0x7C0C:
            if r0 != self.STACK - 32:
                raise CDProofError("unexpected reply address")
            self.reply = bytes(uc.mem_read(r0, 16))
            self._return()
            return
        offset = address - BIAS
        if not any(lo <= offset and offset + size <= hi for lo, hi in
                   ((0x564A, 0x59D8), (0x7EEE, 0x7F16), (0x94CC, 0x94D2),
                    (0x4B16, 0x4B9C), (0x3EEC, 0x3F06))):
            raise CDProofError(f"execution left reviewed CD slices: {address:#x}")
        self.executed.add(offset)

    def run(self, state: int, *, length=14, budget=1000) -> dict:
        _integer(state, "fixture state", 255)
        _integer(length, "fixture read length", 255)
        if type(budget) is not int or not 1 <= budget <= 10000:
            raise ValueError("invalid instruction budget")
        self.backup_setup = False
        self.calls.clear(); self.writes.clear(); self.executed.clear()
        self.reply, self.returned = None, False
        self.copy_length = min(length, 14)
        source = bytes(range(16))  # synthetic, no captured OTP or device data
        packet = bytes([0xCD, 1, length]) + RAM_CONFIG_ADDRESS.to_bytes(4, "big") + bytes(9)
        self.uc.mem_write(self.PACKET, packet)
        self.uc.mem_write(RAM_CONFIG_ADDRESS, source)
        self.uc.mem_write(0x20BBF0, bytes([state]))
        self.uc.mem_write(0x20A664, b"\x00")
        self.uc.mem_write(self.STACK - 128, b"\xa5" * 128)
        a = self.a
        for register in (a.UC_ARM_REG_R0, a.UC_ARM_REG_R1, a.UC_ARM_REG_R2, a.UC_ARM_REG_R3,
                         a.UC_ARM_REG_R4, a.UC_ARM_REG_R5, a.UC_ARM_REG_R6, a.UC_ARM_REG_R7):
            self.uc.reg_write(register, 0)
        self.uc.reg_write(a.UC_ARM_REG_R0, self.PACKET)
        self.uc.reg_write(a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(a.UC_ARM_REG_LR, self.STOP | 1)
        self.uc.emu_start((BIAS + 0x564A) | 1, 0, count=budget)
        if not self.returned or self.reply is None:
            raise CDProofError("CD instruction budget exhausted or reply missing")
        if self.uc.reg_read(a.UC_ARM_REG_SP) != self.STACK:
            raise CDProofError("CD stack not restored")
        if bytes(self.uc.mem_read(RAM_CONFIG_ADDRESS, 16)) != source:
            raise CDProofError("CD modified source data")
        return {"calls_not_executed": list(self.calls), "writes": list(self.writes),
                "reply": self.reply, "executed": sorted(self.executed)}

    def startup_backup_declaration(self) -> dict:
        """Execute only the seven real startup instructions, not boot or ROM."""
        self.backup_setup = True
        self.writes.clear()
        self.executed.clear()
        self.returned = False
        self.uc.mem_write(0x200400, b"\xa5" * 16)
        self.uc.reg_write(self.a.UC_ARM_REG_R0, 0)
        self.uc.reg_write(self.a.UC_ARM_REG_R1, 0)
        try:
            self.uc.emu_start((BIAS + 0x6F2) | 1, 0, count=16)
            if not self.returned:
                raise CDProofError("backup setup budget exhausted")
            surrounding = bytes(self.uc.mem_read(0x200400, 16))
            if surrounding[:4] != b"\xa5" * 4 or surrounding[12:] != b"\xa5" * 4:
                raise CDProofError("backup setup changed neighboring configuration")
            return {"writes": list(self.writes), "executed": sorted(self.executed),
                    "physical_capacity_verified": False}
        finally:
            self.backup_setup = False
