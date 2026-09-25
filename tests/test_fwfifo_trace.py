"""Actual archived evidence and exact-image execution; MMIO is explicitly fake."""
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess

import pytest

from whip.fwfifo_trace import (
    STOCK_SHA256, V2_SHA256, StockFifoHarness, FifoProofError, audit_capture, image_map,
    native_to_model_counts,
)

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "firmware/research/2026-09-22/captures"


@pytest.fixture(params=["rt02cr-stock-3.12.02.bin", "rt02cr-25hz-optical-off-v2-experimental.bin"],
                ids=["stock", "v2"])
def image(request):
    return (ROOT / "firmware" / request.param).read_bytes()


@pytest.fixture
def h(image):
    pytest.importorskip("unicorn", reason="install requirements-firmware-proof.txt")
    return StockFifoHarness(image)


def test_image_gate_and_poll_initializer(image):
    m = image_map(image)
    assert m["image_sha256"] in (STOCK_SHA256, V2_SHA256)
    assert m["initialized_poll_limit"] == 0xFFFFF
    for changed in (image[:-1], image[:0x1000] + bytes([image[0x1000] ^ 1]) + image[0x1001:]):
        with pytest.raises(ValueError, match="pinned"):
            image_map(changed)


@pytest.mark.parametrize("length", [1, 6, 18, 192])
def test_real_read_chain_copies_complete_payload_with_success_and_restores_abi(h, length):
    payload = bytes((i * 71) & 255 for i in range(length))
    r = h.read(0x3F, payload)
    assert (r["result"], r["cpu_bytes_written"], r["peripheral_bytes_read"]) == (1, length, length)
    assert r["data"] == payload.hex()
    assert h.events == ["read_3f_begin", "mutex_take", "mutex_give", "read_3f_end"]
    assert {h.map[k] for k in ("read", "bus", "transfer", "receive", "abort", "cleanup")} <= h.executed
    assert h.unready_reads == 0


@pytest.mark.parametrize("after", [0, 1, 5, 6, 11, 17])
def test_partial_timeout_is_failure_and_preserves_unwritten_tail(h, after):
    payload = bytes(range(18))
    h.fail_after[0x3F] = after
    r = h.read(0x3F, payload)
    assert (r["result"], r["cpu_bytes_written"], r["peripheral_bytes_read"]) == (0, after, after)
    assert bytes.fromhex(r["data"]) == payload[:after] + b"\xa5" * (18 - after)
    assert h.events.count("mutex_give") == 1


@pytest.mark.parametrize("abort", [1, 2, 4, 8, 0x800, 0x1000])
def test_controller_abort_is_propagated_as_read_failure(h, abort):
    h.fail_after[0x3F] = 5
    h.abort_bits = abort
    r = h.read(0x3F, bytes(range(18)))
    assert r["result"] == 0 and r["cpu_bytes_written"] == 5


def test_mutex_failure_never_touches_sensor_or_destination(h):
    h.mutex_ok = False
    r = h.read(0x3F, b"abcdef")
    assert r["result"] == 0 and r["data"] == "a5" * 6
    assert h.events == ["read_3f_begin", "mutex_take", "read_3f_end"]
    assert h.map["bus"] not in h.executed


@pytest.mark.parametrize("stage", ["tx_empty", "master_busy"])
def test_bus_wait_timeout_is_failure_before_data_transfer(h, stage):
    setattr(h, stage, stage == "master_busy")
    r = h.read(0x3F, b"abcdef")
    assert r["result"] == 0 and r["cpu_bytes_written"] == 0
    assert h.delay_calls == 501
    assert h.map["receive"] not in h.executed


def test_zero_poll_budget_can_report_success_after_reading_unready_mmio(h):
    # Negative precondition witness, NOT a claim that live stock has zero here.
    h.uc.mem_write(h.map["poll"], struct.pack("<I", 0))
    h.fail_after[0x3F] = 0
    r = h.read(0x3F, b"abcdef")
    assert r["result"] == 1 and r["cpu_bytes_written"] == 6
    assert r["peripheral_bytes_read"] == 0 and h.unready_reads == 6
    assert r["data"] == "ee" * 6


