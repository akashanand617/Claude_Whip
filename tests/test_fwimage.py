from pathlib import Path

import pytest

from whip import fwimage

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
STOCK = FIRMWARE / "rt02cr-stock-3.12.02.bin"
LOW_LATENCY = FIRMWARE / "rt02cr-low-latency.bin"

# Published in the upstream manifest and verified on download.
LOW_LATENCY_SHA256 = "2ea1bb08826891604fb714a3820c859d77f52f8d22f1d9a870db10cd5fbffe34"

pytestmark = pytest.mark.skipif(not STOCK.exists(), reason="firmware images not present")


def test_low_latency_image_is_the_reviewed_artifact():
    """
    Pin the hash. This image gets flashed to hardware with no recovery path
    beyond the stock restore, so a silent change upstream must break the build
    rather than reach the ring.
    """
    assert fwimage.inspect(LOW_LATENCY).sha256 == LOW_LATENCY_SHA256


def test_both_images_declare_this_ring_hardware():
    for path in (STOCK, LOW_LATENCY):
        assert fwimage.inspect(path).hardware_string == "RT02CR_V3.1"


def test_container_is_recognised_and_not_opaque():
    image = fwimage.inspect(STOCK)
    assert image.magic == fwimage.MAGIC_REALTEK
    assert image.payload_offset == 0x50
    # The header checksum is not a plain CRC32 for this container. That is a
    # different algorithm, not encryption -- the payload disassembles fine.
    assert image.crc32_verifies is False
    assert image.timer_sites, "no Thumb timer idioms found; payload is not readable as code"


def test_stock_carries_the_one_hertz_raw_motion_timer():
    sites = fwimage.inspect(STOCK).timer_sites
    assert any(s.period_ms == 1000 for s in sites), "expected the 125 * 8 ms stock idiom"


def test_low_latency_adds_a_16ms_timer_that_stock_does_not_have():
    """
    The claim being checked is narrow and specific: relative to stock, this
    image introduces one fast period. Both images already contain a 24 ms site,
    so 'has a fast timer' alone would not distinguish them -- the 16 ms site is
    what the patch adds.
    """
    stock = {s.period_ms for s in fwimage.inspect(STOCK).timer_sites}
    low_latency = fwimage.inspect(LOW_LATENCY).timer_sites

    assert 16 not in stock
    fast = [s for s in low_latency if s.period_ms == 16]
    assert len(fast) == 1
    assert fast[0].immediate == 2
    assert fast[0].rate_hz == pytest.approx(62.5)
    assert fast[0].rate_hz >= 25.0, "must clear the M0 gate"


def test_zero_immediates_are_not_timers():
    """`movs rN, #0` before a shift zeroes a register; it is not a period."""
    payload = bytes([0x00, 0x22]) + bytes([0xD2, 0x00])
    assert fwimage.find_timer_sites(payload) == []

    for path in (STOCK, LOW_LATENCY):
        assert all(s.immediate > 0 for s in fwimage.inspect(path).timer_sites)


def test_hardware_match_check():
    image = fwimage.inspect(LOW_LATENCY)
    assert image.matches_hardware("RT02CR_V3.1") is True
    assert image.matches_hardware("rt02cr_v3.1") is True
    assert image.matches_hardware("R02_V3.0") is False
    assert image.matches_hardware(None) is None


def test_find_timer_sites_on_a_synthetic_pattern():
    # movs r2, #5  /  lsls r2, r2, #3   ->  40 ms, 25 Hz
    payload = b"\x00\x00" + bytes([0x05, 0x22]) + bytes([0xD2, 0x00]) + b"\x00\x00"
    sites = fwimage.find_timer_sites(payload)
    assert len(sites) == 1
    assert sites[0].register == 2
    assert sites[0].immediate == 5
    assert sites[0].period_ms == 40
    assert sites[0].rate_hz == pytest.approx(25.0)


def test_timer_site_ignores_movs_too_far_from_the_shift():
    payload = bytes([0x05, 0x22]) + b"\x00" * 16 + bytes([0xD2, 0x00])
    assert fwimage.find_timer_sites(payload) == []


def test_dfu_reassembly_site_is_never_offered_as_a_rate_candidate():
    """
    0x007ed4 carries the same 125 << 3 shape as a real timer but belongs to DFU
    frame reassembly. Patching it can break OTA recovery, so it must not appear
    in the list a future custom build would pick from.
    """
    assert 0x007ED4 in fwimage.DO_NOT_PATCH
    for path in (STOCK, LOW_LATENCY):
        image = fwimage.inspect(path)
        assert all(s.offset not in fwimage.DO_NOT_PATCH for s in fwimage.raw_motion_candidates(image))


def test_optical_start_site_is_located_by_signature():
    """
    The raw-mode optical start is one `ldr` in the sensor enable handler. Both
    3.12.00-based images carry it at the same payload offset (the timer patch
    is elsewhere), and the branch that replaces it must land on the function's
    `pop` -- not the `orrs` that would OR the raw bit into the sensor mask.
    """
    for path in (LOW_LATENCY, FIRMWARE / "rt02cr-25hz.bin"):
        data = path.read_bytes()
        site = fwimage.find_optical_start_site(data[0x50:])
        assert site is not None
        assert 0x50 + site.load_offset == 0xF710
        assert 0x50 + site.return_offset == 0xF6DE
        assert data[0xF710:0xF712] == bytes.fromhex("5148")
        assert data[0xF6DE:0xF6E0] == bytes.fromhex("f8bd")
        assert site.branch == bytes.fromhex("e5e7")  # b #-27 halfwords


def test_optical_start_site_refuses_ambiguity():
    sig = fwimage.OPTICAL_START_SIGNATURE
    ret = fwimage.OPTICAL_RETURN_SIGNATURE
    assert fwimage.find_optical_start_site(b"\x00" * 64) is None
    assert fwimage.find_optical_start_site(ret + b"\x00" * 8 + sig + b"\x00" * 8 + sig) is None, "two starts"
    assert fwimage.find_optical_start_site(b"\x00" * 8 + sig) is None, "no return sequence"
    site = fwimage.find_optical_start_site(b"\x00" * 8 + ret + b"\x00" * 8 + sig)
    assert site is not None
    assert site.return_offset == 8 + len(ret) - 2
    assert site.load_offset == 8 + len(ret) + 8 + len(sig) - 2
