"""Offline validation and reconstruction for the RT12COL application image.

RT12COL uses the same QRing/Realtek application container as RT02CR, but its
sensor board is not interchangeable.  This module deliberately has no BLE or
flash-writing code.  It turns a verified read of the installed application
partition into a rollback OTA container and provides strict primitives for
later, source-specific patching.

The application partition stores the nested Realtek header at 0x826000 and the
application payload at 0x826400.  The 0x50-byte QRing wrapper is transport
metadata and is reconstructed locally.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from whip import fwbuild


HARDWARE = "RT12COL_V1.0"
STOCK_VERSION = "RT12COL_1.00.00_260520"

APP_PARTITION_ADDRESS = 0x826000
APP_PARTITION_SIZE = 0x24000
NESTED_HEADER_SIZE = 0x400
APP_PAYLOAD_ADDRESS = APP_PARTITION_ADDRESS + NESTED_HEADER_SIZE

OUTER_HEADER_SIZE = 0x50
QRING_MAGIC = bytes.fromhex("e5c3bd81")
REALTEK_IMAGE_UUID = bytes.fromhex("f94c6b7e11c5eb118282f74a0c0cef5b")

# The RT12COL build is shifted by 0x20 at the notification/DFU queue relative
# to the pinned RT02CR low-latency image.  This is the stock DFU reassembly
# retry timer, not the A1 raw producer.  Treat it as an immutable recovery site.
DFU_REASSEMBLY_TIMER_OFFSET = 0x7EF4
DFU_REASSEMBLY_TIMER_SIZE = 2

# Offsets relative to the nested Realtek header (file offset 0x50).
NESTED_FLAGS_OFFSET = 0x02
NESTED_PAYLOAD_LENGTH_OFFSET = 0x08
NESTED_UUID_OFFSET = 0x0C
NESTED_PAYLOAD_SHA_OFFSET = 0x174


@dataclass(frozen=True)
class PartitionImage:
    body: bytes
    payload: bytes
    payload_length: int
    flags: int
    payload_sha256: str
    stored_payload_sha256: str
    payload_sha_matches: bool


def _ascii_field(value: str) -> bytes:
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("firmware identity must be ASCII") from exc
    if not encoded or len(encoded) >= 0x20:
        raise ValueError("firmware identity must occupy 1..31 bytes")
    return encoded + bytes(0x20 - len(encoded))


def _read_ascii(data: bytes, offset: int) -> str:
    return data[offset:offset + 0x20].split(b"\0", 1)[0].decode("ascii", errors="strict")


def nested_payload_length(header: bytes) -> int:
    """Validate a repeated 0x400-byte header and return its bounded length."""
    if len(header) != NESTED_HEADER_SIZE:
        raise ValueError("RT12COL nested header must be exactly 0x400 bytes")
    if header[NESTED_UUID_OFFSET:NESTED_UUID_OFFSET + 16] != REALTEK_IMAGE_UUID:
        raise ValueError("unexpected Realtek application UUID")
    length = int.from_bytes(
        header[NESTED_PAYLOAD_LENGTH_OFFSET:NESTED_PAYLOAD_LENGTH_OFFSET + 4], "little"
    )
    maximum = APP_PARTITION_SIZE - NESTED_HEADER_SIZE
    if not 16 <= length <= maximum:
        raise ValueError(f"payload length {length:#x} is outside the RT12COL application partition")
    return length


def parse_partition(partition: bytes, *, require_payload_sha: bool = True) -> PartitionImage:
    """Require an internally authenticated Realtek header+payload read."""
    if len(partition) < NESTED_HEADER_SIZE:
        raise ValueError("truncated RT12COL application partition")
    header = partition[:NESTED_HEADER_SIZE]
    length = nested_payload_length(header)
    used = NESTED_HEADER_SIZE + length
    if len(partition) < used:
        raise ValueError(f"partition read is short: need {used} bytes, got {len(partition)}")
    body = bytes(partition[:used])
    payload = body[NESTED_HEADER_SIZE:]
    stored = header[NESTED_PAYLOAD_SHA_OFFSET:NESTED_PAYLOAD_SHA_OFFSET + 32]
    computed = hashlib.sha256(payload).digest()
    if require_payload_sha and stored != computed:
        raise ValueError("installed RT12COL payload does not match its nested SHA-256")
    flags = int.from_bytes(header[NESTED_FLAGS_OFFSET:NESTED_FLAGS_OFFSET + 2], "little")
    return PartitionImage(
        body=body,
        payload=payload,
        payload_length=length,
        flags=flags,
        payload_sha256=computed.hex(),
        stored_payload_sha256=stored.hex(),
        payload_sha_matches=stored == computed,
    )


def reconstruct_stock_ota(
    partition: bytes,
    *,
    version: str = STOCK_VERSION,
    expected_payload_sha256: str | None = None,
) -> bytes:
    """Create a QRing OTA wrapper around the exact authenticated installed body."""
    parsed = parse_partition(partition, require_payload_sha=False)
    if not parsed.payload_sha_matches:
        if expected_payload_sha256 != parsed.payload_sha256:
            raise ValueError(
                "factory header SHA is stale; an independently repeated payload SHA is required"
            )
        normalized = bytearray(parsed.body)
        normalized[NESTED_PAYLOAD_SHA_OFFSET:NESTED_PAYLOAD_SHA_OFFSET + 32] = bytes.fromhex(
            parsed.payload_sha256
        )
        flags = parsed.flags & ~fwbuild.NOT_READY_BIT
        normalized[NESTED_FLAGS_OFFSET:NESTED_FLAGS_OFFSET + 2] = flags.to_bytes(2, "little")
        parsed = parse_partition(bytes(normalized))
    wrapper = bytearray(OUTER_HEADER_SIZE)
    wrapper[0:4] = QRING_MAGIC
    wrapper[4:8] = len(parsed.body).to_bytes(4, "little")
    wrapper[8:12] = len(parsed.body).to_bytes(4, "little")
    wrapper[0x10:0x30] = _ascii_field(version)
    wrapper[0x30:0x50] = _ascii_field(HARDWARE)
    image = wrapper + parsed.body
    image[0x0C:0x10] = (sum(image[OUTER_HEADER_SIZE:]) & 0xFFFFFFFF).to_bytes(4, "little")
    result = bytes(image)
    problems = verify_ota(result, require_ready=False)
    if problems:
        raise ValueError("reconstructed RT12COL image failed validation: " + "; ".join(problems))
    return result


def verify_ota(data: bytes, *, require_ready: bool = True) -> list[str]:
    """Return every structural/authentication problem in an RT12COL OTA image."""
    problems: list[str] = []
    if len(data) < fwbuild.PAYLOAD_START + 16:
        return ["OTA image is truncated"]
    if data[:4] != QRING_MAGIC:
        problems.append("wrong QRing wrapper magic")
    body_length = len(data) - OUTER_HEADER_SIZE
    for offset in (4, 8):
        if int.from_bytes(data[offset:offset + 4], "little") != body_length:
            problems.append(f"outer body length at {offset:#x} is stale")
    if int.from_bytes(data[0x0C:0x10], "little") != (sum(data[OUTER_HEADER_SIZE:]) & 0xFFFFFFFF):
        problems.append("outer body sum is stale")
    try:
        firmware = _read_ascii(data, 0x10)
        hardware = _read_ascii(data, 0x30)
    except (UnicodeDecodeError, ValueError):
        firmware, hardware = "", ""
        problems.append("outer identity is not ASCII")
    if not firmware.startswith("RT12COL_"):
        problems.append(f"unexpected firmware identity {firmware!r}")
    if hardware != HARDWARE:
        problems.append(f"unexpected hardware identity {hardware!r}")
    try:
        parsed = parse_partition(data[OUTER_HEADER_SIZE:])
    except ValueError as exc:
        problems.append(str(exc))
        return problems
    if len(parsed.body) != body_length:
        problems.append("outer image contains bytes beyond the declared nested payload")
    if require_ready and parsed.flags & fwbuild.NOT_READY_BIT:
        problems.append("nested not_ready flag is set")
    return problems


def patch_ota(
    source: bytes,
    edits: dict[int, tuple[int, int]],
    *,
    version: str,
) -> bytes:
    """Apply strict, size-preserving file-offset edits to a verified RT12COL OTA.

    This primitive intentionally defines no RT12COL patch sites. A caller must
    supply both the expected old byte and replacement byte for every edit after
    the captured source has been mapped. Header edits and the structurally
    identified RT12COL DFU timer site are rejected.
    """
    problems = verify_ota(source, require_ready=False)
    if problems:
        raise ValueError("invalid RT12COL source: " + "; ".join(problems))
    out = bytearray(source)
    for offset, pair in sorted(edits.items()):
        if type(offset) is not int or not fwbuild.PAYLOAD_START <= offset < len(out):
            raise ValueError(f"edit at {offset!r} is outside the application payload")
        if DFU_REASSEMBLY_TIMER_OFFSET <= offset < (
            DFU_REASSEMBLY_TIMER_OFFSET + DFU_REASSEMBLY_TIMER_SIZE
        ):
            raise ValueError(
                f"{DFU_REASSEMBLY_TIMER_OFFSET:#x}.."
                f"{DFU_REASSEMBLY_TIMER_OFFSET + DFU_REASSEMBLY_TIMER_SIZE:#x} "
                "is the protected DFU reassembly timer"
            )
        if (not isinstance(pair, tuple) or len(pair) != 2
                or any(type(value) is not int or not 0 <= value <= 0xFF for value in pair)):
            raise ValueError("every edit must be an (expected_old, new) byte pair")
        expected, replacement = pair
        if out[offset] != expected:
            raise ValueError(
                f"source mismatch at {offset:#x}: expected {expected:#04x}, got {out[offset]:#04x}"
            )
        out[offset] = replacement
    out[0x10:0x30] = _ascii_field(version)
    out = bytearray(fwbuild.refresh(bytes(out)))
    body_length = len(out) - OUTER_HEADER_SIZE
    out[4:8] = body_length.to_bytes(4, "little")
    out[8:12] = body_length.to_bytes(4, "little")
    out[0x0C:0x10] = (sum(out[OUTER_HEADER_SIZE:]) & 0xFFFFFFFF).to_bytes(4, "little")
    result = bytes(out)
    problems = verify_ota(result)
    if problems:
        raise ValueError("patched RT12COL image failed validation: " + "; ".join(problems))
    return result
