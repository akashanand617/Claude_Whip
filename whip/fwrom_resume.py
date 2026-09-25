"""Fixed timer create/start/restart ROM DATA plan; no timer operation or flash.

Requires new exclusive idle coordination. The CD01 dispatcher has known
bookkeeping side effects. This plan never follows a returned function pointer,
reads hook-state RAM, executes the inspected code or reads keys/peripherals.
"""
import hashlib

from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr

# Begin/end are exported symbol boundaries or fixed neighbors of the previously
# captured stop wrapper/default. The last window ends BEFORE the known STOP
# default at 0x140ce. A capture boundary is not a full-callee closure claim.
WINDOWS = (
    ("create_start_restart_wrappers", 0x13634, 0x136BC - 0x13634),
    ("adjacent_timer_literals", 0x137EC, 0x137F8 - 0x137EC),
    ("create_start_restart_backends", 0x13F9E, 0x140CE - 0x13F9E),
)
TOTAL_NEW_BYTES = sum(n for _, _, n in WINDOWS)
EXPECTED_TRANSACTIONS = (91 + 4 + 2 * len(cr.chunks(*rr.TIMER_WINDOW)) +
                         2 * sum(len(cr.chunks(a, n)) for _, a, n in WINDOWS) + 7)
SCHEMA = "whip.rom-timer-resume-code.capture.v1"


def validate_symbols(symbols):
    if hashlib.sha256(symbols).hexdigest() != rr.SYMBOLS_SHA256:
        raise ValueError("unreviewed ROM symbol map")
    lines = set(symbols.splitlines())
    for name, address in (("os_timer_create", 0x13635), ("os_timer_start", 0x13671),
                          ("os_timer_restart", 0x13695), ("os_timer_stop", 0x136BD),
                          ("osif_timer_create", 0x13F9F)):
        if f"{name} = 0x{address:08x} ;".encode() not in lines:
            raise ValueError("timer resume-code symbol boundary mismatch")


class ResumeCodeReader(cr.DescriptorReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = self._started = False
        self._code_phase = None

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        phases = {name: (a, n) for name, a, n in WINDOWS}
        phases.update(identifier=rr.UUID_WINDOW, known_stop=rr.TIMER_WINDOW)
        if self._code_phase in phases:
            allowed |= frozenset(cr.chunks(*phases[self._code_phase]))
        return allowed


async def collect(reader, base, candidate, symbols, session_id, prior):
    if not isinstance(reader, ResumeCodeReader):
        raise ValueError("separate fixed timer resume-code reader required")
    if reader._started or reader.closed:
        raise RuntimeError("timer resume-code session already used; no retry")
    reader._started = True
    try:
        rr.validate_references(base, candidate, symbols)
        validate_symbols(symbols)
        expected_stop = rr.validate_prior_capture(prior)
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config["windows"] if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != rr.DESCRIPTOR_SHA256:
            raise RuntimeError("unreviewed descriptor; no timer resume-code read")
        reader._code_phase = "identifier"
        for _ in range(2):
            if await reader.window(*rr.UUID_WINDOW) != rr.ROM_UUID:
                raise RuntimeError("application ROM identifier differs")
        reader._code_phase = "known_stop"
        for _ in range(2):
            if await reader.window(*rr.TIMER_WINDOW) != expected_stop:
                raise RuntimeError("known timer stop code differs; no new code read")
        windows = {}
        for name, address, length in WINDOWS:
            reader._code_phase = name
            first = await reader.window(address, length)
            repeated = await reader.window(address, length)
            reader._code_phase = None
            if first != repeated:
                raise RuntimeError("timer resume code changed across repeats: " + name)
            windows[name] = {"address": address, "data_hex": first.hex(),
                             "sha256": hashlib.sha256(first).hexdigest()}
        for address, length in cr.CONFIG_WINDOWS:
            expected = cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS else cr.EXPECTED_FLASH_CONFIG
            if await reader.window(address, length) != expected:
                raise RuntimeError("configuration changed")
        if await reader.read(*cr.IDLE_WINDOW) != b"\0":
            raise RuntimeError("raw mode changed")
        reader.emit({"kind": "rom_timer_resume_code", "new_bytes": TOTAL_NEW_BYTES,
                     "known_stop_repeated_equal": True, "repeated_equal": True,
                     "keys_read": False, "pointer_following": False, "target_execution": False})
        return {"schema": SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                "prerequisite_capture": config, "symbols_sha256": rr.SYMBOLS_SHA256,
                "app_rom_identifier": rr.ROM_UUID.hex(), "windows": windows,
                "known_stop_code_sha256": rr.TIMER_CODE_SHA256,
                "known_stop_repeated_equal": True, "repeated_equal": True,
                "keys_read": False, "pointer_following": False, "target_execution": False,
                "full_image_attestation": False, "recovery_verified": False, "flash_authorized": False}
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._code_phase = None
        reader._descriptor_phase = False
        reader.closed = True
