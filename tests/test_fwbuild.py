import hashlib
from pathlib import Path

import pytest

from whip import fwbuild, fwimage

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
LOW_LATENCY = FIRMWARE / "rt02cr-low-latency.bin"
STOCK = FIRMWARE / "rt02cr-stock-3.12.02.bin"

pytestmark = pytest.mark.skipif(not LOW_LATENCY.exists(), reason="firmware images not present")

TIMER_OFFSET = 0x2248  # the raw motion period in the low-latency image


def test_refresh_reproduces_the_published_image_exactly():
    """
    The round trip that validates everything else.

    Upstream built this image with an independent implementation. If refreshing
    its derived fields reproduces it byte for byte, our understanding of the
    container is correct -- and every image we build from it inherits that
    correctness.
    """
    data = LOW_LATENCY.read_bytes()
    assert fwbuild.refresh(data) == data


def test_published_image_is_internally_consistent():
    assert fwbuild.verify(LOW_LATENCY.read_bytes()) == []


def test_stock_image_ships_unready_and_unhashed():
    """
    Not a defect. The vendor image carries `not_ready` and a SHA that is not a
    hash of its payload, because the installer fills that in. It is exactly why
    a custom image must refresh both, and why an image that transfers can still
    fail to boot.
    """
    problems = fwbuild.verify(STOCK.read_bytes())
    assert any("not_ready" in p for p in problems)
    assert any("SHA-256" in p for p in problems)


def test_patch_changes_only_the_target_byte_and_derived_fields():
    data = LOW_LATENCY.read_bytes()
    patched = fwbuild.patch(data, {TIMER_OFFSET: 0x04})

    differing = {i for i, (a, b) in enumerate(zip(data, patched)) if a != b}
    expected = {TIMER_OFFSET}
    expected |= set(range(fwbuild.SHA256_OFFSET, fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN))
    expected |= set(range(fwbuild.BODY_SUM_OFFSET, fwbuild.BODY_SUM_OFFSET + 4))

    assert differing <= expected, "patch touched something it should not have"
    assert TIMER_OFFSET in differing
    assert patched[TIMER_OFFSET] == 0x04


def test_patched_image_stays_consistent():
    patched = fwbuild.patch(LOW_LATENCY.read_bytes(), {TIMER_OFFSET: 0x04})
    assert fwbuild.verify(patched) == []


def test_patched_image_reports_the_new_rate(tmp_path):
    out = tmp_path / "custom.bin"
    out.write_bytes(fwbuild.patch(LOW_LATENCY.read_bytes(), {TIMER_OFFSET: 0x04}))

    fast = [s for s in fwimage.raw_motion_candidates(fwimage.inspect(out)) if s.rate_hz >= 25]
    periods = {s.period_ms for s in fast}
    assert 32 in periods, "expected a 32 ms / 31.25 Hz site"
    assert 16 not in periods, "the 16 ms site should be gone"


def test_body_sum_is_computed_after_the_other_fields():
    """
    The SHA and the flags both sit inside the range the body sum covers, so
    computing the sum first leaves it stale. Verify catches that ordering bug.
    """
    patched = fwbuild.patch(LOW_LATENCY.read_bytes(), {TIMER_OFFSET: 0x03})
    stored = int.from_bytes(patched[fwbuild.BODY_SUM_OFFSET : fwbuild.BODY_SUM_OFFSET + 4], "little")
    assert stored == sum(patched[fwbuild.BODY_START :]) & 0xFFFFFFFF


def test_sha_covers_the_payload_from_0x450():
    patched = fwbuild.patch(LOW_LATENCY.read_bytes(), {TIMER_OFFSET: 0x05})
    stored = patched[fwbuild.SHA256_OFFSET : fwbuild.SHA256_OFFSET + fwbuild.SHA256_LEN]
    assert stored == hashlib.sha256(patched[fwbuild.PAYLOAD_START :]).digest()


def test_patch_refuses_edits_outside_the_payload():
    data = LOW_LATENCY.read_bytes()
    with pytest.raises(ValueError, match="outside the payload"):
        fwbuild.patch(data, {fwbuild.FLAGS_OFFSET: 0x00})
    with pytest.raises(ValueError, match="outside the payload"):
        fwbuild.patch(data, {len(data) + 1: 0x00})


def test_patch_refuses_non_byte_values():
    with pytest.raises(ValueError, match="not a byte"):
        fwbuild.patch(LOW_LATENCY.read_bytes(), {TIMER_OFFSET: 300})


def test_refresh_clears_not_ready():
    data = bytearray(LOW_LATENCY.read_bytes())
    flags = int.from_bytes(data[fwbuild.FLAGS_OFFSET : fwbuild.FLAGS_OFFSET + 2], "little")
    data[fwbuild.FLAGS_OFFSET : fwbuild.FLAGS_OFFSET + 2] = (flags | fwbuild.NOT_READY_BIT).to_bytes(2, "little")

    assert fwbuild.read_fields(bytes(data)).not_ready
    assert not fwbuild.read_fields(fwbuild.refresh(bytes(data))).not_ready
