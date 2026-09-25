"""Captured configuration replay + genuine Thumb witnesses, entirely off-ring."""
import hashlib
import json
from pathlib import Path
import struct

import pytest

from whip import fwcapacity as c
from whip import fwplacement as p


FIRMWARE = Path(__file__).resolve().parents[1] / "firmware"
IMAGES = ("rt02cr-stock-3.12.02.bin", "rt02cr-25hz.bin",
          "rt02cr-25hz-optical-off-v2-experimental.bin")


def observed_descriptor_capture():
    """Exact bounded session bytes, not an invented partition fixture.

    Source: data/capacity-20260923-bank0-descriptor/configuration.json
    SHA256 ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7;
    transcript SHA256 9b98a908895249d2987ff675b7ebf340898f67437e3f2f5bc8e6f08a6d666043.
    Copied explicitly so tests do NOT depend on ignored local data. Replaying
    these bytes is not independent device attestation. image_sha256 records the
    partial fingerprint reference, not a complete image read from the ring.
    """
    return {
        "schema": c.SCHEMA, "evidence_kind": "device_capture",
        "session_id": "capacity-20260923-bank0-descriptor", "image_sha256": c.V2_SHA256,
        "windows": [
            {"address": 0x200380, "data_hex": "007c2000007000000074000070380000",
             "sha256": "d181b7378851e44b709578a730fdafcbcf658ee96e9a0ee2a199fba433d30099"},
            {"address": 0x2003E4,
             "data_hex": "002080000080040000a084000000000000a084000040000000e0840000400200"
                         "00000001000080000000000000000000",
             "sha256": "19f636dc558b3e0d11daebb254ecaaf76d5c3a8597e7219063bf55f3715bf32e"},
            {"address": 0x802198,
             "data_hex": "00d08000001000000030800000a000000060820000400200"
                         "00a084000000000000a084000000000000a0840000000000"
                         "00a084000000000000a084000000000000a0840000000000"
                         "00e0800000800100",
             "sha256": "d74c3afddf382c36dd4c566c539d2dcff16a22e0c7f525a9c1a342875cc4e12f"},
        ],
    }


def change_word(capture, window_index, word_index, value):
    window = capture["windows"][window_index]
    data = bytearray.fromhex(window["data_hex"])
    struct.pack_into("<I", data, word_index * 4, value)
    window["data_hex"] = data.hex()
    window["sha256"] = hashlib.sha256(data).hexdigest()


def test_embedded_capture_equals_archived_physical_session():
    raw = (FIRMWARE / "research/2026-09-23/bank0-descriptor/configuration.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7")
    assert json.loads(raw) == observed_descriptor_capture()


@pytest.mark.parametrize("name", IMAGES)
def test_exact_code_route_and_limits(name):
    report = p.audit_image((FIRMWARE / name).read_bytes())
    assert report["code_binding_verified_offline"]
    assert report["oem_init_maximum_vendor_bytes"] == 0x24050
    assert report["oem_maximum_realtek_bytes"] == 147456
    assert report["oem_staging_address"] == 0x84E000
    assert report["image_id"] == 0x2793
    assert not report["live_image_verified"] and not report["flash_authorized"]


def test_actual_descriptor_bytes_provenance_and_stock_margin():
    capture = observed_descriptor_capture()
    report = p.assess_placement((FIRMWARE / IMAGES[0]).read_bytes(), capture)
    assert report["configured_app"] == dict(name="app", address=0x826000,
                                          size=0x24000, end_exclusive=0x84A000)
    assert report["configured_staging"]["address"] == 0x84E000
    assert report["configured_staging"]["end_exclusive"] == 0x872000
    assert report["required_realtek_bytes"] == 137936
    assert report["configured_capacity_margin_bytes"] == 9520
    assert report["descriptor_and_oem_limits_agree"]
    assert report["configured_and_oem_size_fit"]
    assert report["capture_assessment"]["unresolved_flash_declarations"][0]["name"] == "backup1"
    for key in ("transfer_receipt_is_flash_verification", "physical_chip_geometry_verified",
                "boot_copy_recovery_verified", "ram_ownership_verified", "candidate_binary_verified",
                "placement_approved", "flash_authorized"):
        assert report[key] is False
    parts = report["capture_assessment"]["banks"][0]["partitions"]
    assert [(r["name"], r["address"], r["size"]) for r in parts] == [
        ("secure_boot", 0x80D000, 0x1000), ("rom_patch", 0x803000, 0xA000),
        ("app", 0x826000, 0x24000),
        *[(f"app_data{i}", 0x84A000, 0) for i in range(1, 7)],
        ("upperstack", 0x80E000, 0x18000)]


