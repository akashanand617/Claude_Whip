"""Bounded diagnostic DATA reads. CD's dispatch bookkeeping is not read-only.

No scanning/connection, flash, sensor start/stop, setting or memory-write API.
Only pinned 25 Hz/V2 code, one known idle byte, and two non-secret configuration
windows may be requested. The separate descriptor plan admits one fixed bank0
header window only after matching the prior V2 configuration. Returned pointers
never become follow-up requests.
The caller must arrange an idle, exclusive connection and review the transcript.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time

from whip import fwcapacity, fwidentity, protocol

# Supplement the existing 22-site fingerprint with the actual diagnostic path.
# These windows are inside the known application, not arbitrary caller inputs.
CODE_WINDOWS = (("cd_dispatch", 0x564A, 20), ("cd_gate", 0x59D8, 14),
                ("cd_handler", 0x4B16, 0x86), ("cd_prelude", 0x7EEE, 50),
                ("cd_timer", 0x7ECA, 36), ("cd_timer_pointer", 0x8130, 4),
                ("cd_state_getter", 0x94CC, 6), ("cd_policy_pointers", 0x9568, 20),
                ("cd_policy_helper", 0x9270, 0xA0))
CONFIG_WINDOWS = ((fwcapacity.RAM_CONFIG_ADDRESS, 16),
                  (fwcapacity.FLASH_CONFIG_ADDRESS, 48))
IDLE_WINDOW = (0x209CAC, 1)
# Non-secret words captured twice in capacity-20260923-idle-config. These exact
# values constrain the new read; an unfamiliar layout is not followed.
EXPECTED_RAM_CONFIG = bytes.fromhex("007c2000007000000074000070380000")
EXPECTED_FLASH_CONFIG = bytes.fromhex(
    "002080000080040000a084000000000000a084000040000000e0840000400200"
    "00000001000080000000000000000000")
BANK0_DESCRIPTOR_WINDOW = (0x802198, 80)


def chunks(address, length):
    return tuple((address + offset, min(14, length - offset))
                 for offset in range(0, length, 14))


def allowed_reads():
    allowed = {(s.address, s.length) for s in fwidentity.read_sites()}
    for _, offset, length in CODE_WINDOWS:
        allowed.update(chunks(fwidentity.FILE_TO_ADDRESS + offset, length))
    for address, length in CONFIG_WINDOWS:
        allowed.update(chunks(address, length))
    allowed.add(IDLE_WINDOW)
    return frozenset(allowed)


class CapacityReader:
    """One request at a time; timeout/malformed/unsolicited reply poisons session.

    CD replies have no request identifier. This cannot make the legacy protocol
    cryptographically correlated; no retries or automatic reconnection allowed.
    """
    def __init__(self, client, emit, *, timeout=3.0, spacing=0.1):
        if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(spacing) or spacing < 0:
            raise ValueError("invalid diagnostic timing")
        self.client, self.emit = client, emit
        self.timeout, self.spacing = timeout, spacing
        self.pending = None
        self.poisoned = False

    def _allowed_reads(self):
        return allowed_reads()

    def notify(self, _sender, raw):
        packet = bytes(raw)
        # Every unrelated packet remains terminal, including valid 0x73 status.
        # Log only redacted metadata, never health values or raw payload.
        if not packet or packet[0] != 0xCD:
            self.poisoned = True
            self.emit({"kind": "unexpected_notification", **protocol.notification_metadata(packet),
                       "monotonic": time.monotonic()})
            if self.pending is not None and not self.pending.done():
                self.pending.set_exception(RuntimeError("non-diagnostic traffic; abort idle read"))
            return
        if self.pending is None or self.pending.done():
            self.poisoned = True
            return
        if len(packet) != 16 or protocol.checksum(packet[:-1]) != packet[-1]:
            self.poisoned = True
            self.pending.set_exception(RuntimeError("invalid diagnostic reply"))
            return
        self.pending.set_result(packet)

    async def read(self, address, length):
        if (type(address) is not int or type(length) is not int or
                (address, length) not in self._allowed_reads()):
            raise ValueError("request outside fixed configuration/code read plan")
        if self.poisoned or self.pending is not None:
            self.poisoned = True
            raise RuntimeError("diagnostic session ambiguous or busy; no further requests")
        packet = bytes(protocol.make_packet(0xCD, bytes([1, length]) + address.to_bytes(4, "big")))
        self.pending = asyncio.get_running_loop().create_future()
        self.emit({"kind": "request", "address": address, "length": length,
                   "packet": packet.hex(), "monotonic": time.monotonic()})
        try:
            # A stalled transport write is just as ambiguous as a lost reply.
            # Bound both in one deadline, without retrying either operation.
            async with asyncio.timeout(self.timeout):
                await self.client.write_gatt_char(protocol.UART_RX_CHAR_UUID, packet, response=False)
                response = await self.pending
            await asyncio.sleep(self.spacing)
            if self.poisoned:
                raise RuntimeError("unsolicited/duplicate traffic after diagnostic reply")
            self.emit({"kind": "reply", "address": address, "length": length,
                       "packet": response.hex(), "monotonic": time.monotonic()})
            return response[1:1 + length]
        except BaseException:
            self.poisoned = True
            if self.pending is not None and not self.pending.done():
                self.pending.cancel()
            raise
        finally:
            self.pending = None

    async def window(self, address, length):
        return b"".join([await self.read(a, n) for a, n in chunks(address, length)])


class DescriptorReader(CapacityReader):
    """Separate fixed plan. No descriptor reads before identity/config match."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._descriptor_phase = False

    def _allowed_reads(self):
        allowed = super()._allowed_reads()
        if self._descriptor_phase:
            allowed = allowed | frozenset(chunks(*BANK0_DESCRIPTOR_WINDOW))
        return allowed


