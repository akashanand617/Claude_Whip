"""Fake transport tests only. Never discover/connect a real device."""
import asyncio
import hashlib
from pathlib import Path
import struct

import pytest

from whip import fwcapacity, fwcapacity_read as cr, fwidentity, protocol

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "firmware/rt02cr-25hz.bin").read_bytes()
V2 = (ROOT / "firmware/rt02cr-25hz-optical-off-v2-experimental.bin").read_bytes()


class Fake:
    def __init__(self, image=V2):
        self.image = image
        self.writes = []
        self.reader = cr.CapacityReader(self, lambda item: None, timeout=0.01, spacing=0)
        self.raw = 0
        self.bad = None
        self.config = {
            fwcapacity.RAM_CONFIG_ADDRESS: struct.pack("<4I", 0x207C00, 0x7000, 0x7400, 0),
            fwcapacity.FLASH_CONFIG_ADDRESS: struct.pack("<12I", 0x802000, 0x48000, 0x84A000, 0,
                0x84A000, 0x4000, 0x84E000, 0x24000, 0, 0, 0, 0),
        }  # Invented fixture, not measured ring configuration.

    def memory(self, address, length):
        if address == cr.IDLE_WINDOW[0]:
            return bytes([self.raw])
        for start, data in self.config.items():
            if start <= address < start + len(data):
                return data[address - start:address - start + length]
        offset = address - fwidentity.FILE_TO_ADDRESS
        assert 0x450 <= offset <= offset + length <= len(self.image)
        return self.image[offset:offset + length]

    async def write_gatt_char(self, uuid, packet, response):
        assert uuid == protocol.UART_RX_CHAR_UUID and response is False
        assert len(packet) == 16 and packet[:2] == b"\xcd\x01"
        assert packet[-1] == protocol.checksum(packet[:-1])
        address, length = int.from_bytes(packet[3:7], "big"), packet[2]
        assert (address, length) in self.reader._allowed_reads()
        self.writes.append((address, length))
        if self.bad == "write_timeout":
            await asyncio.Future()
        if self.bad == "timeout":
            return
        reply = bytes(protocol.make_packet(0xCD, self.memory(address, length)))
        if self.bad == "checksum": reply = reply[:-1] + bytes([reply[-1] ^ 1])
        if self.bad == "short": reply = reply[:-1]
        if self.bad == "stream": reply = bytes(protocol.make_packet(0xA1, b"\x03"))
        self.reader.notify(None, reply)
        if self.bad == "duplicate": self.reader.notify(None, reply)


@pytest.mark.parametrize("image", [BASE, V2], ids=["original25hz", "optical-off-v2"])
def test_exact_plan_reads_only_reviewed_windows_and_no_bank_pointers(image):
    f = Fake(image)
    result = asyncio.run(cr.collect_configuration(f.reader, BASE, V2, "fake-test-only"))
    assert result["image_sha256"] in (fwcapacity.ORIGINAL_SHA256, fwcapacity.V2_SHA256)
    assert [(w["address"], len(bytes.fromhex(w["data_hex"]))) for w in result["windows"]] == list(cr.CONFIG_WINDOWS)
    expected = len(fwidentity.read_sites()) + sum(len(cr.chunks(o, n)) for _, o, n in cr.CODE_WINDOWS)
    expected += 2 + 2 * sum(len(cr.chunks(a, n)) for a, n in cr.CONFIG_WINDOWS)
    assert len(f.writes) == expected
    # Transport was fake: do NOT promote its declared capture label to evidence.
    report = fwcapacity.analyze_capture(result, vendor_file_size=138016)
    assert not report["physical_evidence_verified"] and not report["flash_authorized"]
    assert report["missing_descriptor_banks"] == ["bank0"]
    assert not any(a == 0x802198 for a, _ in f.writes)


@pytest.mark.parametrize("address,length", [(0x200000, 14), (0x20038E, 14), (0x200414, 4),
                                            (0x802198, 14), (0x40000000, 1), (0x209CAC, 2),
                                            (True, 1), (0x200380, 16)])
def test_arbitrary_keys_peripherals_and_unreviewed_bank_addresses_refused(address, length):
    f = Fake()
    with pytest.raises(ValueError): asyncio.run(f.reader.read(address, length))
    assert f.writes == []


