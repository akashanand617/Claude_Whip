"""
QRing DFU protocol -- frame construction and response parsing.

Ported from the TypeScript implementation in Nosh118/colmi-ring-tools. Kept
pure: nothing here touches BLE, so every byte that would reach the ring can be
built and asserted in a test first. That property is the whole point. A bug in
this file bricks a ring with no recovery path, so it must be verifiable without
one attached.

The framing:

    BC | cmd | len_lo | len_hi | crc_lo | crc_hi | payload...

`len` is the payload length and `crc` is CRC-16/Modbus over the payload only.
Firmware is sent as 1024-byte chunks, each wrapped in a DATA frame and then
split into BLE-sized segments for writing.

Sequence: START -> INIT -> DATA * n -> CHECK -> END.

Init type 0x01 makes the ring compare the hardware string on the first chunk.
Init type 0x04 skips that comparison. Skipping it is not on its own enough to
activate an arbitrary image -- the nested Realtek header must also be
consistent -- but it is what the catalogue images expect.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = 0xBC

CMD_START = 0x01
CMD_INIT = 0x02
CMD_DATA = 0x03
CMD_CHECK = 0x04
CMD_END = 0x05

COMMAND_NAMES = {
    CMD_START: "start",
    CMD_INIT: "init",
    CMD_DATA: "data",
    CMD_CHECK: "check",
    CMD_END: "end",
}

CHUNK_SIZE_BYTES = 1024
HEADER_SIZE = 6
MIN_SEGMENT_BYTES = 20

# Status codes the ring returns in payload[0]. 6 is the one to watch: the ring
# refuses the transfer outright when it is too low on charge.
STATUS_NAMES = {
    0: "ok",
    1: "data-size",
    2: "data-content",
    3: "command-status",
    4: "command-format",
    5: "inner-error",
    6: "low-battery",
}


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte & 0xFF
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def checksum16(data: bytes) -> int:
    total = 0
    for byte in data:
        total = (total + (byte & 0xFF)) & 0xFFFF
    return total


@dataclass(frozen=True)
class Frame:
    command: int
    payload: bytes
    payload_crc16: int

    @property
    def bytes(self) -> bytes:
        header = bytes(
            [
                MAGIC,
                self.command & 0xFF,
                len(self.payload) & 0xFF,
                (len(self.payload) >> 8) & 0xFF,
                self.payload_crc16 & 0xFF,
                (self.payload_crc16 >> 8) & 0xFF,
            ]
        )
        return header + self.payload

    @property
    def hex(self) -> str:
        return self.bytes.hex()


@dataclass(frozen=True)
class Response:
    valid: bool
    command: int | None
    status_code: int | None
    status_name: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.valid and self.status_code == 0


def build_frame(command: int, payload: bytes = b"") -> Frame:
    return Frame(command=command, payload=payload, payload_crc16=crc16_modbus(payload))


def start_frame() -> Frame:
    return build_frame(CMD_START)


def init_frame(firmware: bytes, init_type: int) -> Frame:
    """
    Announce the transfer: size, CRC-16 and 16-bit sum of the whole image.

    The ring uses these to reject a truncated or corrupted transfer before it
    commits anything, which is the main thing standing between a dropped
    connection and a dead ring.
    """
    if init_type not in (1, 4):
        raise ValueError(f"init_type must be 1 or 4, got {init_type}")

    payload = bytearray(9)
    payload[0] = init_type
    payload[1:5] = len(firmware).to_bytes(4, "little")
    payload[5:7] = crc16_modbus(firmware).to_bytes(2, "little")
    payload[7:9] = checksum16(firmware).to_bytes(2, "little")
    return build_frame(CMD_INIT, bytes(payload))


def data_frame(firmware: bytes, chunk_index: int) -> Frame:
    """One 1024-byte chunk, prefixed with a 1-based little-endian index."""
    offset = chunk_index * CHUNK_SIZE_BYTES
    chunk = firmware[offset : offset + CHUNK_SIZE_BYTES]
    if not chunk:
        raise IndexError(f"chunk {chunk_index} is past the end of a {len(firmware)} byte image")
    payload = (chunk_index + 1).to_bytes(2, "little") + chunk
    return build_frame(CMD_DATA, payload)


def check_frame() -> Frame:
    return build_frame(CMD_CHECK)


def end_frame() -> Frame:
    return build_frame(CMD_END)


def chunk_count(byte_length: int) -> int:
    return -(-byte_length // CHUNK_SIZE_BYTES)


def segment(frame: Frame, segment_bytes: int) -> list[bytes]:
    """Split a frame into BLE-writable pieces."""
    if segment_bytes < MIN_SEGMENT_BYTES:
        raise ValueError(f"segment size must be at least {MIN_SEGMENT_BYTES} bytes")
    data = frame.bytes
    return [data[i : i + segment_bytes] for i in range(0, len(data), segment_bytes)]


def parse_response(data: bytes) -> Response:
    """Validate a notification from the DFU characteristic."""
    if len(data) < HEADER_SIZE:
        return _invalid(f"frame is shorter than the {HEADER_SIZE}-byte header")
    if data[0] != MAGIC:
        return _invalid(f"frame magic is {data[0]:#04x}, not {MAGIC:#04x}")

    payload_length = data[2] | (data[3] << 8)
    if payload_length != len(data) - HEADER_SIZE:
        return _invalid("declared payload length does not match frame size")

    payload = data[HEADER_SIZE:]
    stored = data[4] | (data[5] << 8)
    computed = crc16_modbus(payload)
    if stored != computed:
        return _invalid(f"payload CRC16 {stored:#06x} does not match computed {computed:#06x}")

    status_code = payload[0] if payload else None
    return Response(
        valid=True,
        command=data[1],
        status_code=status_code,
        status_name=STATUS_NAMES.get(status_code, f"status-{status_code}")
        if status_code is not None
        else "missing-status",
    )


def _invalid(error: str) -> Response:
    return Response(valid=False, command=None, status_code=None, status_name="invalid", error=error)


def firmware_stats(firmware: bytes) -> dict:
    """Size, CRC-16 and checksum-16 -- the fields published in the upstream manifest."""
    return {
        "size": len(firmware),
        "crc16": f"{crc16_modbus(firmware):#06x}",
        "checksum16": f"{checksum16(firmware):#06x}",
    }
