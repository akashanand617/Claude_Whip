"""Unattached codec: actual ARM C and whole Swift file against independent frames."""
import binascii
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess

import pytest

from tests.test_unified_thumb import elf  # noqa: F401 — same guarded test ELF
from whip.fwthumb import RuntimeThumb

ROOT = Path(__file__).resolve().parents[1]
BOOT = 0xFEDCBA9876543210


def seal(data):
    assert len(data) == 18
    return data + struct.pack("<H", binascii.crc_hqx(data, 0xFFFF))


def frames(kind, request, body):
    assert len(body) == 20
    return [seal(bytes([0x57, 1, kind, part]) + struct.pack("<I", request) + body[part*10:part*10+10])
            for part in range(2)]


def request(op=1, boot=BOOT, session=0, sequence=0):
    return struct.pack("<BBQIIH", op, 0, boot, session, sequence, 0)


def reply(op=1, result=0, mode=0, charging=0, boot=BOOT, session=0):
    return struct.pack("<BBBBQII", op, result, mode, charging, boot, session, 0)


class WireARM(RuntimeThumb):
    CONTEXT_SIZE_SYMBOL = "proof_wire_size"
    CONTEXT_MAX_BYTES = 128

    def __init__(self, image):
        super().__init__(image)
        self.out = self.CONTEXT + self.call("proof_wire_output_offset")
        self.body = self.CONTEXT + self.call("proof_wire_body_offset")

    def pack(self, kind, id, body):
        ptr = self.raw_input(body or b"\0")
        for part in range(2):
            if not self.call("ww_pack_control", kind, id, ptr, len(body), part, self.out + 20 * part):
                return None
        return [bytes(self.uc.mem_read(self.out + 20*i, 20)) for i in range(2)]

    def begin(self, kind=1, id=42, connection=7, boot=BOOT, operation=1, now=100):
        self.invoke("ww_rx_begin", kind, id, connection, boot & 0xFFFFFFFF, boot >> 32, operation, now)

    def feed(self, packet, connection=7, now=101):
        return self.invoke("ww_rx_feed", self.raw_input(packet or b"\0"), len(packet), connection, now)


@pytest.fixture
def arm(elf):
    return WireARM(elf)


def test_crc_known_answer_and_output_memory_guards(arm):
    assert arm.call("ww_crc", arm.raw_input(b"123456789"), 9) == 0x29B1
    assert arm.context_size == 84
    assert arm.call("proof_wire_body_offset") == 24
    assert arm.call("proof_wire_output_offset") == 44


@pytest.mark.parametrize("alignment", range(4))
def test_shared_bytewise_integer_codec_handles_unaligned_spans_without_neighbor_writes(arm, alignment):
    rng = random.Random(0x32 + alignment)
    for value in [0, 1, 255, 256, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
                  *(rng.randrange(2**32) for _ in range(32))]:
        encoded = struct.pack('<I', value)
        pointer = arm.raw_input(b'\xa5' * alignment + encoded) + alignment
        assert arm.call('ww_get32', pointer) == value
        arm.uc.mem_write(arm.out, b'\xa5' * 12)
        arm.call('ww_put32', arm.out + alignment, value)
        assert bytes(arm.uc.mem_read(arm.out, 12)) == b'\xa5' * alignment + encoded + b'\xa5' * (8 - alignment)


@pytest.mark.parametrize('part', [0, 1])
@pytest.mark.parametrize('kind,body', [(1, request()), (2, reply())])
def test_control_encoder_writes_only_the_requested_twenty_byte_fragment(arm, part, kind, body):
    arm.uc.mem_write(arm.out, b'\xa5' * 40)
    assert arm.call('ww_pack_control', kind, 42, arm.raw_input(body), 20, part, arm.out + part * 20)
    expected = frames(kind, 42, body)[part]
    assert bytes(arm.uc.mem_read(arm.out + 20 * part, 20)) == expected
    assert bytes(arm.uc.mem_read(arm.out + 20 * (1 - part), 20)) == b'\xa5' * 20


