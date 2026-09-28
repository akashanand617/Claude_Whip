from pathlib import Path

import pytest

from probe import flash
from whip import fwimage

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
LOW_LATENCY = FIRMWARE / "rt02cr-low-latency.bin"
STOCK = FIRMWARE / "rt02cr-stock-3.12.02.bin"
RT12_V5_REVOKED = FIRMWARE / "rt12col-25hz-health-default-gesture-v5-lp1-experimental.bin"
RT12_V4_REVOKED = FIRMWARE / "rt12col-25hz-health-default-gesture-v4-lp2-experimental.bin"
RT12_V7 = FIRMWARE / "rt12col-25hz-health-default-gesture-v7-100hz-comparison-experimental.bin"

pytestmark = pytest.mark.skipif(not LOW_LATENCY.exists(), reason="firmware images not present")

RING_HW = "RT02CR_V3.1"
RING_FW = "RT02CR_3.12.02_260824"


def catalogue_entry():
    return flash.load_catalogue_entry(fwimage.inspect(LOW_LATENCY))


def test_catalogue_entry_found_for_low_latency():
    entry = catalogue_entry()
    assert entry is not None
    assert entry["id"] == "rt02cr-low-latency"


def test_stock_image_is_pinned_by_local_checksums():
    """
    The vendor stock image is the only recovery path for this ring and is in no
    published catalogue. It must still be hash-pinned, or the safety check
    evaporates exactly when it matters.
    """
    entry = flash.load_catalogue_entry(fwimage.inspect(STOCK))
    assert entry is not None
    assert entry["sha256"] == fwimage.inspect(STOCK).sha256


def test_v7_bounded_comparison_is_exactly_pinned_and_not_revoked(capsys):
    image = fwimage.inspect(RT12_V7)
    entry = flash.load_catalogue_entry(image)
    assert entry is not None
    assert entry["sha256"] == image.sha256
    flash.preflight(image, entry, allow_unpinned=False)
    assert "sha256 OK" in capsys.readouterr().out


def test_this_ring_is_compatible_with_the_low_latency_image():
    """
    Our firmware build differs from upstream's base build; compatibility comes
    from the prefix rule, not an exact match. That is the case worth pinning,
    since an exact-match-only reading would wrongly reject this ring.
    """
    entry = catalogue_entry()
    assert RING_FW not in entry["compatibleCurrentFirmware"]
    assert flash.firmware_is_compatible(entry, RING_HW, RING_FW)


def test_incompatible_hardware_is_rejected():
    entry = catalogue_entry()
    assert not flash.firmware_is_compatible(entry, "R02_V3.0", RING_FW)


def test_incompatible_firmware_family_is_rejected():
    entry = catalogue_entry()
    assert not flash.firmware_is_compatible(entry, RING_HW, "RT02CR_3.00.06_240523")


def test_preflight_accepts_the_pinned_image(capsys):
    image = fwimage.inspect(LOW_LATENCY)
    flash.preflight(image, catalogue_entry(), allow_unpinned=False)
    assert "sha256 OK" in capsys.readouterr().out


def test_preflight_rejects_a_tampered_image(tmp_path, capsys):
    data = bytearray(LOW_LATENCY.read_bytes())
    data[9000] ^= 0xFF
    tampered = tmp_path / LOW_LATENCY.name
    tampered.write_bytes(bytes(data))

    entry = catalogue_entry()
    with pytest.raises(flash.FlashAborted, match="sha256 mismatch"):
        flash.preflight(fwimage.inspect(tampered), entry, allow_unpinned=False)
    capsys.readouterr()


def test_preflight_refuses_an_unpinned_image_by_default(tmp_path, capsys):
    unknown = tmp_path / "mystery.bin"
    unknown.write_bytes(LOW_LATENCY.read_bytes())

    with pytest.raises(flash.FlashAborted, match="not in"):
        flash.preflight(fwimage.inspect(unknown), None, allow_unpinned=False)
    capsys.readouterr()


def test_preflight_allows_an_unpinned_image_when_asked(tmp_path, capsys):
    unknown = tmp_path / "mystery.bin"
    unknown.write_bytes(LOW_LATENCY.read_bytes())

    flash.preflight(fwimage.inspect(unknown), None, allow_unpinned=True)
    assert "NOT PINNED" in capsys.readouterr().out


def test_preflight_permanently_rejects_v5_by_hash_even_if_renamed_and_pinned(tmp_path, capsys):
    renamed = tmp_path / "apparently-safe.bin"
    renamed.write_bytes(RT12_V5_REVOKED.read_bytes())
    image = fwimage.inspect(renamed)
    entry = {"id": "local:renamed", "sha256": image.sha256}

    with pytest.raises(flash.FlashAborted, match=r"revoked image:.*49\.0%"):
        flash.preflight(image, entry, allow_unpinned=True)
    capsys.readouterr()


def test_preflight_permanently_rejects_v4_by_hash_even_if_renamed_and_pinned(tmp_path, capsys):
    renamed = tmp_path / "apparently-safe-v4.bin"
    renamed.write_bytes(RT12_V4_REVOKED.read_bytes())
    image = fwimage.inspect(renamed)
    entry = {"id": "local:renamed", "sha256": image.sha256}

    with pytest.raises(flash.FlashAborted, match=r"revoked image:.*49\.4%"):
        flash.preflight(image, entry, allow_unpinned=True)
    capsys.readouterr()


def test_battery_floor_keeps_a_margin_over_the_protocol_minimum():
    """
    The protocol refuses below 20%. We keep headroom over that, but the transfer
    costs well under 1 mAh of a 17 mAh cell, so the floor is a sanity check
    against flashing a nearly-dead ring -- not the thing that makes it safe.
    """
    assert flash.BATTERY_FLOOR_PERCENT >= 40


def test_locally_pinned_entries_have_no_catalogue_rules():
    """
    Our own builds and the vendor stock image are pinned by hash in
    firmware/SHA256SUMS and carry no compatibility metadata. Reading those keys
    unconditionally crashed the flash of a self-built image after the hardware
    check had already passed.
    """
    local = flash.load_catalogue_entry(fwimage.inspect(STOCK))
    assert local is not None
    assert not flash.has_compatibility_rules(local)

    upstream = catalogue_entry()
    assert flash.has_compatibility_rules(upstream)


def test_compatibility_is_only_consulted_when_rules_exist():
    assert flash.has_compatibility_rules({"id": "x"}) is False
    assert flash.has_compatibility_rules(None) is False
