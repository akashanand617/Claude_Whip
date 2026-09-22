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


def test_stop_command_matches_the_firmware_pair_for_a1_04():
    """
    The A1 handler pairs 0x04 (enable sensor bit 0x800) with 0x05 (disable
    0x800). 0x02 clears a different bit, which is why the optical sensor stayed
    on after every capture. The stop sequence must lead with 0x05.
    """
    assert protocol.STOP_RAW_SENSOR == bytes.fromhex("a105000000000000000000000000" + "00a6")
    assert protocol.STOP_RAW_SENSOR_PACKETS[0] is protocol.STOP_RAW_SENSOR
    assert protocol.STOP_RAW_SENSOR_PACKETS[1] is protocol.DISABLE_RAW_SENSOR


def test_battery_packet_has_no_subdata():
    packet = protocol.BATTERY_PACKET
    assert packet[0] == 0x03
    assert all(b == 0 for b in packet[1:-1])


def test_quiet_hr_disables_the_sensor_and_timer_not_starts_them():
    # sub_050dc: 69 01 xx enables bit 1; 69 06 02 only stops reporting;
    # 69 06 04 reaches disable(1) and then stops the report timer.
    expected = protocol.make_packet(0x69, bytes([0x06, 0x04]))
    assert protocol.QUIET_SENSOR_PACKETS[0] == expected
    assert expected[-1] == 0x73
    assert all(packet[:2] != bytes([0x69, 0x01])
               for packet in protocol.QUIET_SENSOR_PACKETS)


def test_led_probe_uses_the_same_corrected_hr_stop():
    from probe.ledtest import STEPS

    _, command, sub_data, _ = next(step for step in STEPS if step[0] == "stop heart rate")
    assert protocol.make_packet(command, sub_data) == protocol.QUIET_SENSOR_PACKETS[0]


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