@pytest.mark.parametrize("proposed,fit,margin", [(0x24050, True, 0), (0x24051, False, -1),
                                                (0x27FF, False, 137297),
                                                (0x2800, True, 137296)])
def test_size_is_arithmetic_not_candidate_approval(proposed, fit, margin):
    report = p.assess_placement((FIRMWARE / IMAGES[0]).read_bytes(),
                               observed_descriptor_capture(), proposed_vendor_file_size=proposed)
    assert report["configured_and_oem_size_fit"] is fit
    assert report["configured_capacity_margin_bytes"] == margin
    assert not report["candidate_binary_verified"] and not report["placement_approved"]


def test_missing_descriptor_and_wrong_hash_refused():
    capture = observed_descriptor_capture()
    capture["windows"].pop()
    with pytest.raises(ValueError, match="descriptor"):
        p.assess_placement((FIRMWARE / IMAGES[0]).read_bytes(), capture)
    capture = observed_descriptor_capture()
    capture["windows"][2]["data_hex"] = "00" * 80
    with pytest.raises(ValueError, match="hash"):
        p.assess_placement((FIRMWARE / IMAGES[0]).read_bytes(), capture)


def test_structurally_valid_different_capacity_does_not_match_oem():
    capture = observed_descriptor_capture()
    change_word(capture, 2, 5, 0x23000)  # smaller APP, stays inside bank
    report = p.assess_placement((FIRMWARE / IMAGES[0]).read_bytes(), capture)
    assert not report["descriptor_and_oem_limits_agree"]
    assert not report["configured_and_oem_size_fit"]


@pytest.mark.parametrize("offset", [0, 0x54, 0x841A, 0x84B2, 0x86EC, 0x927A, 138015])
def test_mutated_image_refused_before_emulation(offset):
    raw = bytearray((FIRMWARE / IMAGES[0]).read_bytes())
    raw[offset] ^= 1
    with pytest.raises(ValueError, match="unreviewed image"):
        p.ThumbProof(bytes(raw))


@pytest.fixture(params=IMAGES)
def proof(request):
    pytest.importorskip("unicorn")
    return p.ThumbProof((FIRMWARE / request.param).read_bytes())


def test_actual_init_boundaries_and_uint32_wrap(proof):
    for size in (0, 1, 0x44F, 0x27FF, 0x2800, 138016, 0x2404F, 0x24050,
                 0x24051, 0xFFFFFFFF, 0xFFFF0000):
        r = proof.init_request(size)
        accepted = p.INIT_MINIMUM <= size <= p.INIT_MAXIMUM
        assert r["return_or_boundary_r0"] == (0 if accepted else 1)
        assert r["callbacks"] == [(2, 0 if accepted else 2)]
        assert r["context_state"] == (2 if accepted else 0)
        if accepted:
            assert r["stored_vendor_file_bytes"] == size
            assert r["credited_bytes"] == 0 and r["packet_index"] == 0
        assert not r["calls_not_executed"]


def test_actual_init_all_256_types_and_wrong_length(proof):
    for init_type in range(256):
        r = proof.init_request(138016, init_type=init_type)
        assert r["callbacks"] == [(2, 0 if init_type in (1, 4) else 2)]
    for length in (0, 8, 10, 0xFFFFFFFF):
        assert proof.init_request(138016, packet_length=length)["callbacks"] == [(2, 1)]


@pytest.mark.parametrize("mutex_ok,flash_ok", [(True, True), (True, False), (False, False)])
def test_actual_write_shim_always_returns_zero(proof, mutex_ok, flash_ok):
    r = proof.write_shim(mutex_ok=mutex_ok, flash_ok=flash_ok)
    assert r["return_or_boundary_r0"] == 0
    calls = r["calls_not_executed"]
    writes = [call for call in calls if call[0] == "flash_write_NOT_EXECUTED"]
    assert writes == ([("flash_write_NOT_EXECUTED", 0x84E000, 1024, proof.buffer)] if mutex_ok else [])


@pytest.mark.parametrize("mutex_ok,flash_ok", [(True, True), (True, False), (False, False)])
def test_actual_data_credits_and_acknowledges_even_failed_write(proof, mutex_ok, flash_ok):
    r = proof.continued_data(total=138016, written=1024, payload_length=1024,
                             mutex_ok=mutex_ok, flash_ok=flash_ok)
    assert r["callbacks"] == [(3, 0)]
    assert r["credited_bytes"] == 2048 and r["packet_index"] == 2
    assert r["return_or_boundary_r0"] == 0
    writes = [call for call in r["calls_not_executed"] if call[0] == "flash_write_NOT_EXECUTED"]
    assert writes == ([("flash_write_NOT_EXECUTED", 0x84E400, 1024, proof.buffer)] if mutex_ok else [])