async def collect_configuration(reader: CapacityReader, base: bytes, candidate: bytes, session_id: str):
    """Fingerprint, require idle, read/repeat exactly64 config bytes; no banks.

    Local references and all extra code windows are checked before configuration
    requests. A critical-site match is NOT a full on-device image hash.
    """
    fwidentity.validate_images(base, candidate)
    fwcapacity.audit_cd_image(base)
    fwcapacity.audit_cd_image(candidate)
    samples = {site.name: await reader.read(site.address, site.length)
               for site in fwidentity.read_sites()}
    classification = fwidentity.classify(base, samples)
    if classification == fwidentity.MIXED_OR_UNKNOWN:
        raise RuntimeError("critical-site identity mismatch; no configuration read")
    reference = candidate if classification == fwidentity.OPTICAL_OFF_CANDIDATE else base
    for name, offset, length in CODE_WINDOWS:
        observed = await reader.window(offset + fwidentity.FILE_TO_ADDRESS, length)
        if observed != reference[offset:offset + length]:
            raise RuntimeError(f"diagnostic path mismatch: {name}; no configuration read")
    if await reader.read(*IDLE_WINDOW) != b"\0":
        raise RuntimeError("raw mode is active; abort without sending stop commands")
    windows = []
    for address, length in CONFIG_WINDOWS:
        first = await reader.window(address, length)
        second = await reader.window(address, length)
        if first != second:
            raise RuntimeError("configuration changed across repeated reads")
        windows.append({"address": address, "data_hex": first.hex(),
                        "sha256": hashlib.sha256(first).hexdigest()})
    if await reader.read(*IDLE_WINDOW) != b"\0":
        raise RuntimeError("raw mode changed during diagnostic session")
    reader.emit({"kind": "identity", "classification": classification,
                 "scope": "critical sites and diagnostic code only; NOT full image attestation"})
    return {"schema": fwcapacity.SCHEMA, "evidence_kind": "device_capture",
            "session_id": session_id, "image_sha256": hashlib.sha256(reference).hexdigest(),
            "windows": windows}


async def collect_bank0_descriptor(reader: DescriptorReader, base: bytes, candidate: bytes,
                                  session_id: str):
    """Exactly one new fixed 80-byte data window, twice. Never follow pointers.

    Fresh V2/diagnostic fingerprint, idle flag and exact repeated prior config
    must match first. Config/idle are checked again after the descriptor. A bad
    descriptor format is preserved for offline interpretation, not followed.
    """
    if not isinstance(reader, DescriptorReader):
        raise ValueError("descriptor collection requires the separately selected fixed plan")
    if reader._descriptor_phase:
        raise RuntimeError("descriptor phase already active")
    try:
        captured = await collect_configuration(reader, base, candidate, session_id)
        if captured["image_sha256"] != fwcapacity.V2_SHA256:
            raise RuntimeError("descriptor plan requires the prior V2 fingerprint")
        expected = {fwcapacity.RAM_CONFIG_ADDRESS: EXPECTED_RAM_CONFIG,
                    fwcapacity.FLASH_CONFIG_ADDRESS: EXPECTED_FLASH_CONFIG}
        observed = {w["address"]: bytes.fromhex(w["data_hex"]) for w in captured["windows"]}
        if observed != expected:
            raise RuntimeError("configuration differs from prior reviewed capture; no descriptor read")
        # Structural parser remains fail-closed, including quarantine of the
        # known startup-written backup1 declaration (not a read target).
        fwcapacity.analyze_capture(captured, vendor_file_size=138016)
        reader._descriptor_phase = True
        first = await reader.window(*BANK0_DESCRIPTOR_WINDOW)
        second = await reader.window(*BANK0_DESCRIPTOR_WINDOW)
        reader._descriptor_phase = False
        if first != second:
            raise RuntimeError("bank0 descriptor changed across repeated reads")
        for address, length in CONFIG_WINDOWS:
            if await reader.window(address, length) != expected[address]:
                raise RuntimeError("configuration changed during descriptor read")
        if await reader.read(*IDLE_WINDOW) != b"\0":
            raise RuntimeError("raw mode changed during descriptor read")
        captured["windows"].append({"address": BANK0_DESCRIPTOR_WINDOW[0],
                                    "data_hex": first.hex(),
                                    "sha256": hashlib.sha256(first).hexdigest()})
        reader.emit({"kind": "descriptor", "address": BANK0_DESCRIPTOR_WINDOW[0],
                     "bytes": len(first), "repeated_equal": True, "pointer_following": False})
        return captured
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._descriptor_phase = False
