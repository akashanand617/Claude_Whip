"""Prepared fixed create-hook code read; no execution or dynamic pointer chasing.

The completed support capture fixed 0x205c01 as a lead, NOT code provenance.
A new coordinated session repeats all prior evidence before a bounded header
check and fixed code caps. Neither new literals nor hook values choose targets.
"""
import hashlib
import json
import struct

from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr, fwrom_resume as tr
from whip import fwrom_support as sr

SUPPORT_SHA256 = "bcbffd1362964a186797e815fe15a17d4b66e0b1a8a54918cc09fd20d5cb874a"
SCHEMA = "whip.rom-create-hook.capture.v1"
KNOWN_WINDOWS = sr.KNOWN_WINDOWS + sr.WINDOWS + (("header_compare_call", 0x8AC8, 4),)
PATCH_HEADER = ("nonsecret_patch_header", 0x803000, 52)
CODE_WINDOWS = (("create_hook_ram_cap", 0x205C00, 256),
                ("header_compare_rom_cap", 0x8E24, 128))
NEW_WINDOWS = (PATCH_HEADER,) + CODE_WINDOWS
TOTAL_ROM_BYTES = sum(n for _, a, n in KNOWN_WINDOWS + CODE_WINDOWS if a < 0x200000)
EXPECTED_TRANSACTIONS = (91 + 4 + 7 +
    2 * sum(len(cr.chunks(a, n)) for _, a, n in KNOWN_WINDOWS + NEW_WINDOWS) +
    sum(len(cr.chunks(a, n)) for _, a, n in sr.STATE_WINDOWS + (PATCH_HEADER,)))


def validate_archives(stop, resume, integration, support):
    known = sr.validate_archives(stop, resume, integration)
    if hashlib.sha256(support).hexdigest() != SUPPORT_SHA256:
        raise ValueError("unreviewed support capture")
    saved = json.loads(support)
    for name, address, length in sr.WINDOWS:
        w = saved["windows"][name]; data = bytes.fromhex(w["data_hex"])
        if (w["address"] != address or len(data) != length or
                hashlib.sha256(data).hexdigest() != w["sha256"]):
            raise ValueError("invalid support prerequisite window")
        known[name] = data
    if known["create_start_restart_hook_snapshot"] != struct.pack("<III", 0x205C01, 0, 0):
        raise ValueError("unreviewed create-hook lead")
    window = json.loads(integration)["windows"]["ota_headers"]
    offset = 0x8AC8 - window["address"]
    known["header_compare_call"] = bytes.fromhex(window["data_hex"])[offset:offset + 4]
    if len(known["header_compare_call"]) != 4:
        raise ValueError("missing prior comparator call")
    return known


def validate_patch_header(raw):
    """Conservative containment gate, NOT authenticity/load/ownership proof.

Only 52 non-secret bytes are read. Never inspect dec_key at +0x34 or use
declared addresses as read targets. The SDK header is NOT an equality oracle.
"""
    if len(raw) != 52:
        raise ValueError("requires exactly the non-secret patch prefix")
    ic, _, flags, image_id, _, payload = struct.unpack_from("<BBHHHI", raw)
    execute, source, length, image_base = struct.unpack_from("<IIII", raw, 28)
    if (ic != 12 or image_id != 0x2792 or raw[12:28] != rr.ROM_UUID or
            flags & 0x80 or not flags & 4 or flags & 0xE000):
        raise RuntimeError("unreviewed ROM-patch header identity/flags")
    # Exact declared bank0 ROM-patch extent is 0x803000..0x80d000. Bit 24
    # aliases are accepted only in these two whole fixed source ranges.
    if image_base not in (0x803000, 0x1803000) or not 0 < payload <= 0x9C00:
        raise RuntimeError("unreviewed ROM-patch image extent")
    source_plain = source - 0x1000000 if 0x1803400 <= source < 0x180D000 else source
    if (source_plain & 3 or not 0x803400 <= source_plain < 0x80D000 or
            length & 3 or not 0 < length <= 0x9C00 or
            source_plain + length > 0x803400 + payload):
        raise RuntimeError("unreviewed ROM-patch load-source extent")
    if execute != 0x203800 or not 0x205D00 <= execute + length <= 0x207C00:
        raise RuntimeError("fixed hook cap not in reviewed declared RAM extent")
    return {"ic_type": ic, "image_id": image_id, "control_flags": flags,
            "payload_bytes": payload, "declared_ram_start": execute,
            "declared_load_source": source, "declared_load_bytes": length,
            "declared_image_base": image_base,
            "containment_checked": True, "authenticity_verified": False,
            "ram_ownership_verified": False, "runtime_copy_verified": False}


