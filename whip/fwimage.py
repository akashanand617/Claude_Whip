"""
Firmware image inspection.

Never flash an image you have not read. This module answers, offline and before
anything is written to the ring:

  - what hardware does the image declare, and does it match the ring
  - is it byte-identical to the artifact that was reviewed
  - what raw motion rate will it actually produce

That last one matters most. The rate is not metadata, it is an immediate operand
in the firmware, so the only honest way to know what an image does is to find
that instruction and read it.

Two container formats are in circulation:

  `78563412`  payload at 0x100, header CRC32 verifies over the payload.
              The 2024 R02_V3.0 lineage.
  `e5c3bd81`  payload at 0x50, nested Realtek container, header checksum is
              not a plain CRC32. The RT02CR / RY02 lineage.

Both hold plain ARM Thumb. An earlier version of this project mistook the
second for an encrypted blob on the strength of its entropy and a checksum that
would not verify. Neither is evidence of encryption -- always disassemble before
concluding an image is opaque.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

# Container magics and where the payload starts in each.
MAGIC_PLAINTEXT = bytes.fromhex("78563412")
MAGIC_REALTEK = bytes.fromhex("e5c3bd81")
PAYLOAD_OFFSETS = {MAGIC_PLAINTEXT: 0x100, MAGIC_REALTEK: 0x50}

FW_STRING_OFFSET = 0x10
HW_STRING_OFFSET = 0x30
STRING_LEN = 0x20

# The raw motion period is built as `movs rN, #imm` followed by `lsls rN, rN, #3`,
# i.e. imm * 8 milliseconds. Thumb encodings:
#   movs rN, #imm8   ->  0x2000 | (N << 8) | imm
#   lsls rN, rN, #3  ->  (3 << 6) | (N << 3) | N
MILLISECONDS_PER_TICK = 8
_MAX_GAP_BYTES = 10


@dataclass(frozen=True)
class TimerSite:
    """A `movs rN,#imm / lsls rN,rN,#3` pair -- a period in milliseconds."""

    offset: int
    register: int
    immediate: int

    @property
    def period_ms(self) -> int:
        return self.immediate * MILLISECONDS_PER_TICK

    @property
    def rate_hz(self) -> float:
        return 1000.0 / self.period_ms if self.period_ms else float("inf")


@dataclass
class FirmwareImage:
    path: Path
    size: int
    magic: bytes
    payload_offset: int | None
    firmware_string: str
    hardware_string: str
    sha256: str
    crc32_verifies: bool | None
    timer_sites: list[TimerSite]

    @property
    def container(self) -> str:
        if self.magic == MAGIC_PLAINTEXT:
            return "plaintext (R02_V3.0 lineage)"
        if self.magic == MAGIC_REALTEK:
            return "nested Realtek (RT02CR / RY02 lineage)"
        return "unrecognised"

    def matches_hardware(self, hardware: str | None) -> bool | None:
        """None when we have nothing to compare against."""
        if not hardware:
            return None
        return self.hardware_string.strip().upper() == hardware.strip().upper()


def _read_string(data: bytes, offset: int) -> str:
    raw = data[offset : offset + STRING_LEN]
    return raw.split(b"\0")[0].decode("ascii", errors="replace").strip()


def _lsls_encoding(register: int) -> bytes:
    """Little-endian bytes for `lsls rN, rN, #3`."""
    halfword = (3 << 6) | (register << 3) | register
    return halfword.to_bytes(2, "little")


def find_timer_sites(payload: bytes) -> list[TimerSite]:
    """
    Locate every `movs rN,#imm` that feeds an `lsls rN,rN,#3` shortly after.

    Searching from the shift backwards is far cheaper than disassembling the
    whole image, and the shift is the distinctive half of the idiom -- a bare
    `movs` is everywhere, `lsls rN,rN,#3` is not.
    """
    sites: list[TimerSite] = []

    for register in range(8):
        shift = _lsls_encoding(register)
        movs_high = 0x20 | register  # high byte of `movs rN, #imm`

        for match in re.finditer(re.escape(shift), payload):
            shift_at = match.start()
            if shift_at % 2:
                continue  # Thumb instructions are halfword aligned

            start = max(0, shift_at - _MAX_GAP_BYTES)
            for candidate in range(shift_at - 2, start - 1, -2):
                if payload[candidate + 1] != movs_high:
                    continue
                immediate = payload[candidate]
                # `movs rN, #0` followed by a shift is how the compiler zeroes a
                # register, not a period. Reporting it as a timer produced an
                # infinite rate and made the fast-site count meaningless.
                if immediate:
                    sites.append(TimerSite(offset=candidate, register=register, immediate=immediate))
                break

    return sorted(sites, key=lambda s: s.offset)


def inspect(path: str | Path) -> FirmwareImage:
    """Parse an OTA image and report everything decidable without a ring."""
    path = Path(path)
    data = path.read_bytes()

    magic = data[0:4]
    payload_offset = PAYLOAD_OFFSETS.get(magic)

    crc32_verifies: bool | None = None
    if payload_offset is not None:
        stored = int.from_bytes(data[4:8], "little")
        crc32_verifies = stored == (zlib.crc32(data[payload_offset:]) & 0xFFFFFFFF)

    payload = data[payload_offset:] if payload_offset is not None else b""

    return FirmwareImage(
        path=path,
        size=len(data),
        magic=magic,
        payload_offset=payload_offset,
        firmware_string=_read_string(data, FW_STRING_OFFSET),
        hardware_string=_read_string(data, HW_STRING_OFFSET),
        sha256=hashlib.sha256(data).hexdigest(),
        crc32_verifies=crc32_verifies,
        timer_sites=find_timer_sites(payload),
    )


# Sites that carry the timer idiom but must never be patched. Upstream's
# research notes record 0x007ed4 as part of incoming DFU frame reassembly:
# lowering it can make large DFU Data frames CRC-check before every BLE write
# slice has arrived, breaking future OTA recovery. It looks exactly like a rate
# candidate, which is precisely why it needs naming.
DO_NOT_PATCH = {
    0x007ED4: "DFU frame reassembly -- patching it can break future OTA recovery",
}


def raw_motion_candidates(image: FirmwareImage, max_period_ms: int = 2000) -> list[TimerSite]:
    """
    Timer sites plausible as the raw motion period.

    The idiom is used for several unrelated timers, so this is a filter and not
    an identification. Periods of 1000 ms (stock, 1 Hz) and anything fast enough
    to matter for gesture work are what we care about.

    Sites in DO_NOT_PATCH are excluded outright -- they are known to be
    something else, and offering them as rate candidates invites a change that
    costs the ability to recover the ring.
    """
    return [
        s
        for s in image.timer_sites
        if 0 < s.period_ms <= max_period_ms and s.offset not in DO_NOT_PATCH
    ]
