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

# Determined 2026-09-06 from a 2-minute stationary capture across 8 attitudes.
# See docs/HARDWARE.md; the short version is three independent lines of evidence:
#
#   - byte structure: bytes 2/4/6 take ~10 distinct values while 3/5/7 take
#     ~120, which is high-byte/low-byte for a 16-bit big-endian word. This is
#     decoder-independent -- no candidate had to be assumed to see it.
#   - coverage: it reconciles 82 of 85 stationary windows to a constant
#     gravity magnitude. The runners-up only manage 51-75.
#   - physics: 8005 counts per g implies a full scale of +/-4.09g, within 2%
#     of the standard +/-4g setting.
DEFAULT_UNPACKER = "signed16_be"

OUTLIER_TOLERANCE = 0.15
"""A window disagreeing by more than this is evidence the decode is wrong."""

COUNTS_PER_G = 8005.0
"""Measured, not from a datasheet. Divide raw axis values by this for g."""


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


def raw_axes(payload: bytes) -> tuple[int, int, int]:
    """
    Unsigned 12-bit axes straight off the wire, no sign interpretation.

    Used to judge whether the ring was moving, which must not depend on which
    decoder is being evaluated -- otherwise the candidate under test gets to
    choose the data it is scored on.
    """
    return (
        (payload[6] << 4) | (payload[7] & 0x0F),
        (payload[2] << 4) | (payload[3] & 0x0F),
        (payload[4] << 4) | (payload[5] & 0x0F),
    )


def stationary_windows(
    samples: list[tuple[float, bytes]], window_s: float = 1.0, max_spread: float = 40.0
) -> list[list[bytes]]:
    """
    Split a capture into fixed windows and keep only the still ones.

    A six-orientation capture is mostly stationary, but the moves between
    orientations are real acceleration and they wreck the gravity-constancy
    test. On the first real capture, discarding them cut every candidate's
    spread roughly in half.
    """
    import statistics

    kept: list[list[bytes]] = []
    current: list[bytes] = []
    start = samples[0][0] if samples else 0.0

    for timestamp, payload in samples:
        if timestamp - start >= window_s:
            if current:
                columns = list(zip(*[raw_axes(p) for p in current]))
                if max(statistics.pstdev(c) for c in columns) < max_spread:
                    kept.append(current)
            current, start = [], timestamp
        current.append(payload)

    if current:
        columns = list(zip(*[raw_axes(p) for p in current]))
        if max(statistics.pstdev(c) for c in columns) < max_spread:
            kept.append(current)

    return kept


def count_orientations(windows: list[list[bytes]], bucket: int = 200) -> int:
    """
    How many distinct attitudes the still windows actually cover.

    The ranking is only trustworthy when the candidates were forced to disagree,
    which needs gravity pointing several different ways. Reporting this stops a
    tie being read as a result when the real problem is that the ring barely
    moved.
    """
    import statistics

    seen = set()
    for window in windows:
        columns = zip(*[raw_axes(p) for p in window])
        seen.add(tuple(round(statistics.fmean(c) / bucket) for c in columns))
    return len(seen)


def score_unpackers(payloads: list[bytes]) -> list[tuple[str, float, float]]:
    """
    Rank candidate unpackers against a stationary capture.

    Returns (name, median_magnitude, spread, coverage), best first.
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
    import statistics

    results = []
    for name in UNPACKERS:
        mags = [decode(p, name).magnitude for p in payloads]
        if len(mags) < 2:
            continue
        median = statistics.median(mags)
        if median == 0:
            continue

        # Coverage first, spread second.
        #
        # Ranking on spread alone is exploitable: a decoder that is right in
        # some orientations and wildly wrong in others produces a tight cluster
        # plus a scatter of outliers, and scores well once the outliers are
        # excluded. On the real capture that put the worst candidate top, by
        # discarding 40% of the data as disagreement. A correct decode makes
        # *every* stationary sample read 1g, so how much of the data it
        # reconciles is the primary evidence.
        agreeing = [m for m in mags if abs(m - median) / median <= OUTLIER_TOLERANCE]
        coverage = len(agreeing) / len(mags)
        if len(agreeing) < 2:
            continue
        spread = statistics.pstdev(agreeing) / statistics.fmean(agreeing)
        results.append((name, median, spread, coverage))

    return sorted(results, key=lambda r: (-round(r[3], 2), r[2]))
