"""Guarded Linux raw-HCI recovery primitives for an unreachable BLE ring.

This module deliberately stops at the Bluetooth link layer.  It can observe
legacy, directed, and extended advertisements without relying on a device name
or a CoreBluetooth cache, and can ask a controller to create a connection to an
*exact address that was observed in the same run*.  It never sends ATT/GATT,
ring protocol, sensor, DFU, or firmware data.

Raw HCI does not defeat BLE's radio protocol: LE Create Connection still needs
a connectable advertisement from the peripheral.  The value here is bypassing
OS discovery policy and stale application caches, not bypassing the radio.
"""

from __future__ import annotations

import select
import socket
import struct
import sys
import time
from dataclasses import dataclass
from typing import Iterator


HCI_COMMAND_PKT = 0x01
HCI_EVENT_PKT = 0x04
SOL_HCI = 0
HCI_FILTER = 2

EVT_DISCONN_COMPLETE = 0x05
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
EVT_LE_META_EVENT = 0x3E

EVT_LE_CONN_COMPLETE = 0x01
EVT_LE_ADVERTISING_REPORT = 0x02
EVT_LE_ENHANCED_CONN_COMPLETE = 0x0A
EVT_LE_DIRECTED_ADVERTISING_REPORT = 0x0B
EVT_LE_EXTENDED_ADVERTISING_REPORT = 0x0D

OGF_LINK_CTL = 0x01
OGF_LE_CTL = 0x08
OCF_DISCONNECT = 0x0006
OCF_LE_SET_SCAN_PARAMETERS = 0x000B
OCF_LE_SET_SCAN_ENABLE = 0x000C
OCF_LE_CREATE_CONN = 0x000D
OCF_LE_CREATE_CONN_CANCEL = 0x000E

OP_DISCONNECT = (OGF_LINK_CTL << 10) | OCF_DISCONNECT
OP_LE_SET_SCAN_PARAMETERS = (OGF_LE_CTL << 10) | OCF_LE_SET_SCAN_PARAMETERS
OP_LE_SET_SCAN_ENABLE = (OGF_LE_CTL << 10) | OCF_LE_SET_SCAN_ENABLE
OP_LE_CREATE_CONN = (OGF_LE_CTL << 10) | OCF_LE_CREATE_CONN
OP_LE_CREATE_CONN_CANCEL = (OGF_LE_CTL << 10) | OCF_LE_CREATE_CONN_CANCEL

ADDRESS_TYPE = {"public": 0x00, "random": 0x01}
ADDRESS_TYPE_NAME = {value: key for key, value in ADDRESS_TYPE.items()}

# The R02 exposes these services after connection.  Some revisions also put
# them in advertising data; FEE7 alone is deliberately not treated as identity.
UART_SERVICE_UUID = "6e40fff0-b5a3-f393-e0a9-e50e24dcca9e"
DFU_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"


class HCIError(RuntimeError):
    """A controller rejected or failed a bounded recovery operation."""


@dataclass(frozen=True)
class Advertisement:
    address: str
    address_type: int
    event_type: int
    rssi: int
    data: bytes
    direct_address: str | None = None
    direct_address_type: int | None = None
    extended: bool = False

    @property
    def connectable(self) -> bool:
        if self.extended:
            return bool(self.event_type & 0x0001)
        return self.event_type in (0x00, 0x01)

    @property
    def directed(self) -> bool:
        if self.extended:
            return bool(self.event_type & 0x0004)
        return self.event_type == 0x01 or self.direct_address is not None

    @property
    def local_name(self) -> str | None:
        for kind, value in ad_elements(self.data):
            if kind in (0x08, 0x09):
                return value.decode("utf-8", errors="replace")
        return None

    @property
    def service_uuids(self) -> tuple[str, ...]:
        values: list[str] = []
        for kind, value in ad_elements(self.data):
            if kind in (0x02, 0x03):
                for offset in range(0, len(value) - 1, 2):
                    values.append(f"{int.from_bytes(value[offset:offset + 2], 'little'):04x}")
            elif kind in (0x06, 0x07):
                for offset in range(0, len(value) - 15, 16):
                    values.append(uuid128_from_le(value[offset:offset + 16]))
        return tuple(values)

    @property
    def strong_ring_identity(self) -> bool:
        name = (self.local_name or "").upper()
        named = "COLMI" in name or any(f"R0{n}" in name for n in range(1, 10)) or "R10" in name
        services = {item.lower() for item in self.service_uuids}
        return named or UART_SERVICE_UUID in services or DFU_SERVICE_UUID in services