@pytest.mark.parametrize("status", [3, 0x83])
def test_original_drain_discards_overflow_and_has_two_separate_mutex_scopes(h, status):
    payload = struct.pack("<9h", 1, 2, 8005, 3, 4, 8006, 5, 6, 8007)
    r = h.drain(status, payload)
    assert [t["register"] for t in r["transactions"]] == [0x0C, 0x3F]
    assert r["transactions"][0]["data"] == f"{status:02x}"
    assert r["producer"] == 18 and r["health"] == 0 and r["buffer"] == payload.hex()
    assert h.events == ["read_0c_begin", "mutex_take", "mutex_give", "read_0c_end",
                        "read_3f_begin", "mutex_take", "mutex_give", "read_3f_end"]


@pytest.mark.parametrize("after", [0, 1, 5, 6, 11, 17])
def test_original_drain_publishes_partial_buffer_despite_real_read_failure(h, after):
    payload = bytes(range(1, 19))
    h.fail_after[0x3F] = after
    r = h.drain(3, payload)
    assert r["transactions"][1]["result"] == 0
    assert r["transactions"][1]["cpu_bytes_written"] == after
    assert r["producer"] == 18 and r["health"] == 0
    assert bytes.fromhex(r["buffer"]) == payload[:after] + bytes(18 - after)


def test_failed_status_read_does_not_call_fifo_or_publish(h):
    h.fail_after[0x0C] = 0
    r = h.drain(3, bytes(range(18)))
    assert len(r["transactions"]) == 1 and not r["producer"] and not r["health"]


def test_execution_and_output_guards_are_active(h):
    with pytest.raises(ValueError, match="supported"):
        h.read(0x3E, b"a")  # This module does not even model configuration probes.
    with pytest.raises(FifoProofError, match="unreviewed execution"):
        h.call(0x450)
    with pytest.raises(FifoProofError, match="budget"):
        h.call(h.map["read"], 0x3F, h.OUTPUT, 6, budget=1)
    with pytest.raises(FifoProofError, match="memory read"):
        h._read(h.uc, 0, h.image_end, 1, 0, None)


@pytest.mark.parametrize("words", [(0, 0, 0), (32767, -32768, -1),
                                   (8005, -8005, 123), (0x1234, -21931, 17)])
def test_actual_stock_encoder_native_axes_match_python_model_decoder(h, words):
    from whip import accel
    native = struct.pack("<hhh", *words)
    packet = h.encode_raw(native)
    expected = b"\xa1\x03" + struct.pack(">hhh", *words) + bytes(7)
    expected += bytes([sum(expected) % 256])
    assert packet == expected
    sample = accel.decode(packet)
    assert (sample.x, sample.y, sample.z) == native_to_model_counts(native) == (words[2], words[0], words[1])
    assert accel.COUNTS_PER_G == 8005.0


def test_encoder_and_native_mapping_preserve_every_signed_bit(h):
    from whip import accel
    rng = random.Random(0x8321)
    for _ in range(128):
        frame = rng.randbytes(6)
        sample = accel.decode(h.encode_raw(frame))
        assert (sample.x, sample.y, sample.z) == native_to_model_counts(frame)


def test_native_frame_refuses_partial_or_multiple_frames():
    for data in (b"", bytes(5), bytes(7), bytes(12), "abcdef"):
        with pytest.raises(ValueError, match="six-byte"):
            native_to_model_counts(data)