class CreateHookReader(cr.DescriptorReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = self._started = False
        self._hook_phase = None

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        phases = {name: (a, n) for name, a, n in KNOWN_WINDOWS + NEW_WINDOWS}
        phases["identifier"] = rr.UUID_WINDOW
        if self._hook_phase in phases:
            allowed |= frozenset(cr.chunks(*phases[self._hook_phase]))
        return allowed


async def collect(reader, base, candidate, symbols, session_id, stop, resume, integration, support):
    if not isinstance(reader, CreateHookReader):
        raise ValueError("separate fixed create-hook reader required")
    if reader._started or reader.closed:
        raise RuntimeError("create-hook session already used; no retry")
    reader._started = True
    try:
        rr.validate_references(base, candidate, symbols)
        tr.validate_symbols(symbols)
        known = validate_archives(stop, resume, integration, support)
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config["windows"] if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != rr.DESCRIPTOR_SHA256:
            raise RuntimeError("unreviewed descriptor; no create-hook read")
        reader._hook_phase = "identifier"
        for _ in range(2):
            if await reader.window(*rr.UUID_WINDOW) != rr.ROM_UUID:
                raise RuntimeError("application ROM identifier differs")
        # All prior ROM AND fixed state must match their pinned captures twice.
        # A changed hook value never becomes a target or an alternate plan.
        for name, address, length in KNOWN_WINDOWS:
            reader._hook_phase = name
            for _ in range(2):
                if await reader.window(address, length) != known[name]:
                    raise RuntimeError("known create-hook prerequisite differs: " + name)
        windows = {}; header_fields = None
        for name, address, length in NEW_WINDOWS:
            reader._hook_phase = name
            first = await reader.window(address, length)
            repeated = await reader.window(address, length)
            reader._hook_phase = None
            if first != repeated:
                raise RuntimeError("create-hook code/header changed across repeats: " + name)
            if name == PATCH_HEADER[0]:
                header_fields = validate_patch_header(first)  # BEFORE fixed RAM or ROM cap.
            windows[name] = {"address": address, "data_hex": first.hex(),
                             "sha256": hashlib.sha256(first).hexdigest()}
        for name, address, length in sr.STATE_WINDOWS + (PATCH_HEADER,):
            reader._hook_phase = name
            expected = known[name] if name in known else bytes.fromhex(windows[name]["data_hex"])
            if await reader.window(address, length) != expected:
                raise RuntimeError("create-hook state/header postcheck changed: " + name)
        reader._hook_phase = None
        for address, length in cr.CONFIG_WINDOWS:
            expected = cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS else cr.EXPECTED_FLASH_CONFIG
            if await reader.window(address, length) != expected:
                raise RuntimeError("configuration changed")
        if await reader.read(*cr.IDLE_WINDOW) != b"\0":
            raise RuntimeError("raw mode changed")
        reader.emit({"kind": "rom_create_hook", "new_code_bytes": 384,
                     "nonsecret_header_bytes": 52, "repeated_equal": True,
                     "target_execution": False, "pointer_following": False})
        return {"schema": SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                "prerequisite_capture": config, "prior_support_sha256": SUPPORT_SHA256,
                "app_rom_identifier": rr.ROM_UUID.hex(), "windows": windows,
                "header_fields": header_fields, "known_code_state_repeated_equal": True,
                "repeated_equal": True, "final_state_header_equal": True,
                "keys_read": False, "pointer_following": False, "target_execution": False,
                "runtime_copy_verified": False, "state_immutable": False,
                "full_image_attestation": False, "recovery_verified": False, "flash_authorized": False}
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._hook_phase = None
        reader._descriptor_phase = False
        reader.closed = True
