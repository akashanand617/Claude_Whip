"""Read-only, critical-site fingerprint for the reviewed 25 Hz images.

Both images report the same DIS firmware version. These fixed reads compare
their patch sites and nearby instructions, including the v2 disconnect hook
and timer cleanup, plus the raw period, accelerometer range and protected DFU
timer. The earlier optical-off candidate (SHA-256 f862e5bb...3f27) is unknown
under this fingerprint: it lacks the disconnect cleanup. A match identifies
these sampled bytes only; it is NOT full-image attestation or evidence of
correct hardware behavior.

The CD01 reply contains data but no address, length or request identifier.
The caller MUST send one request at a time, reject unexpected queued replies,
and abort the entire read sequence on timeout or an invalid reply. Never retry
on that connection: a late reply could be mistaken for the next address.
This module constructs packets only; it never connects, writes memory or flashes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib

from whip import fwbuild, fwoptical, fwoptical_unified, protocol


# Application file offset 0x450 is loaded at 0x826400. Code reads use byte
# addresses, not Thumb branch pointers (do not set bit zero).
APP_ADDRESS = 0x826400
FILE_TO_ADDRESS = APP_ADDRESS - fwbuild.PAYLOAD_START  # 0x825fb0
MAX_READ_LENGTH = 14
CANDIDATE_SHA256 = "0d18a0fa860d58ab8f984b5f542f45dac105241f47bf1c2af41321eb0431e14c"
UNIFIED_CANDIDATE_SHA256 = "7e2b3e2e61906031f5b79262ca39022fc34518ab421f814a586f9e49f8691243"

ORIGINAL_25HZ = "original25Hz"
OPTICAL_OFF_CANDIDATE = "optical_off_candidate"
UNIFIED_CANDIDATE = "unified_candidate"
MIXED_OR_UNKNOWN = "mixed_or_unknown"


@dataclass(frozen=True)
class ReadSite:
    name: str
    file_offset: int
    length: int

    def __post_init__(self):
        if type(self.length) is not int or not 1 <= self.length <= MAX_READ_LENGTH:
            raise ValueError("code reads require 1..14 bytes")
        if (type(self.file_offset) is not int
                or not fwbuild.PAYLOAD_START <= self.file_offset
                or self.file_offset + self.length > fwoptical.BASE_SIZE):
            raise ValueError("code read must lie inside the archived application payload")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("code read requires a name")

    @property
    def address(self) -> int:
        return self.file_offset + FILE_TO_ADDRESS


# Half-open ranges contain complete reviewed patches and neighboring code.
# The DFU range is read only; it must never be patched. Do not expose arbitrary
# user-supplied addresses or lengths through a CLI using this helper.
_CODE_RANGES = (
    ("raw_start", 0x21D6, 20),
    ("raw_period", 0x2244, 16),
    ("disconnect_hook", 0x6918, 24),
    # UART, DFU, DIS, FEE7 and HID setup. The revoked first unified image
    # changed UART's call instead of FEE7's; omitting this range made the
    # supposedly critical fingerprint unable to detect that exact failure.
    ("ble_service_setup", 0x7498, 44),
    ("dfu_timer", 0x7ED0, 20),
    ("accel_range", 0xBF04, 16),
    ("idle_request", 0xCAD0, 20),
    ("optical_enable_idle_guard", 0xF68A, 80),
    ("optical_control", 0x122FE, 48),
)
_READ_SITES = tuple(
    ReadSite(f"{name}_{relative:02x}", offset + relative,
             min(MAX_READ_LENGTH, length - relative))
    for name, offset, length in _CODE_RANGES
    for relative in range(0, length, MAX_READ_LENGTH)
)


def read_sites() -> tuple[ReadSite, ...]:
    """Return the fixed, ordered application-code reads (26 requests, 288 bytes)."""
    return _READ_SITES


def _require_site(site: ReadSite) -> None:
    if type(site) is not ReadSite or site not in _READ_SITES:
        raise ValueError("read site is not in the fixed critical-site fingerprint")


def read_packet(site: ReadSite) -> bytes:
    """Build a CD01 memory READ for one fixed code chunk, never a CD02 write."""
    _require_site(site)
    return bytes(protocol.make_packet(
        0xCD, bytes([0x01, site.length]) + site.address.to_bytes(4, "big"),
    ))


def decode_reply(site: ReadSite, packet: bytes | bytearray) -> bytes:
    """Validate a CD reply and return only the requested data bytes.

    This checks framing and checksum, not address correlation: the protocol
    has no such field. Only the serialized, fail-on-timeout caller can maintain
    the association with ``site``. Unrequested padding is not fingerprint data.
    """
    _require_site(site)
    if not isinstance(packet, (bytes, bytearray)) or len(packet) != protocol.PACKET_SIZE:
        raise ValueError("CD reply must be a 16-byte packet; abort diagnostics")
    if packet[0] != 0xCD:
        raise ValueError("unexpected command in CD reply; abort diagnostics")
    if protocol.checksum(packet[:-1]) != packet[-1]:
        raise ValueError("invalid CD reply checksum; abort diagnostics")
    return bytes(packet[1:1 + site.length])


def validate_images(base: bytes, candidate: bytes | None = None,
                    unified_candidate: bytes | None = None) -> bytes:
    """Validate the pinned base and rebuild both exact reviewed candidates.

    If a candidate archive is supplied, require byte-for-byte equality with the
    strict builder's output. Call this before connecting when preparing a probe.
    """
    built = fwoptical.build(base)
    if hashlib.sha256(built).hexdigest() != CANDIDATE_SHA256:
        raise ValueError("builder output is not the pinned optical-off candidate")
    if candidate is not None and candidate != built:
        raise ValueError("candidate archive differs from the strict optical-off build")
    unified = fwoptical_unified.build(base)
    if hashlib.sha256(unified).hexdigest() != UNIFIED_CANDIDATE_SHA256:
        raise ValueError("builder output is not the pinned unified candidate")
    if unified_candidate is not None and unified_candidate != unified:
        raise ValueError("unified archive differs from the strict unified build")
    return built


def classify(base: bytes, samples_by_name: Mapping[str, bytes]) -> str:
    """Classify complete, decoded reads against locally validated references.

    A partial, mixed, malformed or unfamiliar sample set is always unknown.
    A recognized result means every sampled byte matched, not that the complete
    installed image was read or that the emitters stay dark on hardware.
    """
    candidate = validate_images(base)
    unified = fwoptical_unified.build(base)
    if set(samples_by_name) != {site.name for site in _READ_SITES}:
        return MIXED_OR_UNKNOWN
    for site in _READ_SITES:
        sample = samples_by_name[site.name]
        if not isinstance(sample, (bytes, bytearray)) or len(sample) != site.length:
            return MIXED_OR_UNKNOWN
    for label, reference in ((ORIGINAL_25HZ, base),
                             (OPTICAL_OFF_CANDIDATE, candidate),
                             (UNIFIED_CANDIDATE, unified)):
        if all(samples_by_name[site.name] == reference[site.file_offset:site.file_offset + site.length]
               for site in _READ_SITES):
            return label
    return MIXED_OR_UNKNOWN
