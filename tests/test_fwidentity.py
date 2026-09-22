from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from whip import fwbuild, fwidentity, fwoptical, protocol


BASE = Path(__file__).resolve().parent.parent / "firmware" / "rt02cr-25hz.bin"
CANDIDATE = BASE.with_name("rt02cr-25hz-optical-off-v2-experimental.bin")
EARLIER_CANDIDATE = BASE.with_name("rt02cr-25hz-optical-off-experimental.bin")


@pytest.fixture(scope="module")
def base():
    if not BASE.exists():
        pytest.skip("25 Hz firmware archive not present")
    return BASE.read_bytes()


@pytest.fixture(scope="module")
def candidate(base):
    return fwidentity.validate_images(base)


def samples(image):
    return {site.name: image[site.file_offset:site.file_offset + site.length]
            for site in fwidentity.read_sites()}


def reply(data):
    return bytes(protocol.make_packet(0xCD, data))


def test_archive_mapping_and_actual_instruction_bytes(base):
    assert fwidentity.FILE_TO_ADDRESS == 0x825FB0
    assert fwbuild.PAYLOAD_START + fwidentity.FILE_TO_ADDRESS == 0x826400
    # Independent known addresses and bytes, including raw rate, +/-4 g range
    # and the protected DFU reassembly timer. Addresses are byte addresses.
    expected = {
        0x21D6: (0x828186, "5b480bf053fd0120c0020bf05cfd"),
        0x2244: (0x8281F4, "38703d4804220123d2003f491038"),
        0x6918: (0x82C8C8, "7976b876787400f090fb2046ff38"),
        0x7ED0: (0x82DE80, "c0070bd17d21c900e01ce5f703dc"),
        0xBF04: (0x831EB4, "32200968884705210f20fff79afe"),
        0xCAD0: (0x832A80, "f8bda07900280ed0fff736fafff7"),
        0xF68A: (0x83563A, "08bdf8b50446f4f70afb74490020"),
        0x122FE: (0x8382AE, "08b500216a461170002805d00128"),
    }
    sites = {site.file_offset: site for site in fwidentity.read_sites()}
    for offset, (address, hex_data) in expected.items():
        site = sites[offset]
        assert site.address == address
        assert base[offset:offset + site.length] == bytes.fromhex(hex_data)
        packet = fwidentity.read_packet(site)
        assert packet[:3] == bytes([0xCD, 0x01, 14])
        assert packet[3:7] == address.to_bytes(4, "big")
        assert packet[7:15] == bytes(8)
        assert packet[-1] == protocol.checksum(packet[:-1])


def test_fixed_chunks_cover_ranges_without_gaps_or_overlap():
    sites = fwidentity.read_sites()
    assert len(sites) == 22
    assert len({site.name for site in sites}) == len(sites)
    expected_ranges = [(0x21D6, 20), (0x2244, 16), (0x6918, 24), (0x7ED0, 20),
                       (0xBF04, 16), (0xCAD0, 20), (0xF68A, 80), (0x122FE, 48)]
    expected_offsets = {offset + i for offset, length in expected_ranges for i in range(length)}
    actual_offsets = [site.file_offset + i for site in sites for i in range(site.length)]
    assert len(actual_offsets) == len(set(actual_offsets)) == 244
    assert set(actual_offsets) == expected_offsets
    assert fwoptical.PAYLOAD_CHANGE_ALLOWLIST <= set(actual_offsets)
    assert all(1 <= site.length <= 14 for site in sites)
    assert [site.length for site in sites] == [14, 6, 14, 2, 14, 10, 14, 6, 14, 2,
                                             14, 6, 14, 14, 14, 14, 14, 10,
                                             14, 14, 14, 6]


@pytest.mark.parametrize("length", [0, -1, 15, 256, True, 1.0])
def test_rejects_unsafe_chunk_lengths(length):
    with pytest.raises(ValueError, match="1..14"):
        fwidentity.ReadSite("invalid", 0x2244, length)


@pytest.mark.parametrize("offset", [0, 0x44F, fwoptical.BASE_SIZE - 1, True])
def test_rejects_reads_outside_payload(offset):
    with pytest.raises(ValueError, match="application payload"):
        fwidentity.ReadSite("invalid", offset, 14)


def test_packet_helpers_reject_arbitrary_or_altered_site():
    allowed = fwidentity.read_sites()[0]
    for invented in [replace(allowed, file_offset=allowed.file_offset + 2),
                     replace(allowed, length=allowed.length - 1),
                     replace(allowed, name="made_up")]:
        with pytest.raises(ValueError, match="fixed critical-site"):
            fwidentity.read_packet(invented)
        with pytest.raises(ValueError, match="fixed critical-site"):
            fwidentity.decode_reply(invented, reply(bytes(14)))


def test_all_sampled_bytes_match_both_reviewed_images(base, candidate):
    assert base[0x10:0x30] == candidate[0x10:0x30]  # DIS version cannot distinguish
    for image, expected in [(base, "original25Hz"), (candidate, "optical_off_candidate")]:
        observed = {}
        for site in fwidentity.read_sites():
            payload = image[site.file_offset:site.file_offset + site.length]
            observed[site.name] = fwidentity.decode_reply(site, reply(payload))
        assert fwidentity.classify(base, observed) == expected


@pytest.mark.parametrize("offset", [0x21DC, 0x691E, 0xCAD2, 0xF68C, 0xF690,
                                   0xF6B5, 0xF6D0, 0x1231A])
