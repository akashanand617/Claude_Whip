"""One fixed ROM-code capture for real placement/cancellation integration.

Data reads only. No private data, keys, MMIO, returned pointers or on-device
execution. Symbol-bounded code spans are fixed here, never caller parameters.
CD01 still has the separately audited bookkeeping side effects.
"""
import hashlib

from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr

WINDOWS = (
    ("ram_boot", 0x4A78, 0x53A4 - 0x4A78),
    ("flash_layout", 0x805E, 0x81A0 - 0x805E),
    ("ota_headers", 0x8A5C, 0x8C72 - 0x8A5C),
    ("timer_queue", 0x105C8, 0x10FB8 - 0x105C8),
    ("critical_sections", 0x1105E, 0x111A6 - 0x1105E),
)
TOTAL_BYTES = sum(n for _, _, n in WINDOWS)
EXPECTED_TRANSACTIONS = 91 + 4 + 2 * sum(len(cr.chunks(a, n)) for _, a, n in WINDOWS) + 7
SCHEMA = "whip.rom-integration.capture.v1"


class IntegrationReader(cr.DescriptorReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = self._started = False
        self._code_phase = None

    def _allowed_reads(self):
        if self.closed: return frozenset()
        allowed = super()._allowed_reads()
        phases = {name: (a, n) for name, a, n in WINDOWS}
        phases["identifier"] = rr.UUID_WINDOW
        if self._code_phase in phases:
            allowed |= frozenset(cr.chunks(*phases[self._code_phase]))
        return allowed


def validate_symbols(symbols):
    if hashlib.sha256(symbols).hexdigest() != rr.SYMBOLS_SHA256:
        raise ValueError("unreviewed ROM symbol map")
    boundaries = (("update_ram_layout", 0x4A79), ("get_active_ota_bank_addr", 0x53A5),
        ("flash_dump_flash_info", 0x805F), ("flash_erase_locked", 0x81A1),
        ("check_image_chksum", 0x8A5D), ("get_active_bank_image_version", 0x8C73),
        ("vTaskStatusDump", 0x105C9), ("pxPortInitialiseStack", 0x10FB9),
        ("vPortEnterCritical", 0x1105F), ("vTimerCreateFailedHook", 0x111A7))
    lines = set(symbols.splitlines())
    for name, address in boundaries:
        if f"{name} = 0x{address:08x} ;".encode() not in lines:
            raise ValueError("fixed integration-code boundary differs from symbol map")


async def collect(reader, base, candidate, symbols, session_id):
    if not isinstance(reader, IntegrationReader): raise ValueError("separate integration reader required")
    if reader._started or reader.closed: raise RuntimeError("integration session already used; no retry")
    reader._started = True
    try:
        rr.validate_references(base, candidate, symbols)
        validate_symbols(symbols)
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config["windows"] if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != rr.DESCRIPTOR_SHA256:
            raise RuntimeError("unreviewed descriptor; no integration code read")
        reader._code_phase = "identifier"
        for _ in range(2):
            if await reader.window(*rr.UUID_WINDOW) != rr.ROM_UUID:
                raise RuntimeError("application ROM identifier differs")
        windows = {}
        for name, address, length in WINDOWS:
            reader._code_phase = name
            first = await reader.window(address, length)
            repeated = await reader.window(address, length)
            reader._code_phase = None
            if first != repeated: raise RuntimeError("ROM code changed across repeats: " + name)
            windows[name] = {"address": address, "data_hex": first.hex(),
                             "sha256": hashlib.sha256(first).hexdigest()}
        for address, length in cr.CONFIG_WINDOWS:
            expected = cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS else cr.EXPECTED_FLASH_CONFIG
            if await reader.window(address, length) != expected: raise RuntimeError("configuration changed")
        if await reader.read(*cr.IDLE_WINDOW) != b"\0": raise RuntimeError("raw mode changed")
        reader.emit({"kind": "rom_integration", "bytes": TOTAL_BYTES, "repeated_equal": True,
                     "keys_read": False, "pointer_following": False, "target_execution": False})
        return {"schema": SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                "prerequisite_capture": config, "symbols_sha256": rr.SYMBOLS_SHA256,
                "app_rom_identifier": rr.ROM_UUID.hex(), "windows": windows,
                "repeated_equal": True, "keys_read": False, "pointer_following": False,
                "target_execution": False, "full_image_attestation": False,
                "recovery_verified": False, "flash_authorized": False}
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._code_phase = None
        reader._descriptor_phase = False
        reader.closed = True
