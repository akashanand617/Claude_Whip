"""Offline RT12COL container tests; no BLE or device access."""

import asyncio
import hashlib
import json

import pytest

from whip import fwbuild, fwcapacity_read as cr, fwrt12col as rt, fwrt12col_read as rr, protocol


def synthetic_partition(payload: bytes = bytes(range(64))) -> bytes:
    header = bytearray(rt.NESTED_HEADER_SIZE)
    header[rt.NESTED_FLAGS_OFFSET:rt.NESTED_FLAGS_OFFSET + 2] = (0x0901).to_bytes(2, "little")
    header[rt.NESTED_PAYLOAD_LENGTH_OFFSET:rt.NESTED_PAYLOAD_LENGTH_OFFSET + 4] = len(payload).to_bytes(4, "little")
    header[rt.NESTED_UUID_OFFSET:rt.NESTED_UUID_OFFSET + 16] = rt.REALTEK_IMAGE_UUID
    header[rt.NESTED_PAYLOAD_SHA_OFFSET:rt.NESTED_PAYLOAD_SHA_OFFSET + 32] = hashlib.sha256(payload).digest()
    return bytes(header) + payload


def test_reconstructs_authenticated_stock_ota_and_roundtrips_partition():
    partition = synthetic_partition()
    image = rt.reconstruct_stock_ota(partition)
    assert rt.verify_ota(image, require_ready=False) == []
    assert image[:4] == rt.QRING_MAGIC
    assert image[0x10:0x30].split(b"\0")[0].decode() == rt.STOCK_VERSION
    assert image[0x30:0x50].split(b"\0")[0].decode() == rt.HARDWARE
    assert image[0x50:] == partition
    assert int.from_bytes(image[4:8], "little") == len(partition)
    assert int.from_bytes(image[8:12], "little") == len(partition)


def test_stale_factory_sha_requires_independent_repeat_before_normalization():
    partition = bytearray(synthetic_partition())
    partition[rt.NESTED_PAYLOAD_SHA_OFFSET] ^= 1
    parsed = rt.parse_partition(bytes(partition), require_payload_sha=False)
    assert not parsed.payload_sha_matches
    with pytest.raises(ValueError, match="independently repeated"):
        rt.reconstruct_stock_ota(bytes(partition))
    image = rt.reconstruct_stock_ota(
        bytes(partition), expected_payload_sha256=parsed.payload_sha256
    )
    assert rt.verify_ota(image) == []
    assert image[0x50 + rt.NESTED_PAYLOAD_SHA_OFFSET:
                 0x50 + rt.NESTED_PAYLOAD_SHA_OFFSET + 32] == bytes.fromhex(parsed.payload_sha256)


@pytest.mark.parametrize("fault", ["uuid", "length", "sha", "short"])
def test_partition_validation_fails_closed(fault):
    partition = bytearray(synthetic_partition())
    if fault == "uuid":
        partition[rt.NESTED_UUID_OFFSET] ^= 1
    elif fault == "length":
        partition[rt.NESTED_PAYLOAD_LENGTH_OFFSET:rt.NESTED_PAYLOAD_LENGTH_OFFSET + 4] = (
            rt.APP_PARTITION_SIZE
        ).to_bytes(4, "little")
    elif fault == "sha":
        partition[-1] ^= 1
    else:
        partition = partition[:100]
    with pytest.raises(ValueError):
        rt.parse_partition(bytes(partition))


def test_patch_is_source_checked_refreshes_authentication_and_protects_dfu_site():
    source = rt.reconstruct_stock_ota(synthetic_partition(bytes(0x8000)))
    offset = fwbuild.PAYLOAD_START + 8
    result = rt.patch_ota(
        source,
        {offset: (source[offset], source[offset] ^ 1)},
        version="RT12COL_1.00.00_TEST01",
    )
    assert rt.verify_ota(result) == []
    assert result[offset] == source[offset] ^ 1
    assert result[0x52] & fwbuild.NOT_READY_BIT == 0
    with pytest.raises(ValueError, match="source mismatch"):
        rt.patch_ota(source, {offset: (source[offset] ^ 1, source[offset])}, version="RT12COL_TEST")
    for offset in range(
        rt.DFU_REASSEMBLY_TIMER_OFFSET,
        rt.DFU_REASSEMBLY_TIMER_OFFSET + rt.DFU_REASSEMBLY_TIMER_SIZE,
    ):
        with pytest.raises(ValueError, match="protected DFU"):
            rt.patch_ota(
                source, {offset: (source[offset], source[offset])}, version="RT12COL_TEST"
            )


class FakeTransport:
    def __init__(self, partition, batch_size=1):
        self.partition = partition
        self.writes = []
        self.reader = rr.RT12COLReader(
            self, lambda item: None, timeout=0.01, spacing=0, batch_size=batch_size
        )
        self.mutate_final_header = False
        self.header_windows = 0

    async def write_gatt_char(self, uuid, packet, response):
        assert uuid == protocol.UART_RX_CHAR_UUID and response is False
        assert packet[:2] == b"\xcd\x01" and len(packet) == 16
        length = packet[2]
        address = int.from_bytes(packet[3:7], "big")
        assert (address, length) in self.reader._allowed_reads()
        self.writes.append((address, length))
        offset = address - rt.APP_PARTITION_ADDRESS
        data = self.partition[offset:offset + length]
        if address == rt.APP_PARTITION_ADDRESS:
            self.header_windows += 1
        # Two complete initial header reads contain 148 chunks. The third
        # header begins with chunk 149.
        if self.mutate_final_header and self.header_windows == 3:
            data = bytes([data[0] ^ 1]) + data[1:]
        self.reader.notify(None, bytes(protocol.make_packet(0xCD, data)))


