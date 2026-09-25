import struct

import pytest

from probe import ble_recovery as recovery_cli
from whip import ble_recovery as recovery


def hci_event(event: int, payload: bytes) -> bytes:
    return bytes((recovery.HCI_EVENT_PKT, event, len(payload))) + payload


def le_event(subevent: int, payload: bytes) -> bytes:
    return hci_event(recovery.EVT_LE_META_EVENT, bytes((subevent,)) + payload)


def test_address_round_trip_and_validation():
    assert recovery.address_to_le("30:32:41:33:CC:07") == bytes.fromhex("07cc33413230")
    assert recovery.address_from_le(bytes.fromhex("07cc33413230")) == "30:32:41:33:CC:07"
    with pytest.raises(ValueError):
        recovery.address_to_le("30:32:41")
    with pytest.raises(ValueError):
        recovery.address_to_le("30:32:41:33:CC:GG")


def test_create_connection_targets_exact_peer_and_has_conservative_timing():
    command = recovery.create_connection_command("30:32:41:33:CC:07", 0)
    assert command[:4] == bytes.fromhex("010d2019")
    parameters = command[4:]
    assert parameters[:6] == struct.pack("<HHBB", 0x0060, 0x0060, 0, 0)
    assert parameters[6:12] == bytes.fromhex("07cc33413230")
    assert len(parameters) == 25


def test_scan_commands_are_active_duplicate_preserving_and_bounded():
    params = recovery.set_scan_parameters_command()
    enable = recovery.set_scan_enable_command(True)
    assert params == bytes.fromhex("010b200701600060000000")
    assert enable == bytes.fromhex("010c20020100")
    with pytest.raises(ValueError):
        recovery.set_scan_parameters_command(interval=0x0010, window=0x0020)


def test_parse_legacy_ring_advertisement_with_uuid_and_name():
    uart_le = bytes.fromhex("9ecadc240ee5a9e093f3a3b5f0ff406e")
    # Complete local name plus the canonical UART UUID encoded little-endian.
    data = bytes((9, 0x09)) + b"R02_CC07" + bytes((17, 0x07)) + uart_le
    body = bytes((1, 0, 0)) + recovery.address_to_le("30:32:41:33:CC:07")
    body += bytes((len(data),)) + data + struct.pack("b", -42)
    reports = recovery.parse_advertisements(
        le_event(recovery.EVT_LE_ADVERTISING_REPORT, body)
    )
    assert len(reports) == 1
    report = reports[0]
    assert report.address == "30:32:41:33:CC:07"
    assert report.connectable and not report.directed
    assert report.local_name == "R02_CC07"
    assert report.service_uuids == (recovery.UART_SERVICE_UUID,)
    assert report.strong_ring_identity


def test_parse_directed_advertisement_corebluetooth_may_not_surface():
    body = bytes((1, 1, 1)) + recovery.address_to_le("53:20:0D:60:4C:8F")
    body += bytes((0,)) + recovery.address_to_le("68:5E:DD:8D:A2:15") + struct.pack("b", -51)
    report = recovery.parse_advertisements(
        le_event(recovery.EVT_LE_DIRECTED_ADVERTISING_REPORT, body)
    )[0]
    assert report.address == "53:20:0D:60:4C:8F"
    assert report.direct_address == "68:5E:DD:8D:A2:15"
    assert report.connectable and report.directed
    assert report.data == b""


def test_parse_connection_complete():
    body = struct.pack("<BHB", 0, 0x0042, 0)  # status, handle, central role
    body += bytes((1,)) + recovery.address_to_le("53:20:0D:60:4C:8F")
    body += struct.pack("<HHHB", 0x0028, 0, 0x01F4, 0)
    complete = recovery.parse_connection_complete(
        le_event(recovery.EVT_LE_CONN_COMPLETE, body)
    )
    assert complete == recovery.ConnectionComplete(
        status=0,
        handle=0x0042,
        address="53:20:0D:60:4C:8F",
        address_type=1,
        interval=0x0028,
        latency=0,
        supervision_timeout=0x01F4,
    )


def test_command_results_cover_status_and_complete():
    status = hci_event(recovery.EVT_CMD_STATUS,
                       bytes((0, 1)) + struct.pack("<H", recovery.OP_LE_CREATE_CONN))
    complete = hci_event(recovery.EVT_CMD_COMPLETE,
                         bytes((1,)) + struct.pack("<H", recovery.OP_LE_SET_SCAN_ENABLE) + bytes((0,)))
    assert recovery.command_result(status) == (recovery.OP_LE_CREATE_CONN, 0)
    assert recovery.command_result(complete) == (recovery.OP_LE_SET_SCAN_ENABLE, 0)


def test_disconnect_is_a_link_command_not_an_att_or_dfu_write():
    assert recovery.disconnect_command(0x0042) == bytes.fromhex("01060403420013")
    with pytest.raises(ValueError):
        recovery.disconnect_command(0x1000)


def test_malformed_events_are_ignored_instead_of_partially_trusted():
    assert recovery.parse_advertisements(b"\x04\x3e\x20\x02") == ()
    assert recovery.parse_connection_complete(b"\x04\x3e\x20\x01") is None


class ScriptedHCI(recovery.RawHCI):
    def __init__(self, events=()):
        super().__init__(0)
        self.events = iter(events)
        self.commands = []

    def command(self, packet, opcode, timeout=2.0):
        self.commands.append((opcode, packet))

    def receive(self, timeout):
        return next(self.events, None)


def test_connect_timeout_always_cancels_controller_initiation():
    report = recovery.Advertisement("30:32:41:33:CC:07", 0, 0, -40, b"")
    controller = ScriptedHCI()
    with pytest.raises(recovery.HCIError, match="timed out"):
        controller.connect(report, timeout=0)
    assert [opcode for opcode, _ in controller.commands] == [
        recovery.OP_LE_CREATE_CONN,
        recovery.OP_LE_CREATE_CONN_CANCEL,
    ]


def test_successful_connect_does_not_send_cancel():
    address = "30:32:41:33:CC:07"
    body = struct.pack("<BHB", 0, 0x0042, 0)
    body += bytes((0,)) + recovery.address_to_le(address)
    body += struct.pack("<HHHB", 0x0028, 0, 0x01F4, 0)
    event = le_event(recovery.EVT_LE_CONN_COMPLETE, body)
    controller = ScriptedHCI((event,))
    complete = controller.connect(recovery.Advertisement(address, 0, 0, -40, b""), timeout=1)
    assert complete.handle == 0x0042
    assert [opcode for opcode, _ in controller.commands] == [recovery.OP_LE_CREATE_CONN]


def test_darwin_latch_parser_requires_exact_identifier_and_explicit_execution():
    parser = recovery_cli.build_parser()
    args = parser.parse_args([
        "darwin-wait",
        "--identifier", "3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2",
        "--seconds", "300",
        "--execute",
    ])
    assert args.command == "darwin-wait"
    assert args.identifier == "3C2FA77E-1BE3-A0C5-0DD5-DB6A3AD452B2"
    assert args.seconds == 300
    assert args.execute is True
