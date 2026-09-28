import json

import pytest

from probe.rt02_duplicate_control import analyse, analyse_archive
from whip import protocol


def packet(value: int):
    payload = value.to_bytes(2, "big", signed=True) * 3
    return bytes(protocol.make_packet(0xA1, bytes([0x03]) + payload))


def test_duplicate_control_uses_domain_analysis_rate_and_payload_equality():
    records = [(index * 0.04, packet(index // 2)) for index in range(100)]
    result = analyse(records, warmup=0)
    assert result["samples"] == 100
    assert result["notification_rate_hz"] == 25
    assert result["consecutive_duplicate_count"] == 50
    assert result["consecutive_duplicate_fraction"] == 50 / 99
    assert result["gap_median_s"] == pytest.approx(0.04)


def test_duplicate_control_rejects_invalid_packets_and_warmup():
    records = [(index * 0.04, packet(index)) for index in range(100)]
    damaged = bytearray(records[60][1])
    damaged[-1] ^= 1
    records[60] = (records[60][0], bytes(damaged))
    result = analyse(records, warmup=2.0)
    assert result["samples"] == 49
    assert result["consecutive_duplicate_count"] == 0


def test_archive_control_requires_exact_identity_completed_phase_and_cleanup(tmp_path):
    path = tmp_path / "rt02.jsonl"
    rows = [
        {"kind": "device", "device": {
            "address": "fixture", "name": "R02_CC07",
            "hardware": "RT02CR_V3.1", "firmware": "RT02CR_3.12.07_260514",
        }},
        {"kind": "phase", "phase": "optical_stop_mode3", "t": 1.0},
    ]
    for index in range(100):
        rows.append({"kind": "packet", "phase": "optical_stop_mode3",
                     "t": 1 + index * 0.04, "p": packet(index // 2).hex()})
    rows += [
        {"kind": "result", "phase": "optical_stop_mode3",
         "reason": "time_limit", "elapsed_s": 4.0},
        {"kind": "cleanup", "errors": [], "restoration": "verified_000100"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = analyse_archive(path)
    assert result["samples"] == 100
    assert result["consecutive_duplicate_count"] == 50
    assert result["consecutive_duplicate_fraction"] == 50 / 99
    assert result["cleanup"] == "verified_000100"


def test_archive_control_rejects_wrong_family(tmp_path):
    path = tmp_path / "wrong.jsonl"
    path.write_text(json.dumps({"kind": "device", "device": {
        "hardware": "RT12COL_V1.0", "firmware": "RT12COL_1.00.01_260927",
    }}) + "\n")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        analyse_archive(path)
