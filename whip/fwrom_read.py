"""Fixed ROM timer-code DATA read; never execute the target or follow pointers.

Uses the reviewed CD01 dispatcher, whose connection/timer bookkeeping is
stateful. Requires a newly coordinated idle session. This is not a generic ROM
dump, a safe-flash declaration, or permission to read OTP/peripherals/keys.
"""
from __future__ import annotations

import hashlib
import json

from whip import fwcapacity, fwcapacity_read as cr, fwidentity

SCHEMA = "whip.rom-timers.capture.v1"
ROM_UUID = bytes.fromhex("f94c6b7e11c5eb118282f74a0c0cef5b")
UUID_WINDOW = (fwidentity.FILE_TO_ADDRESS + 0x5C, 16)
# Byte addresses, NOT odd Thumb call targets. Ends before os_timer_dump.
TIMER_WINDOW = (0x136BC, 0x48)
SYMBOLS_SHA256 = "6f5a59f6444c01328808ac148b9c60771410196ab3b57e08fc8ff90525934247"
DESCRIPTOR_SHA256 = "d74c3afddf382c36dd4c566c539d2dcff16a22e0c7f525a9c1a342875cc4e12f"
EXPECTED_TRANSACTIONS = 114
PRIOR_CAPTURE_SHA256 = "4290a08b6703c6b3e2ddf262285a28100368253ccff6a46b9116d31df039f16d"
TIMER_CODE_SHA256 = "bf0174582ef92307490e0cdcf0802c912f6f36d8946aac5208f641ad81514e88"
# Separately selected follow-up. Literal locations and both call entry points
# come from the archived wrappers. The 172-byte cap is a capture boundary, NOT
# a claim that the complete implementations/callees lie inside this window.
LITERAL_WINDOW = (0x137F8, 8)
DEFAULT_WINDOW = (0x140CE, 172)
INTERNAL_WINDOWS = (("literals", LITERAL_WINDOW), ("defaults", DEFAULT_WINDOW))
INTERNAL_TRANSACTIONS = 142
INTERNAL_SCHEMA = "whip.rom-timer-internals.capture.v1"
INTERNAL_CAPTURE_SHA256 = "79fe567846b308a081d6820ce552b45fba107470f2258035d67e4cd2d1c88525"
# These two words are established by the captured LDR/literal/BLX chain as
# function-pointer slots in SRAM, not FIFO/MMIO/OTP or arbitrary returned data.
# Read only the fixed slots; never use their contents as a follow-up address.
HOOK_WINDOW = (0x201650, 8)
HOOK_TRANSACTIONS = 144
HOOK_SCHEMA = "whip.rom-timer-hooks.capture.v1"


def validate_internal_capture(raw: bytes):
    if hashlib.sha256(raw).hexdigest() != INTERNAL_CAPTURE_SHA256:
        raise ValueError("unreviewed prior timer-internals capture")
    data = json.loads(raw)["internal_windows"]
    if bytes.fromhex(data["literals"]["data_hex"]) != bytes.fromhex("5016200054162000"):
        raise ValueError("unreviewed hook slot addresses")
    return {phase: bytes.fromhex(data[phase]["data_hex"]) for phase, _ in INTERNAL_WINDOWS}


def validate_prior_capture(raw: bytes):
    if hashlib.sha256(raw).hexdigest() != PRIOR_CAPTURE_SHA256:
        raise ValueError("unreviewed prior ROM capture")
    capture = json.loads(raw)
    code = bytes.fromhex(capture["timer_code"]["data_hex"])
    if (capture["timer_code"]["address"] != TIMER_WINDOW[0]
            or len(code) != TIMER_WINDOW[1]
            or hashlib.sha256(code).hexdigest() != TIMER_CODE_SHA256):
        raise ValueError("unreviewed prior timer code")
    return code


def validate_references(base: bytes, candidate: bytes, symbols: bytes):
    """Run BEFORE connection; the symbols are a map, not executable ROM bytes."""
    fwidentity.validate_images(base, candidate)
    fwcapacity.audit_cd_image(base)
    fwcapacity.audit_cd_image(candidate)
    if base[0x5C:0x6C] != ROM_UUID or candidate[0x5C:0x6C] != ROM_UUID:
        raise ValueError("unreviewed ROM identifier")
    if hashlib.sha256(symbols).hexdigest() != SYMBOLS_SHA256:
        raise ValueError("unreviewed ROM symbol map")
    for line in (b"os_timer_stop = 0x000136bd ;", b"os_timer_delete = 0x000136e1 ;",
                 b"os_timer_dump = 0x00013705 ;"):
        if line not in symbols.splitlines():
            raise ValueError("timer symbol boundary mismatch")


