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

# QRing DFU service, used for firmware transfer. Present on this ring; it is
# what the browser flasher drives.
DFU_SERVICE_UUID = "de5bf728-d711-4e47-af26-65e3012a5dc7"
DFU_NOTIFY_CHAR_UUID = "de5bf729-d711-4e47-af26-65e3012a5dc7"
DFU_WRITE_CHAR_UUID = "de5bf72a-d711-4e47-af26-65e3012a5dc7"

DEVICE_INFO_UUID = "0000180A-0000-1000-8000-00805F9B34FB"
DEVICE_HW_UUID = "00002A27-0000-1000-8000-00805F9B34FB"
DEVICE_FW_UUID = "00002A26-0000-1000-8000-00805F9B34FB"

PACKET_SIZE = 16

CMD_BATTERY = 0x03
CMD_RAW_SENSOR = 0xA1

# Parameters to CMD_RAW_SENSOR, read from the firmware's A1 handler
# (sub_020bc in rt02cr-25hz.bin, see docs/HARDWARE.md "Optical front end").
# Each parameter is a sub-command; start and stop come in matched pairs that
# enable and disable a bit in the sensor task's mask:
#
#   0x01 start   PPG raw mode, sensor bit 0x40      0x02 stop -> clears 0x40
#   0x04 start   motion raw mode, sensor bit 0x800  0x05 stop -> clears 0x800
#   0x06 start   like 0x01                          0x08 stop -> clears 0x40
#   0x07         like 0x01 at 1 Hz with a countdown  0x03 one-shot report
#
# `A1 02` after `A1 04` therefore leaves bit 0x800 set, the optical sensor keeps
# running and its LEDs stay lit until the ring is power-cycled. That was the
# "stuck LED" that a charger tap used to fix. `A1 05` is the real stop.
RAW_ENABLE_ALL = 0x04
RAW_STOP = 0x05
RAW_DISABLE = 0x02  # stops the PPG raw modes (0x01/0x06/0x07); harmless after 0x04

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

# The unit this project's data comes from. A 48-gesture session was recorded
# against a different ring (COLMI R02_D507, stock firmware) that happened to
# be advertising while ours was not: the stream carried nothing and every
# mark was empty. Tools that record refuse any other unit unless told.
EXPECTED_RING = "R02_CC07"


def is_expected_ring(name: str | None, expected: str = EXPECTED_RING) -> bool:
    """Whether an advertised or GATT name is the project's unit, vendor prefix or not."""
    return bool(name) and name.strip().upper().endswith(expected.upper())


def looks_like_ring(name: str | None) -> bool:
    """
    Whether an advertised name plausibly belongs to a Colmi-family ring.

    Do not use startswith here. Real units advertise as "COLMI R02_CC07", with
    the vendor first and a per-unit suffix, so a prefix match on "R02" silently
    misses the ring that is sitting right in front of you. Matching anywhere in
    the string costs nothing and catches the naming variants these rings ship
    with.
    """
    if not name:
        return False
    upper = name.upper()
    return "COLMI" in upper or any(model in upper for model in KNOWN_RING_NAMES)


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
    """Build a raw sensor control packet. param 0x04 starts motion raw mode, 0x05 stops it."""
    return make_packet(CMD_RAW_SENSOR, bytes([param]))


ENABLE_RAW_SENSOR = raw_sensor_packet(RAW_ENABLE_ALL)
STOP_RAW_SENSOR = raw_sensor_packet(RAW_STOP)
DISABLE_RAW_SENSOR = raw_sensor_packet(RAW_DISABLE)
BATTERY_PACKET = make_packet(CMD_BATTERY)

# Send both, in this order, to stop streaming. `A1 05` clears the motion raw
# bit and stops the producer timer; with no sensor bit left set the firmware
# stops the optical sensor (register 0x7b <- 0xa5, 0x00) and the LEDs go out.
# `A1 02` then clears the PPG raw bit in case a 0x01/0x06/0x07 mode was used.
STOP_RAW_SENSOR_PACKETS = (STOP_RAW_SENSOR, DISABLE_RAW_SENSOR)


# Health-command probes, not a raw-stream optical-off switch. On the pinned
# 25 Hz firmware, sub_050dc routes 69 06 04 through disable(bit 1) at 0x5294
# and then stops the HR report timer. 69 01 04 is a START, not a stop, and
# 69 06 02 stops only the report timer. The legacy 0x6A probes have not been
# established as effective here. None clears the raw sensor bit 0x800.
QUIET_SENSOR_PACKETS = (
    make_packet(0x69, bytes([0x06, 0x04])),        # disable realtime HR + its timer
    make_packet(0x6A, bytes([0x01, 0x00, 0x00])),  # stop realtime heart rate
    make_packet(0x6A, bytes([0x03, 0x00, 0x00])),  # stop realtime blood oxygen
)

# These disable only the HR and SpO2 schedules (bits 0 and 1 of 0x208AB1).
# Three other schedule bits belong to 0x36, 0x38 and 0x3A. This is not a
# blanket background-optics disable; realtime requests and indicators are
# separate too. The minute tick's 0x208C4A gate is time-set, not HR enable.
DISABLE_LOGGING_PACKETS = (
    make_packet(0x16, bytes([0x02, 0x02, 0x3C])),  # disable heart-rate logging
    make_packet(0x2C, bytes([0x02, 0x02])),        # disable blood-oxygen logging
)


def parse_battery(packet: bytes | bytearray) -> tuple[int, bool]:
    """Return (battery_percent, is_charging) from an 0x03 reply."""
    return packet[1], bool(packet[2])