def _swift_function(source, prefix):
    start = source.index(prefix)
    opening = source.index("{", start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError("incomplete Swift function")


def test_actual_ios_decode_and_scale_match_native_binding(tmp_path):
    """Compile actual checked-in decoder/checksum functions, not a Python port.

    This validates only input representation/scale, NOT new sensor cadence or
    classifier accuracy. No CoreML inference, simulator or app launch involved.
    """
    compiler = os.environ.get("WHIP_SWIFTC") or shutil.which("swiftc")
    if not compiler:
        pytest.skip("Swift compiler required for actual iOS decoder parity")
    assert Path(compiler).is_absolute() and Path(compiler).is_file(), "Swift compiler must be a resolved file"
    from whip import accel
    protocol = (ROOT / "ios/R02Ring/Health/RingProtocol.swift").read_text()
    inference = (ROOT / "ios/R02Ring/Gesture/GestureInference.swift").read_text()
    assert 'checkpointSHA = "77ed774f03ce3eaddbb8ac29ac8dfc1be32fdd7bef997b56c54157891aff26d5"' in inference
    count_line = next(line.strip() for line in inference.splitlines() if "static let countsPerG =" in line)
    source = "\n".join((
        "import Foundation", "enum RingProtocolError: Error { case invalidPacket }",
        "enum ColmiR02Protocol {",
        _swift_function(protocol, "static func checksum"),
        _swift_function(protocol, "static func isValidPacket"), "}",
        "enum GestureContract {", count_line,
        _swift_function(inference, "static func decode"), "}",
        "let packets = try JSONSerialization.jsonObject(with: FileHandle.standardInput.readDataToEndOfFile()) as! [[UInt8]]",
        "let values = try packets.map { try GestureContract.decode(Data($0)) }",
        "let gs = values.map { $0.map { $0 / GestureContract.countsPerG } }",
        'let result = try JSONSerialization.data(withJSONObject: ["counts": values, "g": gs])',
        "FileHandle.standardOutput.write(result)",
    ))
    fixture, binary = tmp_path / "decode.swift", tmp_path / "decode"
    fixture.write_text(source)
    command = [compiler]
    sdk = os.environ.get("WHIP_SWIFT_SDKROOT")
    if sdk:
        assert Path(sdk).is_absolute() and Path(sdk).is_dir(), "Swift SDK must be a resolved directory"
        command.extend(["-sdk", sdk])
    command.extend(["-module-cache-path", str(tmp_path / "modules"), str(fixture), "-o", str(binary)])
    compiled = subprocess.run(command, capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    rng = random.Random(8321)
    frames = [struct.pack("<hhh", 32767, -32768, -1), struct.pack("<hhh", 0, 8005, -8005)]
    frames += [rng.randbytes(6) for _ in range(128)]
    packets = []
    for frame in frames:
        p = b"\xa1\x03" + struct.pack(">hhh", *struct.unpack("<hhh", frame)) + bytes(7)
        packets.append(list(p + bytes([sum(p) % 256])))
    output = json.loads(subprocess.check_output([str(binary)], input=json.dumps(packets), text=True))
    for frame, counts, gs in zip(frames, output["counts"], output["g"], strict=True):
        assert counts == list(native_to_model_counts(frame))
        assert gs == pytest.approx([v / accel.COUNTS_PER_G for v in counts], rel=1e-15)


def test_real_archive_exposes_25hz_cached_counterexample_and_overflow():
    path = ARCHIVE / "check_1790071705479474000.jsonl"
    r = audit_capture(path)
    assert r["capture_sha256"] == "c89c75edbfe4b98edc1b1f46ff3a608321c0a14b3621f801171c18918589831c"
    phase = next(p for p in r["host_delivery"] if p["phase"] == "streaming")
    assert phase["packets"] == 208 and phase["distinct_xyz"] == 1
    assert 24.9 < phase["host_delivery_hz"] < 25.1
    assert any(s["status"] == 0xA0 and s["overflow"] for s in r["fifo_status_snapshots"])
    assert not r["qualified"] and r["physical_period_ms"] is None
    assert r["model_validation"] == "blocked_no_physical_acquisition_trace"


def test_real_v2_archive_does_not_promote_varying_packets_to_qualified_source():
    r = audit_capture(ARCHIVE / "firmware_validation_1790114546989490000.jsonl")
    phase = next(p for p in r["host_delivery"] if p["phase"] == "tracking_A104_only")
    assert phase["packets"] == 1503 and phase["distinct_xyz"] == 1501
    assert 24.9 < phase["host_delivery_hz"] < 25.1
    assert r["identity_claims"] == [{"classification": "optical_off_candidate",
                                    "scope": "critical_code_sites_only_not_full_image"}]
    assert r["fifo_status_snapshots"] == [] and not r["qualified"]


def test_invalid_capture_is_rejected_not_interpreted(tmp_path):
    p = tmp_path / "broken.jsonl"
    p.write_text("{notjson}\n")
    with pytest.raises(ValueError, match="line 1"):
        audit_capture(p)
    p.write_text("[]\n")
    with pytest.raises(ValueError, match="not an object"):
        audit_capture(p)


def test_bad_packet_evidence_is_reported_and_cannot_change_qualification(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"kind": "packet", "t": 0, "p": "a103"}) + "\n")
    r = audit_capture(p)
    assert r["capture_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert r["errors"] == [{"line": 1, "reason": "invalid_packet"}]
    assert not r["qualified"] and not r["host_delivery"]