def test_actual_data_can_cross_configured_end_before_receipt_rejects(proof):
    # Synthetic malicious/malformed last chunk; NEVER transmitted. Last known
    # credited position is inside the allowed staging slot; incoming length is
    # protocol-legal (<=1536) but would overshoot the declared file and partition.
    r = proof.continued_data(total=0x24050, written=0x23FF0, payload_length=1024)
    assert r["callbacks"] == [(3, 0)]
    assert r["credited_bytes"] == 0x243F0
    assert ("flash_erase_NOT_EXECUTED", 2, 0x872000) in r["calls_not_executed"]
    assert ("flash_write_NOT_EXECUTED", 0x871FF0, 1024, proof.buffer) in r["calls_not_executed"]
    receipt = proof.receipt_check(total=0x24050, written=r["credited_bytes"])
    assert receipt["callbacks"] == [(4, 1)]  # error arrives after recorded write request


def test_actual_data_may_erase_even_when_total_already_reached(proof):
    r = proof.continued_data(total=0x24050, written=0x24FF0, payload_length=1024)
    assert ("flash_erase_NOT_EXECUTED", 2, 0x873000) in r["calls_not_executed"]
    assert not any(call[0] == "flash_write_NOT_EXECUTED" for call in r["calls_not_executed"])
    assert r["credited_bytes"] == 0x24FF0
    assert r["callbacks"] == [(3, 0)]


def test_actual_receipt_is_byte_counter_only(proof):
    for delta in (-1, 0, 1):
        r = proof.receipt_check(total=138016, written=137936 + delta)
        assert r["callbacks"] == [(4, 0 if delta == 0 else 1)]
        assert not r["calls_not_executed"]  # no checksum/readback/flash at CHECK
    assert proof.receipt_check(total=138016, written=137936, state=2)["callbacks"] == [(4, 3)]


@pytest.mark.parametrize("checksum_ok", [False, True])
def test_actual_end_continues_after_checksum_result(proof, checksum_ok):
    r = proof.end_checksum_boundary(checksum_ok=checksum_ok)
    assert r["context_state"] == 5
    assert r["return_or_boundary_r0"] == int(checksum_ok)
    assert ("checksum_MOCK", 0x84E000) in r["calls_not_executed"]
    assert (("set_ready_NOT_EXECUTED", 0x84E000) in r["calls_not_executed"]) is checksum_ok
    assert 0xFB0 in r["executed_file_offsets"]
    assert not r["flash_authorized"]


def test_actual_boot_resolver_reads_app_descriptor_size_and_pinned_header(proof):
    descriptor = bytes.fromhex(observed_descriptor_capture()["windows"][2]["data_hex"])
    r = proof.resolve_app_header(descriptor)
    assert r["return_or_boundary_r0"] == 0x826401
    assert 0x4FC in r["executed_file_offsets"]  # actual read at bank+0x1ac
    assert ("app_header_valid_MOCK", 0x826000, 0x2793) in r["calls_not_executed"]
    assert not r["flash_authorized"]
    empty = bytearray(descriptor)
    struct.pack_into("<I", empty, 20, 0)  # APP descriptor size word only
    r = proof.resolve_app_header(bytes(empty))
    assert r["return_or_boundary_r0"] == 0
    assert not any(call[0] == "header_address_MOCK" for call in r["calls_not_executed"])
    for kwargs in ({"bank_header_ok": False}, {"app_header_ok": False}):
        assert proof.resolve_app_header(descriptor, **kwargs)["return_or_boundary_r0"] == 0


def test_budget_and_input_types_fail_closed(proof):
    with pytest.raises(p.ProofError, match="budget"):
        proof.init_request(138016, budget=1)
    for value in (True, -1, 2**32, 138016.0):
        with pytest.raises(ValueError):
            proof.init_request(value)
    with pytest.raises(ValueError):
        proof.continued_data(total=138016, written=1024, payload_length=1537)


def test_cpu_memory_loads_and_stores_are_tightly_bounded(proof):
    proof._reset()
    proof.mode = "init"
    # The address is mapped in Unicorn but no packet fixture was authorized.
    with pytest.raises(p.ProofError, match="unexpected load"):
        proof._run(proof.p["init"], r0=proof.PACKET, r1=9)
    for address in (0, p.BIAS - 1, proof.image_end, 0x200000, proof.STACK):
        with pytest.raises(p.ProofError, match="unexpected load"):
            proof._read(proof.uc, 0, address, 1, 0, None)
    for address in (proof.context + 20, proof.buffer, 0x84E000, proof.STACK):
        with pytest.raises(p.ProofError, match="unexpected store"):
            proof._write(proof.uc, 0, address, 1, 0, None)
