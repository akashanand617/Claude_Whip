"""Fixed RT12COL installed-application acquisition over legacy CD01.

CD01 reads memory but also runs stock connection/timer bookkeeping.  This plan
is intended only for an idle, exclusive connection.  It admits exactly the
known 144 KiB application partition, first authenticates two identical nested
headers, reads only the header-declared bounded payload, verifies its SHA-256,
then rechecks the header.  No sensor, setting, flash-write or DFU command exists
here, and no transport retry is permitted because CD replies carry no request
identifier.
"""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
import json
import time

from whip import fwcapacity_read as cr, fwrt12col, protocol


SCHEMA = "whip.rt12col.stock-partition.v1"
QUARANTINED_STATUS_SUBTYPES = frozenset((0x0C, 0x12))
MAX_QUARANTINED_STATUS = 64


class RT12COLReader(cr.CapacityReader):
    def __init__(self, *args, batch_size: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        if type(batch_size) is not int or not 1 <= batch_size <= 32:
            raise ValueError("RT12COL batch size must be 1..32")
        self.batch_size = batch_size
        self.phase: str | None = None
        self.payload_length: int | None = None
        self.closed = False
        self.quarantined_status_count = 0
        self.pending_batch = deque()
        self._header_reads = frozenset(cr.chunks(
            fwrt12col.APP_PARTITION_ADDRESS, fwrt12col.NESTED_HEADER_SIZE
        ))
        self._payload_reads: frozenset[tuple[int, int]] = frozenset()

    def select_payload(self, length: int) -> None:
        if self.payload_length is not None:
            raise RuntimeError("RT12COL payload phase already selected")
        maximum = fwrt12col.APP_PARTITION_SIZE - fwrt12col.NESTED_HEADER_SIZE
        if type(length) is not int or not 16 <= length <= maximum:
            raise ValueError("RT12COL payload length is outside the fixed application partition")
        self.payload_length = length
        self._payload_reads = frozenset(cr.chunks(fwrt12col.APP_PAYLOAD_ADDRESS, length))

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        if self.phase == "header":
            return self._header_reads
        if self.phase == "payload":
            return self._payload_reads
        return frozenset()

    def _fail_batch(self, exc: BaseException) -> None:
        self.poisoned = True
        while self.pending_batch:
            _, _, future = self.pending_batch.popleft()
            if not future.done():
                future.set_exception(exc)

    def notify(self, _sender, raw):
        packet = bytes(raw)
        metadata = protocol.notification_metadata(packet)
        if (metadata["command"] == 0x73 and metadata["checksum_valid"]
                and metadata["status_subtype"] in QUARANTINED_STATUS_SUBTYPES):
            self.quarantined_status_count += 1
            self.emit({
                "kind": "quarantined_status",
                **metadata,
                "monotonic": time.monotonic(),
                "read_slot_consumed": False,
            })
            if self.quarantined_status_count > MAX_QUARANTINED_STATUS:
                self._fail_batch(RuntimeError("RT12COL status-notification budget exceeded"))
            return
        if not packet or packet[0] != 0xCD:
            self.emit({
                "kind": "unexpected_notification",
                **metadata,
                "monotonic": time.monotonic(),
            })
            self._fail_batch(RuntimeError("non-diagnostic traffic; abort RT12COL read"))
            return
        if not self.pending_batch:
            self.poisoned = True
            return
        address, length, future = self.pending_batch.popleft()
        if len(packet) != 16 or protocol.checksum(packet[:-1]) != packet[-1]:
            self._fail_batch(RuntimeError("invalid RT12COL diagnostic reply"))
            if not future.done():
                future.set_exception(RuntimeError("invalid RT12COL diagnostic reply"))
            return
        self.emit({
            "kind": "reply",
            "address": address,
            "length": length,
            "packet": packet.hex(),
            "monotonic": time.monotonic(),
        })
        if not future.done():
            future.set_result(packet[1:1 + length])

    async def read_batch(self, requests) -> tuple[bytes, ...]:
        requests = tuple(requests)
        if not requests or len(requests) > self.batch_size:
            raise ValueError("invalid RT12COL read batch")
        if self.poisoned or self.pending_batch or self.pending is not None:
            self.poisoned = True
            raise RuntimeError("RT12COL diagnostic session ambiguous or busy")
        allowed = self._allowed_reads()
        for address, length in requests:
            if (type(address) is not int or type(length) is not int
                    or (address, length) not in allowed):
                raise ValueError("request outside fixed RT12COL application read plan")
        loop = asyncio.get_running_loop()
        futures = []
        packets = []
        for address, length in requests:
            future = loop.create_future()
            futures.append(future)
            self.pending_batch.append((address, length, future))
            packet = bytes(protocol.make_packet(
                0xCD, bytes([1, length]) + address.to_bytes(4, "big")
            ))
            packets.append(packet)
            self.emit({
                "kind": "request",
                "address": address,
                "length": length,
                "packet": packet.hex(),
                "monotonic": time.monotonic(),
                "batch_size": len(requests),
            })
        try:
            async with asyncio.timeout(self.timeout * len(requests)):
                for packet in packets:
                    await self.client.write_gatt_char(
                        protocol.UART_RX_CHAR_UUID, packet, response=False
                    )
                result = await asyncio.gather(*futures)
            await asyncio.sleep(self.spacing)
            if self.poisoned or self.pending_batch:
                raise RuntimeError("incomplete, duplicate or unsolicited RT12COL batch")
            return tuple(result)
        except BaseException as exc:
            self._fail_batch(exc)
            for future in futures:
                if not future.done():
                    future.cancel()
            raise

    async def read(self, address, length):
        return (await self.read_batch(((address, length),)))[0]

    async def window(self, address, length):
        requests = cr.chunks(address, length)
        result = []
        for offset in range(0, len(requests), self.batch_size):
            result.extend(await self.read_batch(requests[offset:offset + self.batch_size]))
        return b"".join(result)


def _decode_transcript_reply(row: dict) -> bytes:
    try:
        packet = bytes.fromhex(row["packet"])
        length = row["length"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("malformed RT12COL transcript reply") from exc
    if (type(length) is not int or not 1 <= length <= 14 or len(packet) != 16
            or packet[0] != 0xCD or protocol.checksum(packet[:-1]) != packet[-1]):
        raise ValueError("invalid RT12COL transcript reply")
    return packet[1:1 + length]


def recover_resume_prefix(raw: bytes) -> tuple[bytes, bytes]:
    """Recover only a contiguous, checksummed prefix from an aborted transcript."""
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid RT12COL transcript JSON") from exc
    header_requests = cr.chunks(fwrt12col.APP_PARTITION_ADDRESS, fwrt12col.NESTED_HEADER_SIZE)
    header_rows = [
        row for row in rows
        if row.get("kind") == "reply"
        and fwrt12col.APP_PARTITION_ADDRESS <= row.get("address", -1) < fwrt12col.APP_PAYLOAD_ADDRESS
    ]
    needed = len(header_requests) * 2
    if len(header_rows) < needed:
        raise ValueError("transcript lacks two complete RT12COL headers")
    headers = []
    for pass_index in range(2):
        selected = header_rows[pass_index * len(header_requests):(pass_index + 1) * len(header_requests)]
        if [(row.get("address"), row.get("length")) for row in selected] != list(header_requests):
            raise ValueError("transcript RT12COL header sequence is not exact")
        headers.append(b"".join(_decode_transcript_reply(row) for row in selected))
    if headers[0] != headers[1]:
        raise ValueError("transcript RT12COL headers differ")
    length = fwrt12col.nested_payload_length(headers[0])

    prefix = bytearray()
    expected = fwrt12col.APP_PAYLOAD_ADDRESS
    end = expected + length
    for row in rows:
        if row.get("kind") != "reply":
            continue
        address = row.get("address", -1)
        if not fwrt12col.APP_PAYLOAD_ADDRESS <= address < end:
            continue
        if address != expected:
            if address < expected:
                raise ValueError("duplicate or reordered payload reply in RT12COL transcript")
            break
        data = _decode_transcript_reply(row)
        wanted = min(14, end - expected)
        if row.get("length") != wanted or len(data) != wanted:
            raise ValueError("unexpected RT12COL payload reply length")
        prefix.extend(data)
        expected += wanted
    if not prefix:
        raise ValueError("transcript has no contiguous RT12COL payload prefix")
    return headers[0], bytes(prefix)


async def collect_stock_partition(
    reader: RT12COLReader,
    *,
    resume_header: bytes | None = None,
    resume_prefix: bytes = b"",
) -> tuple[bytes, dict]:
    if not isinstance(reader, RT12COLReader):
        raise ValueError("the fixed RT12COL reader is required")
    if reader.closed or reader.phase is not None:
        raise RuntimeError("RT12COL acquisition session already used")
    try:
        reader.phase = "header"
        first = await reader.window(
            fwrt12col.APP_PARTITION_ADDRESS, fwrt12col.NESTED_HEADER_SIZE
        )
        second = await reader.window(
            fwrt12col.APP_PARTITION_ADDRESS, fwrt12col.NESTED_HEADER_SIZE
        )
        if first != second:
            raise RuntimeError("RT12COL nested header changed across repeated reads")
        if resume_header is not None and first != resume_header:
            raise RuntimeError("RT12COL nested header differs from resume transcript")
        length = fwrt12col.nested_payload_length(first)
        if not isinstance(resume_prefix, bytes) or len(resume_prefix) > length:
            raise ValueError("invalid RT12COL resume prefix")
        if resume_prefix and len(resume_prefix) != length and len(resume_prefix) % 14:
            raise ValueError("RT12COL resume prefix does not end on a complete read chunk")
        reader.select_payload(length)

        reader.phase = "payload"
        payload_chunks = cr.chunks(
            fwrt12col.APP_PAYLOAD_ADDRESS + len(resume_prefix), length - len(resume_prefix)
        )
        payload_parts = [resume_prefix]
        for offset in range(0, len(payload_chunks), reader.batch_size):
            batch = payload_chunks[offset:offset + reader.batch_size]
            payload_parts.extend(await reader.read_batch(batch))
            completed = offset + len(batch)
            absolute_bytes = len(resume_prefix) + min(completed * 14, length - len(resume_prefix))
            absolute_chunks = (absolute_bytes + 13) // 14
            prior_chunks = (len(resume_prefix) + min(offset * 14, length - len(resume_prefix)) + 13) // 14
            if absolute_chunks // 512 != prior_chunks // 512 or completed == len(payload_chunks):
                reader.emit({
                    "kind": "progress",
                    "chunks": absolute_chunks,
                    "total_chunks": len(cr.chunks(fwrt12col.APP_PAYLOAD_ADDRESS, length)),
                    "bytes": absolute_bytes,
                    "total_bytes": length,
                    "resumed_bytes": len(resume_prefix),
                })
        payload = b"".join(payload_parts)

        reader.phase = "header"
        final = await reader.window(
            fwrt12col.APP_PARTITION_ADDRESS, fwrt12col.NESTED_HEADER_SIZE
        )
        if final != first:
            raise RuntimeError("RT12COL nested header changed during payload acquisition")

        partition = first + payload
        parsed = fwrt12col.parse_partition(partition, require_payload_sha=False)
        report = {
            "schema": SCHEMA,
            "hardware": fwrt12col.HARDWARE,
            "firmware": fwrt12col.STOCK_VERSION,
            "address": fwrt12col.APP_PARTITION_ADDRESS,
            "bytes": len(partition),
            "payload_bytes": parsed.payload_length,
            "partition_sha256": hashlib.sha256(partition).hexdigest(),
            "payload_sha256": parsed.payload_sha256,
            "stored_payload_sha256": parsed.stored_payload_sha256,
            "header_payload_sha_matches": parsed.payload_sha_matches,
            "headers_equal": True,
            "quarantined_status_notifications": reader.quarantined_status_count,
            "resumed_payload_bytes": len(resume_prefix),
            "flashing": False,
            "sensor_commands": False,
            "retries": False,
        }
        reader.emit({"kind": "authenticated_partition", **report})
        return partition, report
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader.phase = None
        reader.closed = True
