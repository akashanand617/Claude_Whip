"""Synthetic parser fixtures and exact-image CD instruction witnesses, no BLE."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct

import pytest

from whip import fwcapacity as c


FIRMWARE = Path(__file__).resolve().parents[1] / "firmware"
IMAGES = ("rt02cr-25hz.bin", "rt02cr-25hz-optical-off-v2-experimental.bin")


def window(address, data):
    return {"address": address, "data_hex": data.hex(), "sha256": hashlib.sha256(data).hexdigest()}


def config_fixture():
    """Invented map solely for parser tests; NEVER a measurement of this ring."""
    ram = struct.pack("<4I", 0x207C00, 0x7000, 0x7400, 0)
    flash = struct.pack("<12I", 0x802000, 0x48000, 0x84A000, 0, 0x84A000, 0x4000,
                        0x84E000, 0x24000, 0, 0, 0, 0)
    descriptors = struct.pack("<20I", 0x80D000, 0x1000, 0x803000, 0xA000,
                              0x826000, 0x24000, *([0, 0] * 6), 0x80E000, 0x18000)
    return {"schema": c.SCHEMA, "evidence_kind": "synthetic_fixture",
            "session_id": "parser-fixture-NOT-ring", "image_sha256": c.V2_SHA256,
            "windows": [window(c.RAM_CONFIG_ADDRESS, ram),
                        window(c.FLASH_CONFIG_ADDRESS, flash),
                        window(0x802198, descriptors)]}


def observed_configuration():
    """Exact non-secret bytes from the separately recorded 2026-09-23 session.

    Original configuration JSON SHA256:
    f8caf08fecc769c4652c57da7db5e1b385dd6223468cbedefbc9d8f705dd9d14.
    Replay here is offline; the test does not independently attest the device.
    """
    return {"schema": c.SCHEMA, "evidence_kind": "device_capture",
            "session_id": "capacity-20260923-idle-config", "image_sha256": c.V2_SHA256,
            "windows": [window(c.RAM_CONFIG_ADDRESS, bytes.fromhex(
                "007c2000007000000074000070380000")),
                window(c.FLASH_CONFIG_ADDRESS, bytes.fromhex(
                    "002080000080040000a084000000000000a084000040000000e0840000400200"
                    "00000001000080000000000000000000"))]}


def replace_word(capture, index, word, value):
    w = capture["windows"][index]
    data = bytearray.fromhex(w["data_hex"])
    struct.pack_into("<I", data, word * 4, value)
    capture["windows"][index] = window(w["address"], bytes(data))


def test_synthetic_fit_is_never_device_evidence_or_authorization():
    report = c.analyze_capture(config_fixture(), vendor_file_size=138016)
    assert report["minimum_partition_bytes"] == 0x21AD0
    assert report["banks"][0]["configured_app_fit"] is True
    assert report["banks"][0]["configured_app_margin_bytes"] == 0x24000 - 0x21AD0
    assert report["banks_describing_known_app_base"] == ["bank0"]
    assert report["ram_configuration"]["matches_nominal_stock_reservation"]
    assert report["ram_configuration"]["free_bytes_proven"] is None
    for key in ("physical_evidence_verified", "live_image_verified", "staging_route_verified",
                "flash_chip_capacity_verified", "placement_approved", "flash_authorized"):
        assert report[key] is False


def test_observed_bytes_have_expected_pinned_window_hashes():
    capture = observed_configuration()
    assert [w["sha256"] for w in capture["windows"]] == [
        "d181b7378851e44b709578a730fdafcbcf658ee96e9a0ee2a199fba433d30099",
        "19f636dc558b3e0d11daebb254ecaaf76d5c3a8597e7219063bf55f3715bf32e"]


def test_observed_override_is_quarantined_not_counted_as_physical_flash():
    capture = observed_configuration()
    data = bytes.fromhex(capture["windows"][1]["data_hex"])
    with pytest.raises(ValueError, match="backup1"):
        c.parse_flash_config(data)  # strict original API is NOT loosened
    report = c.analyze_capture(capture, vendor_file_size=138016)
    regions = {r["name"]: r for r in report["flash_regions"]}
    assert regions["bank0"] == {"name": "bank0", "address": 0x802000,
                                "size": 0x48000, "end_exclusive": 0x84A000}
    assert regions["ota_tmp"]["size"] == 0x24000
    assert regions["ota_tmp"]["end_exclusive"] == 0x872000
    assert "backup1" not in regions
    assert report["unresolved_flash_declarations"][0]["declared_size"] == 0x800000
    assert not report["complete_flash_map_validated"]
    assert not report["flash_chip_capacity_verified"]
    assert not report["flash_authorized"]
    assert report["banks"] == [] and report["missing_descriptor_banks"] == ["bank0"]
    assert report["ram_configuration"]["buffer_heap_bytes"] == 0x3870
    assert report["ram_configuration"]["matches_nominal_stock_reservation"]


@pytest.mark.parametrize("word,value", [(8, 0x1001000), (9, 0x7FF000),
                                        (9, 0x801000), (10, 0x1001000)])
def test_unknown_override_variants_still_refused(word, value):
    capture = observed_configuration()
    replace_word(capture, 1, word, value)
    with pytest.raises(ValueError):
        c.analyze_capture(capture, vendor_file_size=138016)


def test_override_does_not_mask_other_partition_errors_or_approve_new_reads():
    capture = observed_configuration()
    replace_word(capture, 1, 4, 0x840000)
    with pytest.raises(ValueError, match="overlap"):
        c.analyze_capture(capture, vendor_file_size=138016)
    capture = observed_configuration()
    capture["windows"].append(window(0x1000198, bytes(80)))
    with pytest.raises(ValueError, match="unreviewed memory"):
        c.analyze_capture(capture, vendor_file_size=138016)
    capture = observed_configuration()
    capture["image_sha256"] = c.STOCK_SHA256
    with pytest.raises(ValueError, match="backup1"):
        c.analyze_capture(capture, vendor_file_size=138016)


def test_claiming_device_provenance_cannot_promote_fixture_to_verified():
    capture = config_fixture()
    capture["evidence_kind"] = "device_capture"
    report = c.analyze_capture(capture, vendor_file_size=138016)
    assert report["declared_evidence_kind"] == "device_capture"
    assert not report["physical_evidence_verified"]
    assert not report["live_image_verified"]
    assert not report["flash_authorized"]


def test_exact_capacity_boundary_is_arithmetic_only():
    fixture = config_fixture()
    at_limit = c.analyze_capture(fixture, vendor_file_size=0x24050)
    above = c.analyze_capture(fixture, vendor_file_size=0x24051)
    assert at_limit["banks"][0]["configured_app_fit"]
    assert at_limit["banks"][0]["configured_app_margin_bytes"] == 0
    assert not above["banks"][0]["configured_app_fit"]
    assert above["banks"][0]["configured_app_margin_bytes"] == -1
    assert not above["ota_tmp_configured_fit"]
    assert not at_limit["flash_authorized"]


@pytest.mark.parametrize("size", [True, -1, 0x44F, 2**32, 137540.0, "137540"])
def test_invalid_candidate_size(size):
    with pytest.raises(ValueError):
        c.minimum_partition_bytes(size)


def test_missing_descriptors_remains_incomplete_and_does_not_guess():
    fixture = config_fixture()
    fixture["windows"].pop()
    report = c.analyze_capture(fixture, vendor_file_size=138016)
    assert report["missing_descriptor_banks"] == ["bank0"]
    assert report["banks"] == []
    assert report["banks_describing_known_app_base"] == []
    assert not report["flash_authorized"]


@pytest.mark.parametrize("key,value", [("schema", "v2"), ("image_sha256", "0" * 64),
                                       ("image_sha256", []), ("evidence_kind", "verified"),
                                       ("session_id", ""), ("session_id", "../secret"),
                                       ("session_id", 123), ("windows", {})])
def test_invalid_capture_metadata(key, value):
    fixture = config_fixture()
    fixture[key] = value
    with pytest.raises(ValueError):
        c.analyze_capture(fixture, vendor_file_size=138016)


def test_unknown_fields_cannot_smuggle_authorization_or_full_otp():
    fixture = config_fixture()
    fixture["flash_authorized"] = True
    with pytest.raises(ValueError, match="unexpected"):
        c.analyze_capture(fixture, vendor_file_size=138016)
    fixture = config_fixture()
    fixture["windows"].append(window(0x200164, bytes(64)))
    with pytest.raises(ValueError, match="unreviewed memory"):
        c.analyze_capture(fixture, vendor_file_size=138016)


@pytest.mark.parametrize("length", [0, 15, 17, 81, 1024])
def test_narrow_window_sizes_only(length):
    fixture = config_fixture()
    fixture["windows"][0] = window(c.RAM_CONFIG_ADDRESS, bytes(length))
    with pytest.raises(ValueError):
        c.analyze_capture(fixture, vendor_file_size=138016)


def test_duplicate_address_hash_mismatch_and_noncanonical_hex():
    fixture = config_fixture()
    fixture["windows"].append(deepcopy(fixture["windows"][0]))
    with pytest.raises(ValueError, match="duplicate window"):
        c.analyze_capture(fixture, vendor_file_size=138016)
    fixture = config_fixture()
    fixture["windows"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash mismatch"):
        c.analyze_capture(fixture, vendor_file_size=138016)
    fixture = config_fixture()
    fixture["windows"][0]["data_hex"] = "AA " * 16
    with pytest.raises(ValueError, match="canonical"):
        c.analyze_capture(fixture, vendor_file_size=138016)


@pytest.mark.parametrize("word,value", [(0, 0x40000000), (0, 0x207C01), (1, 0),
                                        (1, 0xFFFFFFFF), (2, 0x18000), (3, 0x18004)])
def test_bad_ram_extents(word, value):
    fixture = config_fixture()
    replace_word(fixture, 0, word, value)
    with pytest.raises(ValueError):
        c.analyze_capture(fixture, vendor_file_size=138016)


@pytest.mark.parametrize("word,value", [(0, 0x40000000), (1, 0xFFFFF000), (0, 0x802001),
                                        (1, 0x48001), (4, 0x840000), (7, 0xFFFFFFFF),
                                        (8, 0x200000)])
def test_bad_flash_extents_overflow_alias_and_overlap(word, value):
    fixture = config_fixture()
    replace_word(fixture, 1, word, value)
    with pytest.raises(ValueError):
        c.analyze_capture(fixture, vendor_file_size=138016)


@pytest.mark.parametrize("word,value", [(4, 0x801000), (4, 0x802000), (5, 0),
                                        (5, 0xFFFFF000), (0, 0x803000), (18, 0x825000)])
def test_invalid_descriptor_parent_header_overflow_and_overlap(word, value):
    fixture = config_fixture()
    replace_word(fixture, 2, word, value)
    with pytest.raises(ValueError):
        c.analyze_capture(fixture, vendor_file_size=138016)


def test_no_descriptors_for_zero_size_bank_or_unvalidated_pointer():
    fixture = config_fixture()
    fixture["windows"][2]["address"] = 0x84A198
    with pytest.raises(ValueError, match="unreviewed memory"):
        c.analyze_capture(fixture, vendor_file_size=138016)
    with pytest.raises(ValueError, match="absent bank"):
        c.parse_bank_descriptors(bytes(80), c.Region("bank1", 0x84A000, 0))


def test_full_descriptor_area_includes_upperstack_not_just_app():
    fixture = config_fixture()
    report = c.analyze_capture(fixture, vendor_file_size=138016)
    upper = report["banks"][0]["partitions"][-1]
    assert upper == {"name": "upperstack", "address": 0x80E000, "size": 0x18000,
                     "end_exclusive": 0x826000}
    bank = c.Region("bank0", 0x802000, 0x48000)
    with pytest.raises(ValueError, match="80 bytes"):
        c.parse_bank_descriptors(bytes(72), bank)


def test_json_loader_refuses_duplicates_nonfinite_oversize_and_nonobject():
    assert c.load_capture(json.dumps(config_fixture())) == config_fixture()
    for text in ('{"schema":1,"schema":2}', '{"x":NaN}', '[]', ' ' * 8193):
        with pytest.raises(ValueError):
            c.load_capture(text)


@pytest.mark.parametrize("name", IMAGES)
def test_exact_image_cd_map(name):
    image = (FIRMWARE / name).read_bytes()
    audit = c.audit_cd_image(image)
    assert audit["prelude_file"] == 0x7EEE
    assert audit["unconditional_flag_ram"] == 0x20A664
    assert audit["rom_uuid"] == "f94c6b7e11c5eb118282f74a0c0cef5b"
    assert not audit["side_effect_free"]
    assert not audit["hardware_session_authorized"]


@pytest.mark.parametrize("offset", [0, 0x4B16, 0x5658, 0x7EEE, 0x8130, 0x94CC, 137539])
def test_cd_audit_rejects_changed_image_before_emulation(offset):
    image = bytearray((FIRMWARE / IMAGES[0]).read_bytes())
    image[offset] ^= 1
    with pytest.raises(ValueError, match="exact pinned"):
        c.CDReadHarness(bytes(image))
    with pytest.raises(ValueError, match="exact pinned"):
        c.audit_cd_image(bytes(image))


def test_stock_and_retired_v1_are_not_misidentified_as_reviewed_v2():
    for name in ("rt02cr-stock-3.12.02.bin", "rt02cr-25hz-optical-off-experimental.bin"):
        with pytest.raises(ValueError, match="exact pinned"):
            c.audit_cd_image((FIRMWARE / name).read_bytes())


def test_reviewed_cd_regions_and_literals_are_identical_between_base_and_v2():
    base, v2 = [(FIRMWARE / n).read_bytes() for n in IMAGES]
    for low, high in ((0x3EEC, 0x3F06), (0x4B16, 0x4B9C), (0x564A, 0x59E8),
                      (0x5DD4, 0x5DD8), (0x78AA, 0x78FE), (0x7ECA, 0x7F16),
                      (0x8130, 0x8134), (0x9276, 0x9310), (0x94CC, 0x94D2),
                      (0x9568, 0x957C)):
        assert base[low:high] == v2[low:high]


@pytest.fixture(params=IMAGES)
def harness(request):
    pytest.importorskip("unicorn")
    return c.CDReadHarness((FIRMWARE / request.param).read_bytes())


def test_actual_cd_path_all_256_states(harness):
    for state in range(256):
        result = harness.run(state)
        assert result["writes"] == [(0x20A664, 1)]
        assert result["calls_not_executed"] == ([0x7ECA, 0x9276] if state in (2, 3) else [])
        reply = result["reply"]
        assert reply[:15] == b"\xcd" + bytes(range(14))
        assert reply[-1] == sum(reply[:-1]) % 256
        assert {0x5658, 0x7EF0, 0x59CA, 0x4B68} <= set(result["executed"])


def test_actual_cd_copy_clamps_all_256_requested_lengths(harness):
    for length in range(256):
        result = harness.run(0, length=length)
        n = min(length, 14)
        assert result["reply"][1:15] == bytes(range(n)) + bytes(14 - n)
        assert result["writes"] == [(0x20A664, 1)]


def test_cd_proof_instruction_budget_and_input_types(harness):
    with pytest.raises(c.CDProofError, match="budget"):
        harness.run(2, budget=1)
    for value in (True, -1, 256):
        with pytest.raises(ValueError):
            harness.run(value)


def test_actual_startup_writes_exact_observed_opaque_backup_declaration(harness):
    result = harness.startup_backup_declaration()
    assert result["writes"] == [(0x200404, 0x01000000), (0x200408, 0x00800000)]
    assert result["executed"] == list(range(0x6F2, 0x700, 2))
    assert not result["physical_capacity_verified"]
    # Modes do not silently leak into later CD witnesses.
    assert harness.run(0)["writes"] == [(0x20A664, 1)]