class ROMTimerReader(cr.DescriptorReader):
    """One-use plan with separate, closed-by-default identifier/code phases."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rom_phase = None
        self._started = False
        self.closed = False

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        if self._rom_phase == "identifier":
            allowed |= frozenset(cr.chunks(*UUID_WINDOW))
        elif self._rom_phase == "timers":
            allowed |= frozenset(cr.chunks(*TIMER_WINDOW))
        return allowed


class ROMInternalsReader(ROMTimerReader):
    """Fixed follow-up only. No address derives from the returned literals."""
    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        for phase, window in INTERNAL_WINDOWS:
            if self._rom_phase == phase:
                allowed |= frozenset(cr.chunks(*window))
        return allowed


class ROMHookReader(ROMInternalsReader):
    """Separately reviewed fixed non-secret function-pointer slots, no calls."""
    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        if self._rom_phase == "hook_slots":
            allowed |= frozenset(cr.chunks(*HOOK_WINDOW))
        return allowed


def _window(address, data):
    return {"address": address, "data_hex": data.hex(),
            "sha256": hashlib.sha256(data).hexdigest()}


async def collect_rom_timers(reader: ROMTimerReader, base: bytes, candidate: bytes,
                             symbols: bytes, session_id: str):
    return await _collect(reader, base, candidate, symbols, session_id)


async def collect_rom_internals(reader: ROMInternalsReader, base: bytes, candidate: bytes,
                                symbols: bytes, session_id: str, prior_capture: bytes):
    if not isinstance(reader, ROMInternalsReader):
        raise ValueError("separate ROM internals reader required")
    return await _collect(reader, base, candidate, symbols, session_id, prior_capture)


async def collect_rom_hooks(reader: ROMHookReader, base: bytes, candidate: bytes, symbols: bytes,
                            session_id: str, prior_capture: bytes, prior_internals: bytes):
    if not isinstance(reader, ROMHookReader):
        raise ValueError("separate ROM hook reader required")
    return await _collect(reader, base, candidate, symbols, session_id, prior_capture, prior_internals)


async def _collect(reader, base, candidate, symbols, session_id, prior_capture=None, prior_internals=None):
    if not isinstance(reader, ROMTimerReader):
        raise ValueError("separate ROM timer reader required")
    if reader._started or reader.closed:
        raise RuntimeError("ROM diagnostic session already used; no retry")
    reader._started = True
    try:
        validate_references(base, candidate, symbols)
        if isinstance(reader, ROMInternalsReader) and prior_capture is None:
            raise ValueError("prior captured ROM wrappers required for internals plan")
        if isinstance(reader, ROMHookReader) and prior_internals is None:
            raise ValueError("prior captured internals required for hook plan")
        expected_code = validate_prior_capture(prior_capture) if prior_capture is not None else None
        expected_internals = validate_internal_capture(prior_internals) if prior_internals is not None else None
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config["windows"]
                          if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != DESCRIPTOR_SHA256:
            raise RuntimeError("bank0 differs from reviewed descriptor; no ROM read")
        reader._rom_phase = "identifier"
        for _ in range(2):
            if await reader.window(*UUID_WINDOW) != ROM_UUID:
                raise RuntimeError("application ROM identifier differs; no timer-code read")
        reader._rom_phase = "timers"
        first = await reader.window(*TIMER_WINDOW)
        second = await reader.window(*TIMER_WINDOW)
        reader._rom_phase = None
        if first != second:
            raise RuntimeError("ROM code differs across repeated reads")
        internals = {}
        if expected_code is not None:
            if first != expected_code:
                raise RuntimeError("ROM wrappers differ from prior capture; no internal read")
            for phase, window in INTERNAL_WINDOWS:
                reader._rom_phase = phase
                data = await reader.window(*window)
                repeated = await reader.window(*window)
                reader._rom_phase = None
                if data != repeated:
                    raise RuntimeError(f"ROM {phase} differ across repeated reads")
                internals[phase] = _window(window[0], data)
        hooks = None
        if expected_internals is not None:
            if {phase: bytes.fromhex(w["data_hex"]) for phase, w in internals.items()} != expected_internals:
                raise RuntimeError("ROM internals differ from prior capture; no hook-slot read")
            reader._rom_phase = "hook_slots"
            hooks = await reader.window(*HOOK_WINDOW)
            if await reader.window(*HOOK_WINDOW) != hooks:
                raise RuntimeError("timer hook slots changed across repeated reads")
            reader._rom_phase = None
        for address, length in cr.CONFIG_WINDOWS:
            expected = (cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS
                        else cr.EXPECTED_FLASH_CONFIG)
            if await reader.window(address, length) != expected:
                raise RuntimeError("configuration changed during ROM diagnostic")
        if await reader.read(*cr.IDLE_WINDOW) != b"\0":
            raise RuntimeError("raw mode changed during ROM diagnostic")
        reader.emit({"kind": "rom_timers", "address": TIMER_WINDOW[0],
                     "bytes": len(first), "repeated_equal": True,
                     "pointer_following": False, "target_execution": False})
        result = {"schema": SCHEMA, "evidence_kind": "device_capture",
                "session_id": session_id, "prerequisite_capture": config,
                "app_rom_identifier": _window(UUID_WINDOW[0], ROM_UUID),
                "timer_code": _window(TIMER_WINDOW[0], first),
                "repeated_equal": True, "symbols_sha256": SYMBOLS_SHA256,
                "full_image_attestation": False, "callback_drain_verified": False,
                "recovery_verified": False, "flash_authorized": False}
        if internals:
            result.update(schema=INTERNAL_SCHEMA, internal_windows=internals,
                          prior_capture_sha256=PRIOR_CAPTURE_SHA256,
                          pointer_following=False, target_execution=False,
                          actual_hook_state_read=False, complete_implementations_verified=False)
            reader.emit({"kind": "rom_timer_internals", "bytes": 180,
                         "repeated_equal": True, "pointer_following": False,
                         "target_execution": False})
        if hooks is not None:
            result.update(schema=HOOK_SCHEMA, hook_slots=_window(HOOK_WINDOW[0], hooks),
                          prior_internals_sha256=INTERNAL_CAPTURE_SHA256, actual_hook_state_read=True)
            reader.emit({"kind": "rom_timer_hooks", "bytes": 8, "repeated_equal": True,
                         "pointer_following": False, "target_execution": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._rom_phase = None
        reader._descriptor_phase = False
        reader.closed = True