@pytest.mark.parametrize('part', [2, 3, 127, 255])
def test_invalid_control_fragment_does_not_touch_caller_output(arm, part):
    arm.uc.mem_write(arm.out, b'\xa5' * 40)
    assert not arm.call('ww_pack_control', 1, 42, arm.raw_input(request()), 20, part, arm.out)
    assert bytes(arm.uc.mem_read(arm.out, 40)) == b'\xa5' * 40


@pytest.mark.parametrize("kind,body", [(1, request()), (1, request(2)), (1, request(3)),
    (1, request(4, session=8, sequence=99)), (2, reply()), (2, reply(2, session=8)),
    (2, reply(3, mode=2, session=8)), (2, reply(4, mode=2, session=8)),
    (2, reply(3, result=2, mode=1, session=8)), (2, reply(1, mode=4))])
def test_control_roundtrip_requires_both_fragments(arm, kind, body):
    expected = frames(kind, 42, body)
    assert arm.pack(kind, 42, body) == expected
    arm.begin(kind=kind, operation=body[0])
    assert arm.feed(expected[0]) == 0
    assert arm.feed(expected[1]) == 1
    assert bytes(arm.uc.mem_read(arm.body, 20)) == body
    assert arm.feed(expected[1]) == 2
    assert bytes(arm.uc.mem_read(arm.body, 20)) == bytes(20)


@pytest.mark.parametrize("fault", ["reverse", "duplicate", "wrong_id", "wrong_kind", "wrong_version",
    "bad_crc", "wrong_connection", "timeout", "backward_time", "wrong_boot", "wrong_operation",
    "short", "long", "reserved", "pending_success"])
def test_control_rejection_poisons_partial_message(arm, fault):
    body = reply(3, mode=2, session=8)
    packets = frames(2, 42, body)
    arm.begin(kind=2, operation=3)
    first, second = packets
    if fault == "reverse": first = packets[1]
    if fault == "duplicate": second = first
    if fault == "wrong_id": second = frames(2, 43, body)[1]
    if fault == "wrong_kind": second = seal(second[:2] + b"\x01" + second[3:18])
    if fault == "wrong_version": second = seal(second[:1] + b"\x02" + second[2:18])
    if fault == "bad_crc": second = second[:-1] + bytes([second[-1] ^ 1])
    if fault == "short": second = second[:-1]
    if fault == "long": second += b"\0"
    if fault == "wrong_boot": first, second = frames(2, 42, reply(3, mode=2, session=8, boot=BOOT ^ 1))
    if fault == "wrong_operation": first, second = frames(2, 42, reply(4, mode=2, session=8))
    if fault == "reserved": first, second = frames(2, 42, body[:-1] + b"\x01")
    if fault == "pending_success": first, second = frames(2, 42, reply(3, mode=1, session=8))
    assert arm.feed(first) == (2 if fault == "reverse" else 0)
    assert arm.feed(second, connection=8 if fault == "wrong_connection" else 7,
                    now=1101 if fault == "timeout" else 99 if fault == "backward_time" else 102) == 2
    assert bytes(arm.uc.mem_read(arm.body, 20)) == bytes(20)
    assert arm.feed(packets[0]) == 2 and arm.feed(packets[1]) == 2


def test_fragment_deadline_wrap_boundary_and_invalid_begin(arm):
    data = frames(1, 42, request())
    arm.begin(now=0xFFFFFFF0)
    assert arm.feed(data[0], now=0x10) == 0
    assert arm.feed(data[1], now=(0xFFFFFFF0 + 1000) & 0xFFFFFFFF) == 1
    for overrides in (dict(boot=0), dict(id=0), dict(connection=0), dict(kind=3), dict(operation=0)):
        arm.begin(**overrides)
        assert arm.feed(data[0]) == 2


