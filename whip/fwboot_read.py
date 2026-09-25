"""Fixed secure-boot reference comparison, DATA reads only; never install/call it.

The 52-byte prefix ends before the header's dec_key field at +0x34. No key,
authentication block, OTP, peripheral or arbitrary returned pointer is read.
CD01 has the previously audited connection/timer bookkeeping side effects.
"""
from __future__ import annotations

import hashlib
import json

from whip import fwcapacity, fwcapacity_read as cr, fwrom_read as rr

REFERENCE_SHA256 = "2fe73838cc94264ac43ea5c5cef99290e0a3d1ac266b266cd047230826e0ecb8"
BODY_SHA256 = "17a7115e12cc472b5e745802be29df8b0b0917cfc3eaa4ee99d2f4134c59cf04"
HEADER_WINDOW = (0x80D000, 52)
BODY_WINDOW = (0x80D400, 528)
EXPECTED_TRANSACTIONS = 182
SCHEMA = "whip.boot-reference.capture.v1"


def validate_reference(raw: bytes):
    if hashlib.sha256(raw).hexdigest() != REFERENCE_SHA256:
        raise ValueError("unreviewed external boot reference")
    ref = json.loads(raw)
    header, body = (bytes.fromhex(ref[k]) for k in ("nonsecret_header_hex", "body_hex"))
    if (len(header) != 52 or len(body) != 528 or header[12:28] != rr.ROM_UUID
            or int.from_bytes(header[4:6], "little") != 0x2791
            or int.from_bytes(header[8:12], "little") != 528
            or hashlib.sha256(body).hexdigest() != BODY_SHA256):
        raise ValueError("invalid fixed secure-boot reference")
    return header, body


class BootReferenceReader(cr.DescriptorReader):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._started = False
        self.closed = False
        self._boot_phase = None

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        window = {"header": HEADER_WINDOW, "body": BODY_WINDOW}.get(self._boot_phase)
        return allowed | frozenset(cr.chunks(*window)) if window else allowed


def _window(address, data):
    return {"address": address, "data_hex": data.hex(), "sha256": hashlib.sha256(data).hexdigest()}


async def collect_boot_reference(reader, base, candidate, symbols, session_id, reference):
    if not isinstance(reader, BootReferenceReader):
        raise ValueError("separate fixed boot reader required")
    if reader._started or reader.closed:
        raise RuntimeError("boot diagnostic session already used; no retry")
    reader._started = True
    try:
        rr.validate_references(base, candidate, symbols)
        expected_header, expected_body = validate_reference(reference)
        config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
        descriptor = next(w for w in config["windows"] if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
        if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != rr.DESCRIPTOR_SHA256:
            raise RuntimeError("unreviewed descriptor; no boot read")
        reader._boot_phase = "header"
        header = await reader.window(*HEADER_WINDOW)
        repeated = await reader.window(*HEADER_WINDOW)
        reader._boot_phase = None
        if header != repeated or header != expected_header:
            raise RuntimeError("boot prefix differs from reviewed reference; no body read")
        reader._boot_phase = "body"
        body = await reader.window(*BODY_WINDOW)
        repeated = await reader.window(*BODY_WINDOW)
        reader._boot_phase = None
        if body != repeated:
            raise RuntimeError("boot code changed across repeated reads")
        for address, length in cr.CONFIG_WINDOWS:
            expected = cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS else cr.EXPECTED_FLASH_CONFIG
            if await reader.window(address, length) != expected:
                raise RuntimeError("configuration changed during boot diagnostic")
        if await reader.read(*cr.IDLE_WINDOW) != b"\0":
            raise RuntimeError("raw mode changed during boot diagnostic")
        reader.emit({"kind": "boot_reference", "header_bytes": 52, "body_bytes": 528,
                     "body_matches_reference": body == expected_body, "repeated_equal": True,
                     "keys_read": False, "pointer_following": False, "target_execution": False})
        return {"schema": SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                "prerequisite_capture": config, "reference_sha256": REFERENCE_SHA256,
                "header": _window(HEADER_WINDOW[0], header), "body": _window(BODY_WINDOW[0], body),
                "repeated_equal": True, "body_matches_reference": body == expected_body,
                "full_image_attestation": False, "keys_read": False, "pointer_following": False,
                "target_execution": False, "recovery_verified": False, "flash_authorized": False}
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._boot_phase = None
        reader._descriptor_phase = False
        reader.closed = True
