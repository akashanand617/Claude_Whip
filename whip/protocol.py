"""
Colmi R02 BLE protocol constants and packet construction.

Protocol derived from tahnok/colmi_r02_client (connection + packet format) and
edgeimpulse/example-data-collection-colmi-r02 (raw sensor streaming).

Every command is a 16 byte packet: command byte, up to 14 bytes of sub data,
then a checksum which is the sum of the preceding bytes mod 256.
"""

from __future__ import annotations

# nRF UART service. The ring speaks its entire command protocol over this.
UART_SERVICE_UUID = "6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # we write here
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # ring notifies here

DEVICE_INFO_UUID = "0000180A-0000-1000-8000-00805F9B34FB"
DEVICE_HW_UUID = "00002A27-0000-1000-8000-00805F9B34FB"
DEVICE_FW_UUID = "00002A26-0000-1000-8000-00805F9B34FB"

PACKET_SIZE = 16

CMD_BATTERY = 0x03
CMD_RAW_SENSOR = 0xA1

# Parameters to CMD_RAW_SENSOR. 0x04 and 0x02 are the only two confirmed by a
# working implementation; everything else in the byte space is unexplored and
# is what probe/sweep.py is for.
RAW_ENABLE_ALL = 0x04
RAW_DISABLE = 0x02

# Subtypes appearing in byte 1 of an 0xA1 notification.
SUBTYPE_SPO2 = 0x01
SUBTYPE_PPG = 0x02
SUBTYPE_ACCEL = 0x03

SUBTYPE_NAMES = {
    SUBTYPE_SPO2: "spo2",
    SUBTYPE_PPG: "ppg",
    SUBTYPE_ACCEL: "accel",
}

# Ring advertising names seen in the wild.
KNOWN_RING_NAMES = ("R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10")


def checksum(packet: bytes | bytearray) -> int:
    """Sum of all bytes, mod 256."""
    return sum(packet) & 0xFF


def make_packet(command: int, sub_data: bytes | bytearray | None = None) -> bytearray:
    """Build a well formed 16 byte command packet with a trailing checksum."""
    if not 0 <= command <= 0xFF:
        raise ValueError(f"command must fit in a byte, got {command}")

    packet = bytearray(PACKET_SIZE)
    packet[0] = command

    if sub_data:
        if len(sub_data) > PACKET_SIZE - 2:
            raise ValueError(f"sub_data must be at most {PACKET_SIZE - 2} bytes, got {len(sub_data)}")
        packet[1 : 1 + len(sub_data)] = sub_data

    packet[-1] = checksum(packet[:-1])
    return packet


def raw_sensor_packet(param: int) -> bytearray:
    """Build a raw sensor control packet. param 0x04 starts, 0x02 stops."""
    return make_packet(CMD_RAW_SENSOR, bytes([param]))


ENABLE_RAW_SENSOR = raw_sensor_packet(RAW_ENABLE_ALL)
DISABLE_RAW_SENSOR = raw_sensor_packet(RAW_DISABLE)
BATTERY_PACKET = make_packet(CMD_BATTERY)


def parse_battery(packet: bytes | bytearray) -> tuple[int, bool]:
    """Return (battery_percent, is_charging) from an 0x03 reply."""
    return packet[1], bool(packet[2])
