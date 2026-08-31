"""
BLE capture core.

Design rule: the notification callback does as little as possible. It stamps the
arrival time and stores the payload, nothing else. Parsing, decoding and
analysis all happen offline against the saved capture, because the number we are
trying to measure is the arrival timing itself and any work done in the callback
contaminates it.

Timestamps use time.perf_counter() for intervals (monotonic, high resolution)
and time.time() once at start so captures can be located in wall clock time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from whip import protocol

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_S = 2.0


@dataclass
class DeviceInfo:
    address: str
    name: str | None
    firmware: str | None = None
    hardware: str | None = None

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "firmware": self.firmware,
            "hardware": self.hardware,
        }


@dataclass
class Capture:
    """A recorded stream of notifications plus the metadata needed to interpret it."""

    device: DeviceInfo
    started_wall: float
    param: int
    label: str
    records: list[tuple[float, bytes]] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def header(self) -> dict:
        return {
            "kind": "header",
            "started_wall": self.started_wall,
            "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_wall)),
            "param": self.param,
            "label": self.label,
            "device": self.device.as_dict(),
            **self.notes,
        }


async def find_ring(address: str | None = None, name: str | None = None, timeout: float = 10.0) -> BLEDevice:
    """
    Locate a ring. Prefer an explicit address; fall back to scanning for a known
    ring name. On macOS the address is a CoreBluetooth UUID, not a MAC.
    """
    if address:
        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        if device is None:
            raise RuntimeError(f"no device found at address {address}")
        return device

    logger.info("scanning for %.0fs", timeout)
    devices = await BleakScanner.discover(timeout=timeout)

    if name:
        match = next((d for d in devices if d.name == name), None)
        if match is None:
            raise RuntimeError(f"no device advertising the name {name!r}")
        return match

    rings = [d for d in devices if d.name and d.name.startswith(protocol.KNOWN_RING_NAMES)]
    if not rings:
        raise RuntimeError("no ring found. Is it charged and out of range of the phone app?")
    if len(rings) > 1:
        names = ", ".join(f"{d.name} ({d.address})" for d in rings)
        raise RuntimeError(f"multiple rings found, pass --address to pick one: {names}")

    return rings[0]


async def read_device_info(client: BleakClient, device: BLEDevice) -> DeviceInfo:
    """
    Read firmware and hardware revision. Worth recording on every capture:
    rings that look identical ship different firmware, and the firmware version
    is the first thing that explains a rate discrepancy between two units.
    """
    info = DeviceInfo(address=device.address, name=device.name)

    try:
        info.firmware = (await client.read_gatt_char(protocol.DEVICE_FW_UUID)).decode(errors="replace").strip()
        info.hardware = (await client.read_gatt_char(protocol.DEVICE_HW_UUID)).decode(errors="replace").strip()
    except Exception as exc:  # noqa: BLE001 - device info is nice to have, not essential
        logger.warning("could not read device info: %s", exc)

    return info


async def read_battery(client: BleakClient, timeout: float = 3.0) -> tuple[int, bool] | None:
    """Request battery level and wait for the 0x03 reply. Returns None on timeout."""
    reply: asyncio.Future = asyncio.get_running_loop().create_future()

    def handler(_sender, data: bytearray) -> None:
        if data and data[0] == protocol.CMD_BATTERY and not reply.done():
            reply.set_result(bytes(data))

    await client.start_notify(protocol.UART_TX_CHAR_UUID, handler)
    try:
        await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, protocol.BATTERY_PACKET, response=False)
        packet = await asyncio.wait_for(reply, timeout=timeout)
        return protocol.parse_battery(packet)
    except asyncio.TimeoutError:
        return None
    finally:
        await client.stop_notify(protocol.UART_TX_CHAR_UUID)


@asynccontextmanager
async def connected(device: BLEDevice, disconnect_callback=None):
    """Connect to the ring, yielding a live BleakClient."""
    client = BleakClient(device, disconnected_callback=disconnect_callback)
    await client.connect()
    logger.info("connected to %s (%s)", device.name, device.address)
    try:
        yield client
    finally:
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001 - teardown should never mask a real error
            logger.warning("error on disconnect: %s", exc)


async def stream(
    client: BleakClient,
    duration: float,
    param: int = protocol.RAW_ENABLE_ALL,
    sink: Path | None = None,
    capture: Capture | None = None,
) -> list[tuple[float, bytes]]:
    """
    Enable raw sensor streaming, record every notification for `duration`
    seconds, then disable. Returns the raw records.

    If `sink` is given, records are also flushed to a JSONL file as they arrive
    so a long capture survives a crash or a disconnect.
    """
    records: list[tuple[float, bytes]] = capture.records if capture else []
    t0 = time.perf_counter()

    def on_notify(_sender, data: bytearray) -> None:
        # Nothing but a timestamp and a copy. Any work here shows up as jitter.
        records.append((time.perf_counter() - t0, bytes(data)))

    handle = None
    if sink is not None:
        sink.parent.mkdir(parents=True, exist_ok=True)
        handle = sink.open("w")
        if capture is not None:
            handle.write(json.dumps(capture.header()) + "\n")
        handle.flush()

    written = 0

    async def flusher() -> None:
        nonlocal written
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            written = _flush(handle, records, written)

    await client.start_notify(protocol.UART_TX_CHAR_UUID, on_notify)
    await client.write_gatt_char(protocol.UART_RX_CHAR_UUID, protocol.raw_sensor_packet(param), response=False)

    flush_task = asyncio.create_task(flusher()) if handle else None
    try:
        await asyncio.sleep(duration)
    finally:
        if flush_task:
            flush_task.cancel()
        try:
            await client.write_gatt_char(
                protocol.UART_RX_CHAR_UUID, protocol.DISABLE_RAW_SENSOR, response=False
            )
            await client.stop_notify(protocol.UART_TX_CHAR_UUID)
        except Exception as exc:  # noqa: BLE001 - we still want the data we captured
            logger.warning("error stopping stream: %s", exc)

        if handle:
            _flush(handle, records, written)
            handle.close()

    return records


def _flush(handle, records: list[tuple[float, bytes]], written: int) -> int:
    """Append any records not yet on disk. Returns the new written count."""
    if handle is None:
        return written

    pending = records[written:]
    for t, payload in pending:
        handle.write(json.dumps({"t": round(t, 6), "p": payload.hex()}) + "\n")
    handle.flush()
    return written + len(pending)


def load_capture(path: Path) -> tuple[dict, list[tuple[float, bytes]]]:
    """Read a JSONL capture back into (header, records)."""
    header: dict = {}
    records: list[tuple[float, bytes]] = []

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("kind") == "header":
                header = obj
            else:
                records.append((obj["t"], bytes.fromhex(obj["p"])))

    return header, records
