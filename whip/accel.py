"""
Accelerometer sample decoding for 0xA1 subtype 0x03 notifications.

The ring carries an STK8321, a 12 bit accelerometer, so each axis is 12 bits
packed across two bytes. Byte order in the notification is *not* X, Y, Z:

    bytes 2-3  ->  Y
    bytes 4-5  ->  Z
    bytes 6-7  ->  X

That ordering comes from the one public implementation that is known to work
(edgeimpulse/example-data-collection-colmi-r02).

The sign handling in that implementation is internally inconsistent: it tests
bit 3 of the high byte but subtracts 1 << 11, which is not a coherent two's
complement decode for a 12 bit value. It may still be correct if the ring packs
values in a way we have not fully understood, or it may be a latent bug that
happens not to matter for step counting.

Rather than guess, we decode with several candidate unpackers and let real data
decide. A stationary ring measures only gravity, so the correct unpacker is the
one whose vector magnitude stays constant while the ring sits still. See
`score_unpackers` and probe/analyze.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# Byte offsets of each axis within the 16 byte notification.
AXIS_OFFSETS = {"x": 6, "y": 2, "z": 4}


def _reference(hi: int, lo: int) -> int:
    """Exactly what the Edge Impulse collector does. Kept for bug-for-bug parity."""
    value = (hi << 4) | (lo & 0x0F)
    if hi & 0x08:
        value -= 1 << 11
    return value


def _signed12(hi: int, lo: int) -> int:
    """Coherent 12 bit two's complement, high byte first."""
    value = (hi << 4) | (lo & 0x0F)
    if value & 0x800:
        value -= 1 << 12
    return value


def _signed12_swapped(hi: int, lo: int) -> int:
    """Coherent 12 bit two's complement, low byte first."""
    value = (lo << 4) | (hi & 0x0F)
    if value & 0x800:
        value -= 1 << 12
    return value


def _signed16_le(hi: int, lo: int) -> int:
    return int.from_bytes(bytes([hi, lo]), "little", signed=True)


def _signed16_be(hi: int, lo: int) -> int:
    return int.from_bytes(bytes([hi, lo]), "big", signed=True)


UNPACKERS: dict[str, Callable[[int, int], int]] = {
    "reference": _reference,
    "signed12": _signed12,
    "signed12_swapped": _signed12_swapped,
    "signed16_le": _signed16_le,
    "signed16_be": _signed16_be,
}

DEFAULT_UNPACKER = "reference"


@dataclass(frozen=True)
class AccelSample:
    x: int
    y: int
    z: int

    @property
    def magnitude(self) -> float:
        return (self.x**2 + self.y**2 + self.z**2) ** 0.5


def decode(payload: bytes, unpacker: str = DEFAULT_UNPACKER) -> AccelSample:
    """Decode one accelerometer notification payload into a sample."""
    if len(payload) < 8:
        raise ValueError(f"payload too short to hold a sample: {len(payload)} bytes")

    fn = UNPACKERS[unpacker]
    axes = {axis: fn(payload[off], payload[off + 1]) for axis, off in AXIS_OFFSETS.items()}
    return AccelSample(**axes)


def score_unpackers(payloads: list[bytes]) -> list[tuple[str, float, float]]:
    """
    Rank candidate unpackers against a stationary capture.

    Returns (name, mean_magnitude, coefficient_of_variation) sorted best first.
    While the ring is still, the only acceleration is gravity, so magnitude
    should be near constant. The unpacker with the lowest relative spread is
    almost certainly the correct one.

    IMPORTANT: the capture must cover several orientations, including the
    negative direction of each axis. With gravity on a single axis every value
    stays positive, the candidates never disagree about sign, and several of
    them tie at near-zero spread -- the ranking is then meaningless. Rest the
    ring on each of its six faces for ten seconds and the sign handling, which
    is the only thing the candidates actually dispute, becomes decisive.
    """
    results = []
    for name in UNPACKERS:
        mags = [decode(p, name).magnitude for p in payloads]
        if not mags:
            continue
        mean = sum(mags) / len(mags)
        if mean == 0:
            continue
        variance = sum((m - mean) ** 2 for m in mags) / len(mags)
        results.append((name, mean, (variance**0.5) / mean))

    return sorted(results, key=lambda r: r[2])