@pytest.mark.parametrize("kind,body", [
    (1, request(0)), (1, request(5)), (1, request(boot=0)), (1, request(session=1)),
    (1, request(sequence=1)), (1, request(4)), (1, request(4, session=1)), (1, request(4, sequence=1)),
    (2, reply(3, mode=1, session=1)), (2, reply(2, mode=2, session=1)), (2, reply(4, mode=2)),
    (2, reply(mode=5)), (2, reply(result=5)), (2, reply(charging=2)),
    (2, reply(mode=2, session=1, charging=1))])
def test_invalid_body_cannot_be_encoded(arm, kind, body):
    assert arm.pack(kind, 42, body) is None


def test_motion_representation_and_every_single_bit_error(arm):
    xyz = (-32768, 8005, 32767)
    expected = seal(b"\x57\x01\x03\0" + struct.pack("<IIhhh", 8, 99, *xyz))
    assert arm.call("ww_pack_motion", 8, 99, arm.raw_input(struct.pack("<hhh", *xyz)), arm.out)
    assert bytes(arm.uc.mem_read(arm.out, 20)) == expected
    for bit in range(160):
        altered = bytearray(expected); altered[bit // 8] ^= 1 << (bit % 8)
        assert not arm.call("ww_motion_valid", arm.raw_input(bytes(altered)), 20, 8)
    assert arm.call("ww_motion_valid", arm.raw_input(expected), 20, 8)
    assert not arm.call("ww_motion_valid", arm.raw_input(expected), 20, 9)
    for session, sequence in [(0, 1), (1, 0)]:
        assert not arm.call("ww_pack_motion", session, sequence, arm.raw_input(bytes(6)), arm.out)


@pytest.fixture(scope="module")
def swift(tmp_path_factory):
    compiler = os.environ.get("WHIP_SWIFTC") or shutil.which("swiftc")
    if not compiler: pytest.skip("Swift compiler required")
    work = tmp_path_factory.mktemp("wire-swift")
    main = work / "main.swift"
    main.write_text('''import Foundation
let cases = try JSONSerialization.jsonObject(with: FileHandle.standardInput.readDataToEndOfFile()) as! [[String: Any]]
var results: [[String: Any]] = []
for c in cases {
    let kind = UnifiedWire.Kind(rawValue: UInt8(c["kind"] as! Int))!
    if kind == .motion {
        let xyz = c["xyz"] as! [Int]
        let value = UnifiedWire.Motion(session: UInt32(c["session"] as! UInt64),
            sequence: UInt32(c["sequence"] as! UInt64), x: Int16(xyz[0]), y: Int16(xyz[1]), z: Int16(xyz[2]))
        var output: [String: Any] = [:]
        do { output["frame"] = try UnifiedWire.motion(value) } catch { output["frame"] = NSNull() }
        do {
            let decoded = try UnifiedWire.decodeMotion((c["frame"] as! [Int]).map { UInt8($0) }, session: value.session)
            output["decoded"] = [Int(decoded.x), Int(decoded.y), Int(decoded.z)]
        } catch { output["decoded"] = NSNull() }
        results.append(output)
        continue
    }
    let id = UInt32(c["id"] as! UInt64), body = (c["body"] as! [Int]).map { UInt8($0) }
    var result: [String: Any] = [:]
    do { result["frames"] = try UnifiedWire.control(kind: kind, requestID: id, body: body) }
    catch { result["frames"] = NSNull() }
    var r = try UnifiedWire.Receiver(kind: kind, operation: UnifiedWire.Operation(rawValue: UInt8(c["op"] as! Int))!,
        requestID: id, connection: UInt32(c["connection"] as! UInt64), bootID: UInt64(c["boot"] as! String)!,
        now: UInt32(c["start"] as! UInt64))
    var states: [Int] = []
    for a in c["actions"] as! [[String: Any]] {
        do {
            let value = try r.feed((a["frame"] as! [Int]).map { UInt8($0) },
                connection: UInt32(a["connection"] as! UInt64), now: UInt32(a["now"] as! UInt64))
            states.append(value == nil ? 0 : 1)
            if let value { result["body"] = value }
        } catch { states.append(2) }
    }
    result["states"] = states
    results.append(result)
}
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: results))
''')
    binary = work / "wire"
    command = [compiler]
    if os.environ.get("WHIP_SWIFT_SDKROOT"):
        command += ["-sdk", os.environ["WHIP_SWIFT_SDKROOT"]]
    result = subprocess.run([*command, "-module-cache-path", str(work / "modules"),
                             str(ROOT / "ios/R02Ring/Health/UnifiedWire.swift"), str(main),
                             "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


def test_actual_swift_and_arm_share_control_frames_and_rejection_states(arm, swift):
    rng = random.Random(0x5757)
    cases, expected = [], []
    for index in range(240):
        kind = 1 + (index % 2); op = 1 + (index // 2) % 4
        id, boot = rng.randint(1, 2**32 - 1), rng.randint(1, 2**64 - 1)
        session, sequence = rng.randint(1, 2**32 - 1), rng.randint(1, 2**32 - 1)
        body = (request(op, boot, session if op == 4 else 0, sequence if op == 4 else 0) if kind == 1
                else reply(op, mode=2 if op in (3, 4) else 0, boot=boot, session=session))
        packets = frames(kind, id, body)
        connection = 7; times = [101, 102]
        expected_op, expected_boot = op, boot
        fault = index % 10
        if fault == 1: packets.reverse()
        if fault == 2: packets[1] = packets[0]
        if fault == 3: packets[1] = frames(kind, id ^ 1, body)[1]
        if fault == 4: times[1] = 1101
        if fault == 5: connection = 8
        if fault == 6: expected_boot ^= 1
        if fault == 7: expected_op = 1 + op % 4
        if fault == 8: packets[1] = bytes([packets[1][0] ^ 1]) + packets[1][1:]
        assert arm.pack(kind, id, body) == frames(kind, id, body)
        arm.begin(kind=kind, id=id, boot=expected_boot, operation=expected_op)
        states = [arm.feed(packets[i], connection=connection, now=times[i]) for i in range(2)]
        cases.append(dict(kind=kind, id=id, body=list(body), op=expected_op, boot=str(expected_boot),
            connection=7, start=100, actions=[dict(frame=list(packets[i]), connection=connection, now=times[i])
                                             for i in range(2)]))
        value = dict(frames=[list(p) for p in frames(kind, id, body)], states=states)
        if states[-1] == 1: value["body"] = list(body)
        expected.append(value)
    got = json.loads(subprocess.check_output([str(swift)], input=json.dumps(cases), text=True))
    assert got == expected


def test_actual_swift_and_arm_motion_parity_and_corruption(arm, swift):
    rng = random.Random(0x8005)
    cases, expected = [], []
    for i in range(256):
        session, sequence = rng.randint(1, 2**32-1), rng.randint(1, 2**32-1)
        xyz = [rng.randint(-32768, 32767) for _ in range(3)]
        raw = seal(b"\x57\x01\x03\0" + struct.pack("<IIhhh", session, sequence, *xyz))
        assert arm.call("ww_pack_motion", session, sequence,
                        arm.raw_input(struct.pack("<hhh", *xyz)), arm.out)
        assert bytes(arm.uc.mem_read(arm.out, 20)) == raw
        incoming = bytearray(raw)
        if i % 2:
            bit = i % 160; incoming[bit // 8] ^= 1 << (bit % 8)
        valid = arm.call("ww_motion_valid", arm.raw_input(bytes(incoming)), 20, session)
        cases.append(dict(kind=3, session=session, sequence=sequence, xyz=xyz, frame=list(incoming)))
        expected.append(dict(frame=list(raw), decoded=xyz if valid else None))
    assert json.loads(subprocess.check_output([str(swift)], input=json.dumps(cases), text=True)) == expected