def test_fixed_reader_authenticates_payload_and_closes_every_address_afterward():
    partition = synthetic_partition(bytes(range(128)))
    fake = FakeTransport(partition)
    result, report = asyncio.run(rr.collect_stock_partition(fake.reader))
    assert result == partition
    assert report["payload_sha256"] == hashlib.sha256(bytes(range(128))).hexdigest()
    expected_header_chunks = len(cr.chunks(rt.APP_PARTITION_ADDRESS, rt.NESTED_HEADER_SIZE))
    expected_payload_chunks = len(cr.chunks(rt.APP_PAYLOAD_ADDRESS, 128))
    assert len(fake.writes) == expected_header_chunks * 3 + expected_payload_chunks
    assert fake.reader.closed and fake.reader._allowed_reads() == frozenset()
    with pytest.raises(ValueError):
        asyncio.run(fake.reader.read(rt.APP_PARTITION_ADDRESS, 14))


def test_ordered_batches_reconstruct_the_same_authenticated_partition():
    partition = synthetic_partition(bytes(range(192)))
    fake = FakeTransport(partition, batch_size=8)
    result, report = asyncio.run(rr.collect_stock_partition(fake.reader))
    assert result == partition
    assert report["payload_sha256"] == hashlib.sha256(bytes(range(192))).hexdigest()
    assert fake.reader.closed and not fake.reader.pending_batch


def test_only_known_checksum_valid_statuses_are_quarantined_without_consuming_read_slot():
    events = []
    fake = FakeTransport(synthetic_partition())
    fake.reader.emit = events.append
    for subtype in (0x0C, 0x12):
        accepted = bytes(protocol.make_packet(0x73, bytes([subtype]) + b"private"))
        fake.reader.notify(None, accepted)
        assert not fake.reader.poisoned
    assert fake.reader.quarantined_status_count == 2
    assert [event["status_subtype"] for event in events] == [0x0C, 0x12]
    assert all(event["kind"] == "quarantined_status" and not event["payload_saved"]
               and not event["read_slot_consumed"] for event in events)
    assert all(isinstance(event["monotonic"], float) for event in events)

    for packet in (
        bytes(protocol.make_packet(0x73, b"\x03private")),
        accepted[:-1] + bytes([accepted[-1] ^ 1]),
        bytes(protocol.make_packet(0xA1, b"\x03private")),
    ):
        other = FakeTransport(synthetic_partition())
        other.reader.notify(None, packet)
        assert other.reader.poisoned


def test_resume_parser_and_collector_reuse_only_contiguous_checksummed_prefix():
    partition = synthetic_partition(bytes(range(192)))
    header = partition[:rt.NESTED_HEADER_SIZE]
    payload = partition[rt.NESTED_HEADER_SIZE:]
    rows = []
    for _ in range(2):
        for address, length in cr.chunks(rt.APP_PARTITION_ADDRESS, rt.NESTED_HEADER_SIZE):
            offset = address - rt.APP_PARTITION_ADDRESS
            rows.append({
                "kind": "reply", "address": address, "length": length,
                "packet": bytes(protocol.make_packet(0xCD, header[offset:offset + length])).hex(),
            })
    prefix = payload[:42]
    for address, length in cr.chunks(rt.APP_PAYLOAD_ADDRESS, len(prefix)):
        offset = address - rt.APP_PAYLOAD_ADDRESS
        rows.append({
            "kind": "reply", "address": address, "length": length,
            "packet": bytes(protocol.make_packet(0xCD, prefix[offset:offset + length])).hex(),
        })
    raw = b"\n".join(json.dumps(row).encode() for row in rows) + b"\n"
    recovered_header, recovered_prefix = rr.recover_resume_prefix(raw)
    assert recovered_header == header and recovered_prefix == prefix

    fake = FakeTransport(partition, batch_size=8)
    result, report = asyncio.run(rr.collect_stock_partition(
        fake.reader, resume_header=recovered_header, resume_prefix=recovered_prefix
    ))
    assert result == partition and report["resumed_payload_bytes"] == len(prefix)
    payload_reads = [(address, length) for address, length in fake.writes
                     if address >= rt.APP_PAYLOAD_ADDRESS]
    assert payload_reads[0][0] == rt.APP_PAYLOAD_ADDRESS + len(prefix)


def test_fixed_reader_rejects_header_change_without_retry_or_artifact():
    fake = FakeTransport(synthetic_partition())
    fake.mutate_final_header = True
    with pytest.raises(RuntimeError, match="changed during"):
        asyncio.run(rr.collect_stock_partition(fake.reader))
    assert fake.reader.closed and fake.reader.poisoned


@pytest.mark.parametrize("address", [
    rt.APP_PARTITION_ADDRESS - 1,
    rt.APP_PARTITION_ADDRESS + rt.APP_PARTITION_SIZE,
    0x200000,
    0x40000000,
])
def test_fixed_reader_never_admits_outside_memory(address):
    fake = FakeTransport(synthetic_partition())
    fake.reader.phase = "header"
    with pytest.raises(ValueError):
        asyncio.run(fake.reader.read(address, 1))
    assert fake.writes == []