@pytest.mark.parametrize("bad", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_one_bad_reply_poisons_connection_and_never_retries(bad):
    f = Fake()
    f.bad = bad
    with pytest.raises((RuntimeError, TimeoutError)):
        asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
    assert f.reader.poisoned
    f.bad = None
    with pytest.raises(RuntimeError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
    assert len(f.writes) == 1


def test_preexisting_reply_or_parallel_request_refused():
    f = Fake()
    f.reader.notify(None, bytes(protocol.make_packet(0xCD)))
    with pytest.raises(RuntimeError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
    assert not f.writes
    f = Fake()
    async def busy():
        f.reader.pending = asyncio.get_running_loop().create_future()
        with pytest.raises(RuntimeError): await f.reader.read(*cr.IDLE_WINDOW)
        f.reader.pending.cancel()
    asyncio.run(busy())
    assert not f.writes


@pytest.mark.parametrize("packet", [b"", bytes(protocol.make_packet(0x03, b"private")),
                                  bytes(protocol.make_packet(0xA1, b"private"))])
def test_foreign_packet_logs_only_metadata_and_remains_terminal(packet):
    f = Fake()
    events = []
    f.reader.emit = events.append
    f.reader.notify(None, packet)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event.pop("monotonic"), float)
    assert event == {"kind": "unexpected_notification", "command": packet[0] if packet else None,
                     "bytes": len(packet), "payload_saved": False, "status_subtype": None,
                     "checksum_valid": bool(packet)}
    assert f.reader.poisoned
    with pytest.raises(RuntimeError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
    assert not f.writes


@pytest.mark.parametrize("which", ["identity", "diagnostic_path", "raw_active"])
def test_mismatch_never_reads_config_or_stops_stream(which):
    f = Fake()
    image = bytearray(V2)
    if which == "identity": image[0x21D6] ^= 1
    if which == "diagnostic_path": image[0x564A] ^= 1
    if which == "raw_active": f.raw = 4
    f.image = bytes(image)
    with pytest.raises(RuntimeError):
        asyncio.run(cr.collect_configuration(f.reader, BASE, V2, "fake"))
    assert not any(0x200380 <= a < 0x200414 for a, _ in f.writes)


def test_invalid_local_reference_sends_nothing():
    f = Fake()
    with pytest.raises(ValueError):
        asyncio.run(cr.collect_configuration(f.reader, BASE, V2[:-1], "fake"))
    assert not f.writes


class DescriptorFake(Fake):
    def __init__(self, image=V2):
        super().__init__(image)
        self.reader = cr.DescriptorReader(self, lambda item: None, timeout=0.01, spacing=0)
        self.config[fwcapacity.RAM_CONFIG_ADDRESS] = cr.EXPECTED_RAM_CONFIG
        self.config[fwcapacity.FLASH_CONFIG_ADDRESS] = cr.EXPECTED_FLASH_CONFIG
        # Invented bank header. This is NOT the unread physical descriptor.
        self.config[0x802198] = struct.pack("<20I", 0x803000, 0x1000,
            0x804000, 0x22000, 0x826000, 0x24000, *([0] * 14))
        self.descriptor_reads = 0
        self.mutation = None
        self.descriptor_fault = None

    async def write_gatt_char(self, uuid, packet, response):
        address = int.from_bytes(packet[3:7], "big")
        if 0x802198 <= address < 0x8021E8 and self.descriptor_fault:
            self.bad = self.descriptor_fault
        await super().write_gatt_char(uuid, packet, response)

    def memory(self, address, length):
        if 0x802198 <= address < 0x8021E8:
            self.descriptor_reads += 1
            if self.mutation == "idle": self.raw = 4
        raw = super().memory(address, length)
        if (self.mutation == "descriptor" and address == 0x802198
                and self.descriptor_reads > 6):
            return bytes([raw[0] ^ 1]) + raw[1:]
        if (self.mutation == "config_after" and address == fwcapacity.RAM_CONFIG_ADDRESS
                and self.descriptor_reads):
            return bytes([raw[0] ^ 1]) + raw[1:]
        return raw


def test_descriptor_prerequisites_pin_the_actual_prior_nonsecret_windows():
    assert len(cr.EXPECTED_RAM_CONFIG) == 16 and len(cr.EXPECTED_FLASH_CONFIG) == 48
    assert hashlib.sha256(cr.EXPECTED_RAM_CONFIG).hexdigest() == "d181b7378851e44b709578a730fdafcbcf658ee96e9a0ee2a199fba433d30099"
    assert hashlib.sha256(cr.EXPECTED_FLASH_CONFIG).hexdigest() == "19f636dc558b3e0d11daebb254ecaaf76d5c3a8597e7219063bf55f3715bf32e"


def test_descriptor_plan_adds_only_one_fixed_window_twice_and_closes_phase():
    f = DescriptorFake()
    with pytest.raises(ValueError): asyncio.run(f.reader.read(0x802198, 14))
    result = asyncio.run(cr.collect_bank0_descriptor(f.reader, BASE, V2, "fake-descriptor"))
    assert len(f.writes) == 91 and f.descriptor_reads == 12
    descriptor_requests = [(a, n) for a, n in f.writes if 0x802000 <= a < 0x803000]
    assert descriptor_requests == list(cr.chunks(0x802198, 80)) * 2
    assert result["windows"][-1]["address"] == 0x802198
    assert not f.reader._descriptor_phase
    with pytest.raises(ValueError): asyncio.run(f.reader.read(0x802198, 14))
    report = fwcapacity.analyze_capture(result, vendor_file_size=138016)
    assert report["missing_descriptor_banks"] == []
    assert not report["flash_authorized"] and not report["placement_approved"]
    assert report["banks"][0]["configured_app_margin_bytes"] == 9520


@pytest.mark.parametrize("address,length", [(0x802190, 14), (0x802198, 15), (0x8021E8, 1),
                                            (0x84A198, 14), (0x1000198, 14), (0x40000000, 4)])
def test_even_unlocked_descriptor_plan_cannot_follow_other_pointers(address, length):
    f = DescriptorFake()
    f.reader._descriptor_phase = True  # Explicit fault injection, not normal API.
    with pytest.raises(ValueError): asyncio.run(f.reader.read(address, length))
    assert not f.writes


@pytest.mark.parametrize("mismatch", ["base_image", "ram", "flash", "active"])
def test_descriptor_prerequisite_mismatch_never_reads_header(mismatch):
    f = DescriptorFake(BASE if mismatch == "base_image" else V2)
    if mismatch in ("ram", "flash"):
        addr = fwcapacity.RAM_CONFIG_ADDRESS if mismatch == "ram" else fwcapacity.FLASH_CONFIG_ADDRESS
        raw = f.config[addr]
        f.config[addr] = bytes([raw[0] ^ 1]) + raw[1:]
    if mismatch == "active": f.raw = 4
    with pytest.raises(RuntimeError):
        asyncio.run(cr.collect_bank0_descriptor(f.reader, BASE, V2, "fake-mismatch"))
    assert f.descriptor_reads == 0 and f.reader.poisoned and not f.reader._descriptor_phase


@pytest.mark.parametrize("change", ["descriptor", "config_after", "idle"])
def test_descriptor_session_mutation_aborts_without_retries(change):
    f = DescriptorFake()
    f.mutation = change
    with pytest.raises(RuntimeError):
        asyncio.run(cr.collect_bank0_descriptor(f.reader, BASE, V2, "fake-mutation"))
    assert f.reader.poisoned and not f.reader._descriptor_phase
    assert f.descriptor_reads == 12
    with pytest.raises(RuntimeError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))


def test_malformed_descriptor_is_preserved_but_never_followed_or_approved():
    f = DescriptorFake()
    f.config[0x802198] = bytes([0xFF]) * 80
    result = asyncio.run(cr.collect_bank0_descriptor(f.reader, BASE, V2, "fake-invalid-format"))
    assert result["windows"][-1]["data_hex"] == "ff" * 80
    with pytest.raises(ValueError): fwcapacity.analyze_capture(result, vendor_file_size=138016)
    assert f.descriptor_reads == 12 and len(f.writes) == 91


def test_original_reader_cannot_run_descriptor_plan():
    f = Fake()
    with pytest.raises(ValueError):
        asyncio.run(cr.collect_bank0_descriptor(f.reader, BASE, V2, "fake"))
    assert not f.writes


@pytest.mark.parametrize("fault", ["timeout", "write_timeout", "checksum", "short", "stream", "duplicate"])
def test_descriptor_transport_fault_closes_phase_and_never_retries(fault):
    f = DescriptorFake()
    f.descriptor_fault = fault
    with pytest.raises((RuntimeError, TimeoutError)):
        asyncio.run(cr.collect_bank0_descriptor(f.reader, BASE, V2, "fake-transport-fault"))
    assert f.reader.poisoned and not f.reader._descriptor_phase
    assert [(a, n) for a, n in f.writes if 0x802000 <= a < 0x803000] == [(0x802198, 14)]
    with pytest.raises(RuntimeError): asyncio.run(f.reader.read(*cr.IDLE_WINDOW))
