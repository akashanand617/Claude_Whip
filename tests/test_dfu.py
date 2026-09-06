import json
from pathlib import Path

import pytest

from whip import dfu

FIRMWARE = Path(__file__).resolve().parent.parent / "firmware"
MANIFEST = FIRMWARE / "upstream-manifest.json"
LOW_LATENCY = FIRMWARE / "rt02cr-low-latency.bin"

pytestmark = pytest.mark.skipif(not LOW_LATENCY.exists(), reason="firmware images not present")


def load_manifest_entry(entry_id: str) -> dict:
    manifest = json.loads(MANIFEST.read_text())
    return next(e for e in manifest["firmware"] if e["id"] == entry_id)


def test_crc16_and_checksum_reproduce_the_published_constants():
    """
    The strongest offline check available: upstream computed these numbers with
    an independent implementation and published them. If ours agree byte for
    byte on a 137 KB image, the framing arithmetic is right -- which matters,
    because the ring uses exactly these to accept or reject the transfer.
    """
    entry = load_manifest_entry("rt02cr-low-latency")
    stats = dfu.firmware_stats(LOW_LATENCY.read_bytes())

    assert stats["crc16"] == entry["crc16"]
    assert stats["checksum16"] == entry["checksum16"]
    assert stats["size"] == entry["size"]


def test_crc16_modbus_known_vector():
    # The canonical CRC-16/Modbus check value for "123456789".
    assert dfu.crc16_modbus(b"123456789") == 0x4B37


def test_frame_layout():
    frame = dfu.build_frame(dfu.CMD_DATA, b"\x01\x02\x03")
    raw = frame.bytes

    assert raw[0] == dfu.MAGIC
    assert raw[1] == dfu.CMD_DATA
    assert raw[2] | (raw[3] << 8) == 3
    assert raw[4] | (raw[5] << 8) == dfu.crc16_modbus(b"\x01\x02\x03")
    assert raw[6:] == b"\x01\x02\x03"


def test_empty_frames_have_no_payload():
    for frame in (dfu.start_frame(), dfu.check_frame(), dfu.end_frame()):
        assert len(frame.bytes) == dfu.HEADER_SIZE
        assert frame.payload == b""


def test_init_frame_carries_size_crc_and_checksum():
    firmware = bytes(range(256)) * 8
    frame = dfu.init_frame(firmware, init_type=4)
    payload = frame.payload

    assert len(payload) == 9
    assert payload[0] == 4
    assert int.from_bytes(payload[1:5], "little") == len(firmware)
    assert int.from_bytes(payload[5:7], "little") == dfu.crc16_modbus(firmware)
    assert int.from_bytes(payload[7:9], "little") == dfu.checksum16(firmware)


def test_init_frame_rejects_unknown_init_type():
    with pytest.raises(ValueError):
        dfu.init_frame(b"\x00" * 16, init_type=2)


def test_data_frame_index_is_one_based():
    """
    Off-by-one here would misplace every chunk. The wire index is 1-based while
    the API is 0-based, which is exactly the kind of mismatch worth pinning.
    """
    firmware = bytes(range(256)) * 8
    frame = dfu.data_frame(firmware, chunk_index=0)
    assert int.from_bytes(frame.payload[0:2], "little") == 1
    assert frame.payload[2:] == firmware[: dfu.CHUNK_SIZE_BYTES]

    frame = dfu.data_frame(firmware, chunk_index=1)
    assert int.from_bytes(frame.payload[0:2], "little") == 2
    assert frame.payload[2:] == firmware[dfu.CHUNK_SIZE_BYTES : 2 * dfu.CHUNK_SIZE_BYTES]


def test_last_chunk_is_short_not_padded():
    firmware = b"\xaa" * (dfu.CHUNK_SIZE_BYTES + 10)
    last = dfu.data_frame(firmware, chunk_index=1)
    assert len(last.payload) == 2 + 10


def test_data_frame_past_the_end_raises():
    with pytest.raises(IndexError):
        dfu.data_frame(b"\x00" * 10, chunk_index=5)


def test_chunk_count_covers_the_real_image():
    firmware = LOW_LATENCY.read_bytes()
    count = dfu.chunk_count(len(firmware))
    assert count == 135  # 137540 / 1024 rounded up

    rebuilt = b"".join(dfu.data_frame(firmware, i).payload[2:] for i in range(count))
    assert rebuilt == firmware, "chunking must reassemble to the original image exactly"


def test_segmentation_preserves_the_frame():
    frame = dfu.data_frame(LOW_LATENCY.read_bytes(), 0)
    segments = dfu.segment(frame, 240)

    assert all(len(s) <= 240 for s in segments)
    assert b"".join(segments) == frame.bytes


def test_segment_rejects_undersized_mtu():
    with pytest.raises(ValueError):
        dfu.segment(dfu.start_frame(), 8)


def test_parse_ok_response():
    reply = dfu.build_frame(dfu.CMD_INIT, b"\x00").bytes
    parsed = dfu.parse_response(reply)
    assert parsed.valid and parsed.ok
    assert parsed.command == dfu.CMD_INIT
    assert parsed.status_name == "ok"


def test_parse_low_battery_response():
    reply = dfu.build_frame(dfu.CMD_INIT, b"\x06").bytes
    parsed = dfu.parse_response(reply)
    assert parsed.valid
    assert not parsed.ok
    assert parsed.status_name == "low-battery"


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"\xbc\x01", "too short"),
        (b"\xaa\x01\x00\x00\x00\x00", "bad magic"),
        (b"\xbc\x01\x09\x00\x00\x00", "length mismatch"),
        (b"\xbc\x01\x01\x00\x00\x00\x05", "bad crc"),
    ],
)
def test_parse_rejects_malformed_frames(data, reason):
    parsed = dfu.parse_response(data)
    assert not parsed.valid, reason
    assert parsed.error
