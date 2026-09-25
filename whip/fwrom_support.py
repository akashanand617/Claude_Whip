"""Prepared fixed support-code/config DATA read; no target execution or flash.

New exclusive-idle coordination is mandatory. CD01 has bookkeeping effects.
Returned literals/hook values are data only and NEVER become request addresses.
"""
import hashlib
import json

from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr, fwrom_resume as tr

RESUME_SHA256 = "b09002f65a8b1ff4dbe1ba0aea54c79e2043a4f0ebd0683921229a731ae74064"
INTEGRATION_SHA256 = "d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b"
SCHEMA = "whip.rom-support.capture.v1"

# The helper is a fixed 512-byte CAP beginning at a captured direct BL target,
# not a claimed function length. Context/literal bounds come from captured BL
# and PC-relative LDR instructions. All ROM values remain uninterpreted data.
ROM_WINDOWS = (
    ("arithmetic_helper_cap", 0x3F97A, 512),
    ("timer_context_and_literals", 0x14238, 28),
    ("flash_layout_literals", 0x8420, 40),
    ("ota_header_literals", 0x8CBC, 36),
)
# Derived independently from the ALREADY captured create default and wrapper
# literals: +0x19 from 0x200364, +0x20 from 0x200464, and three fixed hook slots.
# No new ROM literal, pointer or live value controls these addresses or lengths.
STATE_WINDOWS = (
    ("timer_inhibit_snapshot", 0x20037D, 1),
    ("timer_rate_config_snapshot", 0x200484, 4),
    ("create_start_restart_hook_snapshot", 0x201644, 12),
)
WINDOWS = ROM_WINDOWS + STATE_WINDOWS
CALLER_WITNESSES = (
    ("flash_first_ldr", 0x8062, 4),
    ("flash_last_ldr", 0x815E, 2),
    ("ota_first_ldr", 0x8AA8, 2),
    ("ota_last_ldr", 0x8C66, 2),
)
KNOWN_WINDOWS = (("known_stop", *rr.TIMER_WINDOW),) + tr.WINDOWS + CALLER_WITNESSES
TOTAL_ROM_BYTES = sum(n for _, _, n in ROM_WINDOWS)
TOTAL_STATE_BYTES = sum(n for _, _, n in STATE_WINDOWS)
TOTAL_KNOWN_BYTES = sum(n for _, _, n in KNOWN_WINDOWS)
EXPECTED_TRANSACTIONS = (91 + 4 + 7 +
    2 * sum(len(cr.chunks(a, n)) for _, a, n in KNOWN_WINDOWS + WINDOWS))


def validate_archives(prior_stop, prior_resume, prior_integration):
    known = {"known_stop": rr.validate_prior_capture(prior_stop)}
    for raw, expected in ((prior_resume, RESUME_SHA256), (prior_integration, INTEGRATION_SHA256)):
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("unreviewed prior support-code archive")
    resume, integration = json.loads(prior_resume), json.loads(prior_integration)
    for name, address, length in tr.WINDOWS:
        window = resume["windows"][name]
        data = bytes.fromhex(window["data_hex"])
        if (window["address"] != address or len(data) != length or
                hashlib.sha256(data).hexdigest() != window["sha256"]):
            raise ValueError("invalid prior timer window")
        known[name] = data
    for name, address, length in CALLER_WITNESSES:
        matches = []
        for w in integration["windows"].values():
            data = bytes.fromhex(w["data_hex"])
            offset = address - w["address"]
            if 0 <= offset and offset + length <= len(data):
                matches.append(data[offset:offset + length])
        if len(matches) != 1:
            raise ValueError("support caller witness is not uniquely captured")
        known[name] = matches[0]
    return known


class SupportReader(cr.DescriptorReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = self._started = False
        self._support_phase = None

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        phases = {name: (a, n) for name, a, n in KNOWN_WINDOWS + WINDOWS}
        phases["identifier"] = rr.UUID_WINDOW
        if self._support_phase in phases:
            allowed |= frozenset(cr.chunks(*phases[self._support_phase]))
        return allowed


async def collect(reader, base, candidate, symbols, session_id,
                  prior_stop, prior_resume, prior_integration):
    if not isinstance(reader, SupportReader):
        raise ValueError("separate fixed support-code reader required")
    if reader._started or reader.closed:
        raise RuntimeError("support-code session already used; no retry")
    reader._started = True
    try:
        rr.validate_references(base, candidate, symbols)
        tr.validate_symbols(symbols)
        known = validate_archives(prior_stop, prior_resume, prior_integration)
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config["windows"] if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != rr.DESCRIPTOR_SHA256:
            raise RuntimeError("unreviewed descriptor; no support-code read")
        reader._support_phase = "identifier"
        for _ in range(2):
            if await reader.window(*rr.UUID_WINDOW) != rr.ROM_UUID:
                raise RuntimeError("application ROM identifier differs")
        # ALL known-code comparisons, including their second reads, precede ANY
        # new ROM/state access. A mismatch never widens this diagnostic plan.
        for name, address, length in KNOWN_WINDOWS:
            reader._support_phase = name
            for _ in range(2):
                if await reader.window(address, length) != known[name]:
                    raise RuntimeError("known support prerequisite differs: " + name)
        windows = {}
        for name, address, length in WINDOWS:
            reader._support_phase = name
            first = await reader.window(address, length)
            repeated = await reader.window(address, length)
            reader._support_phase = None
            if first != repeated:
                raise RuntimeError("support code/state changed across repeats: " + name)
            windows[name] = {"address": address, "data_hex": first.hex(),
                             "sha256": hashlib.sha256(first).hexdigest()}
        for address, length in cr.CONFIG_WINDOWS:
            expected = cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS else cr.EXPECTED_FLASH_CONFIG
            if await reader.window(address, length) != expected:
                raise RuntimeError("configuration changed")
        if await reader.read(*cr.IDLE_WINDOW) != b"\0":
            raise RuntimeError("raw mode changed")
        reader.emit({"kind": "rom_support", "new_rom_bytes": TOTAL_ROM_BYTES,
                     "state_snapshot_bytes": TOTAL_STATE_BYTES, "repeated_equal": True,
                     "keys_read": False, "pointer_following": False, "target_execution": False})
        return {"schema": SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                "prerequisite_capture": config, "symbols_sha256": rr.SYMBOLS_SHA256,
                "prior_resume_sha256": RESUME_SHA256, "prior_integration_sha256": INTEGRATION_SHA256,
                "app_rom_identifier": rr.ROM_UUID.hex(), "windows": windows,
                "known_code_repeated_equal": True, "repeated_equal": True,
                "keys_read": False, "pointer_following": False, "target_execution": False,
                "timer_state_immutable": False, "physical_timing_verified": False,
                "full_image_attestation": False, "recovery_verified": False, "flash_authorized": False}
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._support_phase = None
        reader._descriptor_phase = False
        reader.closed = True
