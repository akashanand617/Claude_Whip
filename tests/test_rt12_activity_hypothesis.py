"""Integrity checks for the off-ring RT12 activity/inactivity audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware" / "research" / "2026-09-27" / "rt12-activity-hypothesis"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_activity_hypothesis_archive_pins_exact_inputs_and_off_ring_disposition():
    analysis = json.loads((ARCHIVE / "analysis.json").read_text())

    assert analysis["device_io"] is False
    stock = ROOT / analysis["stock_image"]["path"]
    assert _sha256(stock) == analysis["stock_image"]["sha256"]

    expected_writes = {
        ("0xca0a", "0x35", "0x40"),
        ("0xca16", "0x34", "0x41"),
        ("0xca2e", "0x3f", "0x20"),
    }
    fixed_writes = {
        (item["call_site"], item["register"], item["value"])
        for item in analysis["fixed_stock_writes"]
    }
    assert expected_writes <= fixed_writes

    config = analysis["decoded_active_configuration"]
    assert config["sleep_on"] is True
    assert config["sleep_dur"] == 0
    assert config["wake_threshold_lsb"] == 1
    assert config["interrupts_enable"] is True
    assert analysis["timing_correction"] == {
        "sleep_dur_lsb": "512/ODR",
        "wake_dur_lsb": "1/ODR",
        "programmed_sleep_dur": 0,
        "programmed_wake_dur": 2,
    }

    for capture in analysis["capture_checks"].values():
        assert _sha256(ROOT / capture["path"]) == capture["capture_sha256"]
        assert capture["maximum_run_to_run_delta_g_at_8192_counts_per_g"] < 0.03
        assert capture["singleton_high_motion_alignment"] is False

    v6 = analysis["v6"]
    artifact = ROOT / v6["path"]
    assert _sha256(artifact) == v6["sha256"]
    assert v6["gesture_wake_up_ths"] == "0x01"
    assert v6["stock_restore_wake_up_ths"] == "0x41"
    assert v6["flashed"] is True
    assert v6["bounded_user_authorized_flash"] is True
    assert v6["flash_approved_for_general_install"] is False
    assert v6["identity_verified"] is True
    assert v6["physical_source_freshness_validated"] is True

    source = analysis["v6_source_freshness"]
    assert _sha256(ROOT / source["path"]) == source["sha256"]
    assert source["samples"] == source["distinct_payloads"] == 250
    assert source["consecutive_duplicate_count"] == 0
    assert 24.99 <= source["notification_rate_hz"] <= 25.01
    assert source["broad_motion_threshold_crossed"] is False
    assert source["lease_stopped_stream"] is True

    high_motion = analysis["v6_high_motion"]
    assert _sha256(ROOT / high_motion["path"]) == high_motion["sha256"]
    assert high_motion["samples"] == 250
    assert high_motion["consecutive_duplicate_count"] == 0
    assert high_motion["motion_observed"] is True
    assert high_motion["peak_vector_g"] > 7
    assert high_motion["axis_rail_hits"] > 0

    renewal = analysis["v6_renewal_and_snap"]
    assert _sha256(ROOT / renewal["path"]) == renewal["sha256"]
    assert renewal["samples"] == renewal["distinct_payloads"] == 501
    assert renewal["consecutive_duplicate_count"] == 0
    assert 24.99 <= renewal["notification_rate_hz"] <= 25.02
    assert all(not boundary["duplicate"] for boundary in renewal["renewal_boundaries"])
    assert all(boundary["nearby_duplicates"] == 0 for boundary in renewal["renewal_boundaries"])
    assert renewal["intended_gesture"] == "snap"
    assert renewal["model_event"]["name"] == "flick"

    deployment = json.loads((ARCHIVE / "deployment.json").read_text())
    assert deployment["image_sha256"] == v6["sha256"]
    assert deployment["dfu_check"] == "ok"
    assert deployment["post_reboot_firmware"] == v6["version"]
    assert deployment["source_freshness_tested"] is True
    assert deployment["source_freshness_duplicate_transitions"] == 0
    assert deployment["high_motion_tested"] is True
    assert deployment["lease_renewal_boundary_duplicates"] == 0
    assert deployment["gesture_model_tested"] is True
