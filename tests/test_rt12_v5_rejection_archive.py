"""Pin the physical evidence that permanently revoked RT12COL V5-LP1."""

from __future__ import annotations

import hashlib
from pathlib import Path

from probe.rt02_duplicate_control import analyse
from whip import capture


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-27/rt12-v5-lp1-physical/capture.jsonl"
ARCHIVE_SHA256 = "74ae851af8c68578e94ca8f51e610985b42e472c3fe50acac65c3c6967a5638f"


def test_v5_physical_capture_is_exact_and_recomputes_the_rejection_metric():
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == ARCHIVE_SHA256
    header, records = capture.load_capture(ARCHIVE)
    assert header["device"]["hardware"] == "RT12COL_V1.0"
    assert header["device"]["firmware"] == "RT12COL_1.00.05_260927"

    report = analyse(records, warmup=0)
    assert report["samples"] == 201
    assert report["observed_s"] == 7.995054
    assert report["consecutive_duplicate_count"] == 98
    assert report["consecutive_duplicate_fraction"] == 0.49
    assert report["distinct_payloads"] == 98
    assert 25.01 < report["notification_rate_hz"] < 25.02


def test_v5_duplicate_pattern_is_almost_strict_pairs_not_one_frozen_run():
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

    assert runs.count(2) == 98
    assert runs.count(1) == 5
    assert set(runs) == {1, 2}
