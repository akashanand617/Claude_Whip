"""Pin the physical evidence that permanently revoked RT12COL V4-LP2."""

from __future__ import annotations

import hashlib
from pathlib import Path

from probe.rt02_duplicate_control import analyse
from whip import capture


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-27/rt12-v4-lp2-physical/capture.jsonl"
ARCHIVE_SHA256 = "61af77598443f88a614dded8aed63a7e4f0bc066944181fec2c9be782152faea"


def test_v4_physical_capture_is_exact_and_recomputes_the_rejection_metric():
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == ARCHIVE_SHA256
    header, records = capture.load_capture(ARCHIVE)
    assert header["device"]["hardware"] == "RT12COL_V1.0"
    assert header["device"]["firmware"] == "RT12COL_1.00.04_260927"

    report = analyse(records, warmup=0)
    assert report["samples"] == 250
    assert report["observed_s"] == 9.945105000000002
    assert report["consecutive_duplicate_count"] == 123
    assert report["consecutive_duplicate_fraction"] == 123 / 249
    assert report["distinct_payloads"] == 124
    assert 25.03 < report["notification_rate_hz"] < 25.04


def test_v4_duplicate_pattern_is_almost_strict_pairs_not_one_frozen_run():
    _, records = capture.load_capture(ARCHIVE)
    payloads = [
        packet[2:8] for _, packet in records
        if len(packet) == 16 and packet[:2] == b"\xa1\x03"
    ]
    runs: list[int] = []
    start = 0
    while start < len(payloads):
        end = start + 1
        while end < len(payloads) and payloads[end] == payloads[start]:
            end += 1
        runs.append(end - start)
        start = end

    assert runs.count(2) == 123
    assert runs.count(1) == 4
    assert set(runs) == {1, 2}
