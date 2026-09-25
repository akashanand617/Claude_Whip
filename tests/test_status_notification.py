"""Exact-image 0x73 packet construction, not physical event attribution.

Only three selected constructors and their checksum helper execute. Getters
return explicit fixtures; transport is intercepted before queue/BLE execution.
No RTOS, sensor, battery, timing, history or live-cause proof follows.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from whip import fwcapacity, protocol
from whip.fwplacement import _bl_destination
from tests.test_fwcapacity_read import Fake

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "stock": ("rt02cr-stock-3.12.02.bin", fwcapacity.STOCK_SHA256,
              (0x66B6, 0x67A6, 0x67D0), (0x679A, 0x67D0, 0x6812),
              0x3FE8, 0x7E30, 0x68F8, 0x209D30,
              (0xB7B8, 0xB9A2, 0xB9AA, 0x2C36, 0x2DAE, 0x3F7A,
               0x3F76, 0x3F8A, 0xEC4C, 0xE9D8, 0xE84E)),
    "v2": ("rt02cr-25hz-optical-off-v2-experimental.bin", fwcapacity.V2_SHA256,
           (0x646E, 0x655E, 0x6588), (0x6552, 0x6588, 0x65CA),
           0x3EEC, 0x7C0C, 0x66B0, 0x209D2C,
           (0xB762, 0xB95A, 0xB960, 0x2BD6, 0x2D4E, 0x3E82,
            0x3E7E, 0x3E92, 0xEB7C, 0xE908, 0xE77E)),
}
PROFILES["original25Hz"] = (
    "rt02cr-25hz.bin", fwcapacity.ORIGINAL_SHA256, *PROFILES["v2"][2:])
GETTER_VALUES = (0x123456, 0x654321, 0x112233, 73, 3,
                 0x12345678, 0x9ABC, 0x1357, 61, 42, 87)
SUBTYPE_DATA = {
    0x12: bytes.fromhex("123456654321112233"),
    0x0C: bytes([73, 1]), 0x25: bytes.fromhex("123456789abc"),
    0x38: bytes.fromhex("1357"), 0x27: bytes([61]),
    0x28: bytes.fromhex("abcd"), 0x2B: bytes([42]), 0x2C: bytes([87]),
}


class Constructor:
    """Test-only bounded instruction execution; never loads BLE tooling."""
    BIAS = 0x825FB0
    STOP = 0x3FFF0
    STACK = 0x221FF0
    BUFFER = 0x220100

    def __init__(self, profile):
        import unicorn as u
        from unicorn import arm_const as a
        self.u, self.a = u, a
        (name, digest, self.entries, ends, checksum, self.send,
         self.literal, self.field, getters) = PROFILES[profile]
        self.image = (ROOT / "firmware" / name).read_bytes()
        assert hashlib.sha256(self.image).hexdigest() == digest
        self.ranges = (*zip(self.entries, ends, strict=True), (checksum, checksum + 26))
        self.getters = dict(zip(getters, GETTER_VALUES, strict=True))
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_write(self.BIAS, self.image)
        self.uc.mem_map(0x3F000, 0x1000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(0x209000, 0x1000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_write(self.field, bytes.fromhex("abcd"))
        self.uc.mem_map(0x220000, 0x2000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.uc.mem_write(self.BUFFER, bytes(range(12)))
        self.uc.hook_add(u.UC_HOOK_CODE, self.code)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self.read)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self.write)

    def read(self, uc, access, address, size, value, opaque):
        allowed = ((0x221000, 0x222000), (self.BUFFER, self.BUFFER + 12),
                   (self.field, self.field + 2),
                   (self.BIAS + self.literal, self.BIAS + self.literal + 4))
        if not any(lo <= address < address + size <= hi for lo, hi in allowed):
            raise RuntimeError(f"unreviewed data read {address:#x}")

    def write(self, uc, access, address, size, value, opaque):
        if not 0x221000 <= address < address + size <= 0x222000:
            raise RuntimeError(f"unreviewed write {address:#x}")

    def code(self, uc, address, size, opaque):
        if address == self.STOP:
            self.returned = True
            uc.emu_stop()
            return
        offset = address - self.BIAS
        if offset in self.getters or offset == self.send:
            if offset == self.send:
                ptr = uc.reg_read(self.a.UC_ARM_REG_R0)
                assert 0x221000 <= ptr <= 0x222000 - 16
                self.packets.append(bytes(uc.mem_read(ptr, 16)))
                value = 0  # explicit transport substitute, not queue acceptance
            else:
                self.getter_calls.append(offset)
                value = self.getters[offset]
            uc.reg_write(self.a.UC_ARM_REG_R0, value)
            uc.reg_write(self.a.UC_ARM_REG_PC, uc.reg_read(self.a.UC_ARM_REG_LR))
            return
        if not any(lo <= offset < offset + size <= hi for lo, hi in self.ranges):
            raise RuntimeError(f"unreviewed code {offset:#x}")

    def call(self, index, *args):
        self.packets, self.getter_calls, self.returned = [], [], False
        for reg, value in zip((self.a.UC_ARM_REG_R0, self.a.UC_ARM_REG_R1,
                               self.a.UC_ARM_REG_R2, self.a.UC_ARM_REG_R3),
                              (*args, 0, 0, 0, 0)):
            self.uc.reg_write(reg, value)
        self.uc.mem_write(0x221000, b"\xa5" * 0x1000)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, self.STOP | 1)
        self.uc.emu_start((self.BIAS + self.entries[index]) | 1, 0xFFFFFFFF, count=5000)
        assert self.returned and self.uc.reg_read(self.a.UC_ARM_REG_SP) == self.STACK
        assert len(self.packets) == 1
        return self.packets[0]


@pytest.mark.parametrize("profile", PROFILES)
def test_all_subtypes_share_0x73_so_command_alone_cannot_identify_event(profile):
    h = Constructor(profile)
    for subtype in range(256):
        packet = h.call(0, subtype)
        expected = protocol.make_packet(0x73, bytes([subtype]) + SUBTYPE_DATA.get(subtype, b""))
        assert packet == bytes(expected)
        assert bool(h.getter_calls) == (subtype in SUBTYPE_DATA and subtype != 0x28)
        assert protocol.notification_metadata(packet)["status_subtype"] == subtype


@pytest.mark.parametrize("profile", PROFILES)
def test_two_argument_constructor_sends_status_and_value_not_a_unique_event(profile):
    h = Constructor(profile)
    for subtype in (0, 0x2A, 0x2D, 0x30, 255):
        for value in (0, 1, 255, 256, 0xFFFFFFFF):
            assert h.call(1, subtype, value) == bytes(protocol.make_packet(0x73, bytes([subtype, value & 255])))
            assert not h.getter_calls


@pytest.mark.parametrize("profile", PROFILES)
def test_buffer_constructor_caps_at_twelve_bytes_and_leaves_padding_zero(profile):
    h = Constructor(profile)
    for length in (0, 1, 11, 12, 13, 255, 0xFFFFFFFF):
        assert h.call(2, 0xA5, h.BUFFER, length) == bytes(protocol.make_packet(
            0x73, b"\xa5" + bytes(range(min(length, 12)))))
        assert not h.getter_calls


@pytest.mark.parametrize("profile", PROFILES)
def test_selected_real_callers_include_motion_health_and_device_status(profile):
    h = Constructor(profile)
    # Local exact-image call-site witnesses, not an exhaustive indirect graph
    # or evidence that any one caller produced the archived physical packet.
    calls = ((0xCEFA, 0x12), (0xE0FA, 3), (0x2C4E, 0x0C)) if profile == "stock" else (
        (0xCE98, 0x12), (0xE036, 3), (0x2BEE, 0x0C))
    for site, subtype in calls:
        assert h.image[site - 2:site] == bytes([subtype, 0x20])
        assert _bl_destination(h.image, site) == h.entries[0]


def test_metadata_never_contains_measurements_or_checksum_value():
    # Holding subtype fixed, every payload variation must produce identical
    # metadata. This is not a hash, digest, or encoded form of health values.
    expected = {"command": 0x73, "bytes": 16, "checksum_valid": True,
                "status_subtype": 0x12, "payload_saved": False}
    for value in range(256):
        packet = protocol.make_packet(0x73, b"\x12" + bytes([value]) * 13)
        assert protocol.notification_metadata(packet) == expected
    for command in range(256):
        if command != 0x73:
            assert protocol.notification_metadata(protocol.make_packet(command, b"private"))["status_subtype"] is None


@pytest.mark.parametrize("raw", [b"", b"\x73", b"\x73\x12", b"\x73" * 15,
                                  b"\x73" * 16, b"\x73" * 17])
def test_malformed_packet_never_gets_a_trusted_subtype(raw):
    result = protocol.notification_metadata(raw)
    assert result["checksum_valid"] is False and result["status_subtype"] is None


@pytest.mark.parametrize("subtype", [0x0C, 0x12, 0x03, 0x2D, 0xFF])
@pytest.mark.parametrize("when", ["before_read", "pending", "after_reply"])
def test_every_status_subtype_remains_terminal_for_diagnostic(subtype, when):
    f = Fake(); events = []; f.reader.emit = events.append
    packet = bytes(protocol.make_packet(0x73, bytes([subtype]) + b"private"))
    async def run():
        if when == "before_read":
            f.reader.notify(None, packet)
        else:
            original = f.write_gatt_char
            async def inject(uuid, request, *, response):
                if when == "after_reply":
                    await original(uuid, request, response=response)
                else:
                    # No diagnostic reply is invented in the pending case.
                    assert uuid == protocol.UART_RX_CHAR_UUID and response is False
                    assert request[:2] == b"\xcd\x01"
                    f.writes.append((int.from_bytes(request[3:7], "big"), request[2]))
                f.reader.notify(None, packet)
            f.write_gatt_char = inject
        from whip import fwcapacity_read as cr
        with pytest.raises(RuntimeError): await f.reader.read(*cr.IDLE_WINDOW)
        assert f.reader.poisoned
        with pytest.raises(RuntimeError): await f.reader.read(*cr.IDLE_WINDOW)
    asyncio.run(run())
    assert len(f.writes) == (0 if when == "before_read" else 1)
    status = [e for e in events if e["kind"] == "unexpected_notification"]
    assert len(status) == 1 and status[0]["status_subtype"] == subtype
    assert status[0]["checksum_valid"] and isinstance(status[0]["monotonic"], float)
    assert "private" not in json.dumps(status) and "70726976617465" not in json.dumps(status)


def test_old_aborted_capture_cannot_gain_a_subtype_retroactively():
    path = ROOT / "firmware/research/2026-09-23/rom-create-hook-aborted/transcript.jsonl"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "b28dbcb5749ed3e69dc577550f72bca7ff91bbb88df5f3d8cc973708445f6ece"
    rows = [json.loads(s) for s in raw.splitlines()]
    assert [r for r in rows if r["kind"] == "unexpected_notification"] == [
        {"kind": "unexpected_notification", "command": 0x73, "bytes": 16, "payload_saved": False}]
    assert rows[-1]["kind"] == "aborted" and rows[-1]["disconnect_confirmed"]
    assert not (path.parent / "rom-create-hook.json").exists()