@dataclass(frozen=True)
class ConnectionComplete:
    status: int
    handle: int
    address: str
    address_type: int
    interval: int
    latency: int
    supervision_timeout: int


def address_to_le(address: str) -> bytes:
    parts = address.split(":")
    if len(parts) != 6:
        raise ValueError(f"invalid Bluetooth address: {address!r}")
    try:
        raw = bytes(int(part, 16) for part in parts)
    except ValueError as exc:
        raise ValueError(f"invalid Bluetooth address: {address!r}") from exc
    if any(len(part) != 2 for part in parts):
        raise ValueError(f"invalid Bluetooth address: {address!r}")
    return raw[::-1]


def address_from_le(raw: bytes) -> str:
    if len(raw) != 6:
        raise ValueError("a Bluetooth address is exactly six bytes")
    return ":".join(f"{byte:02X}" for byte in raw[::-1])


def uuid128_from_le(raw: bytes) -> str:
    if len(raw) != 16:
        raise ValueError("a 128-bit UUID is exactly sixteen bytes")
    canonical = raw[::-1].hex()
    return "-".join((canonical[:8], canonical[8:12], canonical[12:16],
                     canonical[16:20], canonical[20:]))


def ad_elements(data: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield well-formed AD structures; ignore a truncated final structure."""
    offset = 0
    while offset < len(data):
        length = data[offset]
        if length == 0:
            return
        end = offset + 1 + length
        if length < 1 or end > len(data):
            return
        yield data[offset + 1], data[offset + 2:end]
        offset = end


def hci_command(opcode: int, parameters: bytes = b"") -> bytes:
    if len(parameters) > 255:
        raise ValueError("HCI command parameters exceed one-byte length")
    return struct.pack("<BHB", HCI_COMMAND_PKT, opcode, len(parameters)) + parameters


def set_scan_parameters_command(*, active: bool = True, interval: int = 0x0060,
                                window: int = 0x0060) -> bytes:
    if not 0x0004 <= window <= interval <= 0x4000:
        raise ValueError("scan timing must satisfy 0x0004 <= window <= interval <= 0x4000")
    parameters = struct.pack("<BHHBB", int(active), interval, window, 0x00, 0x00)
    return hci_command(OP_LE_SET_SCAN_PARAMETERS, parameters)


def set_scan_enable_command(enabled: bool, *, filter_duplicates: bool = False) -> bytes:
    return hci_command(OP_LE_SET_SCAN_ENABLE,
                       struct.pack("<BB", int(enabled), int(filter_duplicates)))


def create_connection_command(address: str, address_type: int, *,
                              scan_interval: int = 0x0060,
                              scan_window: int = 0x0060) -> bytes:
    if address_type not in ADDRESS_TYPE_NAME:
        raise ValueError("peer address type must be public (0) or random (1)")
    if not 0x0004 <= scan_window <= scan_interval <= 0x4000:
        raise ValueError("initiator timing must satisfy window <= interval")
    parameters = struct.pack(
        "<HHBB6sBHHHHHH",
        scan_interval,
        scan_window,
        0x00,  # initiator filter policy: use exact peer address
        address_type,
        address_to_le(address),
        0x00,  # own public address; a dedicated adapter has no RPA dependency
        0x0018,  # 30 ms connection interval minimum
        0x0028,  # 50 ms connection interval maximum
        0x0000,  # peripheral latency
        0x01F4,  # 5 s supervision timeout
        0x0000,
        0x0000,
    )
    return hci_command(OP_LE_CREATE_CONN, parameters)


def create_connection_cancel_command() -> bytes:
    return hci_command(OP_LE_CREATE_CONN_CANCEL)


def disconnect_command(handle: int, reason: int = 0x13) -> bytes:
    if not 0 <= handle <= 0x0EFF:
        raise ValueError("invalid 12-bit connection handle")
    return hci_command(OP_DISCONNECT, struct.pack("<HB", handle, reason))


def _event_payload(packet: bytes) -> tuple[int, bytes] | None:
    if len(packet) < 3 or packet[0] != HCI_EVENT_PKT:
        return None
    length = packet[2]
    if len(packet) < 3 + length:
        return None
    return packet[1], packet[3:3 + length]


def command_result(packet: bytes) -> tuple[int, int] | None:
    """Return ``(opcode, status)`` for Command Complete/Status events."""
    parsed = _event_payload(packet)
    if parsed is None:
        return None
    event, payload = parsed
    if event == EVT_CMD_STATUS and len(payload) >= 4:
        return int.from_bytes(payload[2:4], "little"), payload[0]
    if event == EVT_CMD_COMPLETE and len(payload) >= 4:
        return int.from_bytes(payload[1:3], "little"), payload[3]
    return None


def parse_advertisements(packet: bytes) -> tuple[Advertisement, ...]:
    parsed = _event_payload(packet)
    if parsed is None or parsed[0] != EVT_LE_META_EVENT or not parsed[1]:
        return ()
    payload = parsed[1]
    subevent = payload[0]
    body = payload[1:]
    if not body:
        return ()

    reports: list[Advertisement] = []
    count = body[0]
    offset = 1
    try:
        for _ in range(count):
            if subevent == EVT_LE_ADVERTISING_REPORT:
                event_type, address_type = body[offset], body[offset + 1]
                address = address_from_le(body[offset + 2:offset + 8])
                data_length = body[offset + 8]
                data_start = offset + 9
                data_end = data_start + data_length
                rssi = struct.unpack("b", body[data_end:data_end + 1])[0]
                reports.append(Advertisement(address, address_type, event_type, rssi,
                                             body[data_start:data_end]))
                offset = data_end + 1
            elif subevent == EVT_LE_DIRECTED_ADVERTISING_REPORT:
                event_type, address_type = body[offset], body[offset + 1]
                address = address_from_le(body[offset + 2:offset + 8])
                direct_type = body[offset + 8]
                direct_address = address_from_le(body[offset + 9:offset + 15])
                rssi = struct.unpack("b", body[offset + 15:offset + 16])[0]
                reports.append(Advertisement(address, address_type, event_type, rssi, b"",
                                             direct_address, direct_type))
                offset += 16
            elif subevent == EVT_LE_EXTENDED_ADVERTISING_REPORT:
                event_type = int.from_bytes(body[offset:offset + 2], "little")
                address_type = body[offset + 2]
                address = address_from_le(body[offset + 3:offset + 9])
                rssi = struct.unpack("b", body[offset + 13:offset + 14])[0]
                direct_type = body[offset + 16]
                direct_raw = body[offset + 17:offset + 23]
                data_length = body[offset + 23]
                data_start = offset + 24
                data_end = data_start + data_length
                direct_address = None if direct_type == 0xFF else address_from_le(direct_raw)
                reports.append(Advertisement(address, address_type, event_type, rssi,
                                             body[data_start:data_end], direct_address,
                                             None if direct_type == 0xFF else direct_type,
                                             extended=True))
                offset = data_end
            else:
                return ()
    except (IndexError, struct.error, ValueError):
        return ()
    return tuple(reports)


def parse_connection_complete(packet: bytes) -> ConnectionComplete | None:
    parsed = _event_payload(packet)
    if parsed is None or parsed[0] != EVT_LE_META_EVENT or len(parsed[1]) < 2:
        return None
    payload = parsed[1]
    subevent = payload[0]
    body = payload[1:]
    if subevent not in (EVT_LE_CONN_COMPLETE, EVT_LE_ENHANCED_CONN_COMPLETE):
        return None
    # Both events begin with this common prefix.  Enhanced Complete inserts two
    # local/peer RPA fields after the peer address, before interval.
    if len(body) < 18:
        return None
    status = body[0]
    handle = int.from_bytes(body[1:3], "little") & 0x0FFF
    address_type = body[4]
    address = address_from_le(body[5:11])
    timing_offset = 23 if subevent == EVT_LE_ENHANCED_CONN_COMPLETE else 11
    if len(body) < timing_offset + 6:
        return None
    interval, latency, timeout = struct.unpack_from("<HHH", body, timing_offset)
    return ConnectionComplete(status, handle, address, address_type,
                              interval, latency, timeout)


class RawHCI:
    """Minimal HCI command/event transport for a dedicated Linux controller."""

    def __init__(self, adapter: int = 0):
        self.adapter = adapter
        self.sock: socket.socket | None = None

    def __enter__(self) -> "RawHCI":
        if not sys.platform.startswith("linux"):
            raise HCIError(
                "raw HCI execution requires Linux and a dedicated BLE adapter; "
                "Apple's internal CoreBluetooth controller does not expose this interface"
            )
        af_bluetooth = getattr(socket, "AF_BLUETOOTH", 31)
        btproto_hci = getattr(socket, "BTPROTO_HCI", 1)
        try:
            self.sock = socket.socket(af_bluetooth, socket.SOCK_RAW, btproto_hci)
            self.sock.bind((self.adapter,))
            # A new Linux raw-HCI socket may otherwise have an empty packet
            # filter.  Accept HCI event packets and every event number; opcode
            # matching remains explicit in command().
            event_filter = struct.pack("<IIIH", 1 << HCI_EVENT_PKT,
                                       0xFFFFFFFF, 0xFFFFFFFF, 0)
            self.sock.setsockopt(SOL_HCI, HCI_FILTER, event_filter)
            self.sock.setblocking(False)
        except (OSError, PermissionError) as exc:
            if self.sock is not None:
                self.sock.close()
                self.sock = None
            raise HCIError(
                f"cannot open hci{self.adapter}: {exc}; use a dedicated adapter and "
                "CAP_NET_RAW/CAP_NET_ADMIN (or root)"
            ) from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def send(self, packet: bytes) -> None:
        if self.sock is None:
            raise HCIError("HCI transport is not open")
        self.sock.send(packet)

    def receive(self, timeout: float) -> bytes | None:
        if self.sock is None:
            raise HCIError("HCI transport is not open")
        ready, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
        return self.sock.recv(4096) if ready else None

    def command(self, packet: bytes, opcode: int, timeout: float = 2.0) -> None:
        self.send(packet)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.receive(deadline - time.monotonic())
            if event is None:
                break
            result = command_result(event)
            if result is None or result[0] != opcode:
                continue
            if result[1] != 0:
                raise HCIError(f"controller rejected opcode 0x{opcode:04x}: status 0x{result[1]:02x}")
            return
        raise HCIError(f"no completion/status for opcode 0x{opcode:04x}")

    def scan(self, seconds: float) -> Iterator[Advertisement]:
        self.command(set_scan_enable_command(False), OP_LE_SET_SCAN_ENABLE)
        self.command(set_scan_parameters_command(), OP_LE_SET_SCAN_PARAMETERS)
        self.command(set_scan_enable_command(True), OP_LE_SET_SCAN_ENABLE)
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                event = self.receive(min(1.0, deadline - time.monotonic()))
                if event is not None:
                    yield from parse_advertisements(event)
        finally:
            self.command(set_scan_enable_command(False), OP_LE_SET_SCAN_ENABLE)

    def connect(self, observed: Advertisement, timeout: float = 90.0) -> ConnectionComplete:
        if not observed.connectable:
            raise HCIError(f"{observed.address} did not emit a connectable advertisement")
        self.command(
            create_connection_command(observed.address, observed.address_type),
            OP_LE_CREATE_CONN,
        )
        deadline = time.monotonic() + timeout
        connected = False
        try:
            while time.monotonic() < deadline:
                event = self.receive(min(1.0, deadline - time.monotonic()))
                if event is None:
                    continue
                complete = parse_connection_complete(event)
                if complete is None:
                    continue
                if complete.status != 0:
                    raise HCIError(f"LE connection failed: status 0x{complete.status:02x}")
                if complete.address != observed.address:
                    self.command(disconnect_command(complete.handle), OP_DISCONNECT)
                    raise HCIError("controller completed a connection to an unexpected address")
                connected = True
                return complete
        finally:
            # Cancel on timeout, interruption, or a failed complete event. A
            # controller whose procedure already ended may reject it; harmless.
            if not connected:
                try:
                    self.command(create_connection_cancel_command(), OP_LE_CREATE_CONN_CANCEL)
                except HCIError:
                    pass
        raise HCIError("timed out waiting for a connectable advertisement")

    def disconnect(self, handle: int) -> None:
        self.command(disconnect_command(handle), OP_DISCONNECT)
