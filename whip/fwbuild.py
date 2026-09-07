"""
Build custom OTA images for the RT02CR container.

An image only boots if three derived fields agree with its contents. Change one
byte of code and all three go stale, and the ring will either reject the
transfer or accept it and fail to run the new firmware.

    0x000c  u32 LE   sum of every byte from 0x50 to EOF
    0x0052  u16 LE   Realtek control flags; bit 7 is `not_ready`
    0x01c4  32 bytes SHA-256 of the payload at 0x450 to EOF

All three are verified against the published low-latency image, which satisfies
every one. The stock vendor image satisfies the first but not the third: it
ships with `not_ready` set and a SHA that is not a hash of its payload, because
the installer is expected to fill that in. That is precisely why a custom image
has to refresh the SHA and clear the bit -- an image with a stale SHA transfers
but does not boot as the new firmware.

Layout, from the research notes in Nosh118/colmi-ring-tools:

    0x0000  QRing OTA wrapper, magic e5c3bd81
    0x0010  firmware version string
    0x0030  hardware version string
    0x0050  nested Realtek image header
    0x0058  u32 payload length (filesize - 0x450)
    0x0450  Realtek application payload
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

BODY_SUM_OFFSET = 0x0C
FLAGS_OFFSET = 0x52
SHA256_OFFSET = 0x1C4
PAYLOAD_LENGTH_OFFSET = 0x58

BODY_START = 0x50
PAYLOAD_START = 0x450

NOT_READY_BIT = 0x0080

SHA256_LEN = 32


@dataclass(frozen=True)
class ContainerFields:
    body_sum: int
    flags: int
    sha256: str
    payload_length: int

    @property
    def not_ready(self) -> bool:
        return bool(self.flags & NOT_READY_BIT)


def read_fields(data: bytes) -> ContainerFields:
    return ContainerFields(
        body_sum=int.from_bytes(data[BODY_SUM_OFFSET : BODY_SUM_OFFSET + 4], "little"),
        flags=int.from_bytes(data[FLAGS_OFFSET : FLAGS_OFFSET + 2], "little"),
        sha256=data[SHA256_OFFSET : SHA256_OFFSET + SHA256_LEN].hex(),
        payload_length=int.from_bytes(data[PAYLOAD_LENGTH_OFFSET : PAYLOAD_LENGTH_OFFSET + 4], "little"),
    )


def expected_fields(data: bytes) -> ContainerFields:
    """What the three derived fields should be for this image's contents."""
    return ContainerFields(
        body_sum=sum(data[BODY_START:]) & 0xFFFFFFFF,
        flags=int.from_bytes(data[FLAGS_OFFSET : FLAGS_OFFSET + 2], "little") & ~NOT_READY_BIT,
        sha256=hashlib.sha256(data[PAYLOAD_START:]).hexdigest(),
        payload_length=len(data) - PAYLOAD_START,
    )


def verify(data: bytes) -> list[str]:
    """Return a list of problems. Empty means the image is internally consistent."""
    actual, expected = read_fields(data), expected_fields(data)
    problems = []

    if actual.sha256 != expected.sha256:
        problems.append(f"payload SHA-256 stale: stored {actual.sha256[:16]}..., expected {expected.sha256[:16]}...")
    if actual.not_ready:
        problems.append(f"not_ready bit is set in flags {actual.flags:#06x}; the image will not boot")
    if actual.body_sum != expected.body_sum:
        problems.append(f"body sum stale: stored {actual.body_sum:#010x}, expected {expected.body_sum:#010x}")
    if actual.payload_length != expected.payload_length:
        problems.append(
            f"payload length {actual.payload_length} does not match file size minus {PAYLOAD_START:#x}"
        )
    return problems


def refresh(data: bytes) -> bytes:
    """
    Recompute every derived field so the image matches its own contents.

    Order matters: the SHA and the flags both live inside the region the body sum
    covers, so the sum has to be computed last.
    """
    out = bytearray(data)

    out[SHA256_OFFSET : SHA256_OFFSET + SHA256_LEN] = hashlib.sha256(bytes(out[PAYLOAD_START:])).digest()

    flags = int.from_bytes(out[FLAGS_OFFSET : FLAGS_OFFSET + 2], "little") & ~NOT_READY_BIT
    out[FLAGS_OFFSET : FLAGS_OFFSET + 2] = flags.to_bytes(2, "little")

    out[BODY_SUM_OFFSET : BODY_SUM_OFFSET + 4] = (sum(out[BODY_START:]) & 0xFFFFFFFF).to_bytes(4, "little")
    return bytes(out)


def patch(data: bytes, edits: dict[int, int]) -> bytes:
    """
    Apply byte edits at file offsets, then refresh the derived fields.

    Every edit must land in the payload. An edit inside the header would be
    silently undone by the refresh, or would corrupt a field we depend on.
    """
    out = bytearray(data)
    for offset, value in edits.items():
        if not PAYLOAD_START <= offset < len(out):
            raise ValueError(f"edit at {offset:#x} is outside the payload ({PAYLOAD_START:#x}..{len(out):#x})")
        if not 0 <= value <= 0xFF:
            raise ValueError(f"edit value {value} at {offset:#x} is not a byte")
        out[offset] = value
    return refresh(bytes(out))