def test_partial_patch_is_unknown(base, candidate, offset):
    # A candidate with even one edited byte reverted cannot pass the gate.
    assert base[offset] != candidate[offset]
    partial = bytearray(candidate)
    partial[offset] = base[offset]
    assert fwidentity.classify(base, samples(partial)) == "mixed_or_unknown"


@pytest.mark.parametrize("offset", [0x21D6, 0x2248, 0x691C, 0x6922, 0x7ED4,
                                   0xBF0A, 0xCAD0, 0xF68E, 0xF6D4, 0xF6D8, 0x12326])
def test_changed_neighbor_or_protected_instruction_is_unknown(base, candidate, offset):
    altered = bytearray(candidate)
    altered[offset] ^= 1
    assert fwidentity.classify(base, samples(altered)) == "mixed_or_unknown"


@pytest.mark.parametrize("mutation", ["missing", "extra", "short", "long", "nonbytes"])
def test_incomplete_or_malformed_sample_set_is_unknown(base, candidate, mutation):
    observed = samples(candidate)
    first = fwidentity.read_sites()[0].name
    if mutation == "missing":
        del observed[first]
    elif mutation == "extra":
        observed["unrequested"] = b"\x00"
    elif mutation == "short":
        observed[first] = observed[first][:-1]
    elif mutation == "long":
        observed[first] += b"\x00"
    else:
        observed[first] = list(observed[first])
    assert fwidentity.classify(base, observed) == "mixed_or_unknown"


def test_reply_checksum_command_and_framing_are_required():
    site = fwidentity.read_sites()[0]
    valid = reply(bytes(range(14)))
    assert fwidentity.decode_reply(site, valid) == bytes(range(14))
    with pytest.raises(ValueError, match="checksum"):
        fwidentity.decode_reply(site, valid[:-1] + bytes([valid[-1] ^ 1]))
    with pytest.raises(ValueError, match="unexpected command"):
        fwidentity.decode_reply(site, protocol.make_packet(0xCE, bytes(range(14))))
    for truncated in [b"", valid[:-1], valid + b"\x00"]:
        with pytest.raises(ValueError, match="16-byte"):
            fwidentity.decode_reply(site, truncated)


def test_partial_final_chunk_ignores_padding_but_checks_entire_checksum():
    site = next(site for site in fwidentity.read_sites() if site.length == 2)
    packet = reply(b"\x12\x34" + b"\xFF" * 12)
    assert fwidentity.decode_reply(site, packet) == b"\x12\x34"
    damaged = bytearray(packet)
    damaged[14] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        fwidentity.decode_reply(site, damaged)


def test_reference_validation_rejects_changed_base_or_candidate(base, candidate):
    assert fwidentity.validate_images(base, candidate) == candidate
    altered_base = fwbuild.patch(base, {0x2248: 3})
    with pytest.raises(ValueError, match="unrecognized base SHA-256"):
        fwidentity.validate_images(altered_base)
    with pytest.raises(ValueError, match="differs from the strict"):
        fwidentity.validate_images(base, fwbuild.patch(candidate, {0x2248: 3}))
    if CANDIDATE.exists():
        assert fwidentity.validate_images(base, CANDIDATE.read_bytes()) == candidate


def test_disconnect_cleanup_bytes_and_literals_are_sampled(candidate):
    expected_hook = bytes.fromhex("08f0c9fe")
    expected_wrapper = bytes.fromhex(
        "10b5f7f7c4fc054c2078042805d10020207020461030f4f735fb10bdac9c2000"
    )
    observed = {site.file_offset + i: value
                for site in fwidentity.read_sites()
                for i, value in enumerate(candidate[site.file_offset:site.file_offset + site.length])}
    assert bytes(observed[offset] for offset in range(0x691E, 0x6922)) == expected_hook
    assert bytes(observed[offset] for offset in range(0xF6B4, 0xF6D4)) == expected_wrapper
    assert hashlib.sha256(candidate).hexdigest() == fwidentity.CANDIDATE_SHA256


def test_earlier_optical_candidate_is_preserved_but_not_accepted(base):
    if not EARLIER_CANDIDATE.exists():
        pytest.skip("earlier optical-off candidate archive not present")
    earlier = EARLIER_CANDIDATE.read_bytes()
    assert hashlib.sha256(earlier).hexdigest() == (
        "f862e5bb1b65ff43d6133524d20fd82bcbc072bd8a1245a9927367993a213f27"
    )
    assert fwidentity.classify(base, samples(earlier)) == "mixed_or_unknown"
    with pytest.raises(ValueError, match="differs from the strict"):
        fwidentity.validate_images(base, earlier)


def test_builder_output_is_pinned_too(base, candidate, monkeypatch):
    changed = fwbuild.patch(candidate, {0x2248: 3})
    monkeypatch.setattr(fwoptical, "build", lambda data: changed)
    with pytest.raises(ValueError, match="not the pinned optical-off"):
        fwidentity.validate_images(base)


def test_sample_match_does_not_claim_full_image_attestation(base, candidate):
    # An unobserved change cannot be detected by sampling. Preserve this
    # limitation explicitly rather than calling the result full verification.
    altered = bytearray(candidate)
    altered[0x10000] ^= 1
    assert fwidentity.classify(base, samples(altered)) == "optical_off_candidate"
