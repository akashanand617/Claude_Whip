import pytest

from whip import protocol


def test_packet_is_sixteen_bytes():
    assert len(protocol.make_packet(0xA1, b"\x04")) == protocol.PACKET_SIZE


def test_checksum_is_sum_of_preceding_bytes():
    packet = protocol.make_packet(0xA1, b"\x04")
    assert packet[-1] == sum(packet[:-1]) & 0xFF


def test_enable_command_matches_known_working_bytes():
    """
    The Edge Impulse collector builds its enable command from the hex string
    "a104". If our packet ever stops matching that, raw streaming breaks.
    """
    expected = bytearray(16)
    expected[0] = 0xA1
    expected[1] = 0x04
    expected[-1] = sum(expected[:-1]) & 0xFF

    assert protocol.ENABLE_RAW_SENSOR == expected


def test_disable_command():
    assert protocol.DISABLE_RAW_SENSOR[0] == 0xA1
    assert protocol.DISABLE_RAW_SENSOR[1] == 0x02


def test_battery_packet_has_no_subdata():
    packet = protocol.BATTERY_PACKET
    assert packet[0] == 0x03
    assert all(b == 0 for b in packet[1:-1])


def test_rejects_oversized_subdata():
    with pytest.raises(ValueError):
        protocol.make_packet(0xA1, b"\x00" * 15)


def test_rejects_bad_command():
    with pytest.raises(ValueError):
        protocol.make_packet(256)


def test_parse_battery():
    packet = bytearray(16)
    packet[0] = 0x03
    packet[1] = 64
    packet[2] = 0
    assert protocol.parse_battery(packet) == (64, False)

    packet[2] = 1
    assert protocol.parse_battery(packet) == (64, True)
