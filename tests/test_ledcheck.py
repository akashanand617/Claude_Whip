import asyncio

import pytest

from probe.ledcheck import (accel_freshness, ce_exchange, motion_control_packet,
                            optical_stop_packet, sensor_read_packet)
from whip import protocol


def test_optical_stop_targets_only_vc30f_stop_register():
    packet = optical_stop_packet()
    assert bytes(packet) == bytes.fromhex("ce 02 33 7b 01 00 00 00 00 00 00 00 00 00 00 7f")
    assert packet[4] == 1  # exactly one register byte; no adjacent registers
    assert packet[5] == 0  # STOP, never RESET (0xa5) or RUN (0x5a)
    assert packet[-1] == sum(packet[:-1]) % 256


def test_motion_control_is_fixed_volatile_submode_and_has_matching_disable():
    assert bytes(motion_control_packet(True)) == bytes.fromhex(
        "3b 02 01 03 00 00 00 00 00 00 00 00 00 00 00 41")
    assert bytes(motion_control_packet(False)) == bytes.fromhex(
        "3b 02 01 00 00 00 00 00 00 00 00 00 00 00 00 3e")
    with pytest.raises(ValueError):
        motion_control_packet(2)


def test_freshness_distinguishes_repeated_packets_from_live_values():
    old = bytes.fromhex("a103000100020003")
    new = bytes.fromhex("a103000200020003")
    result = accel_freshness([(0, old), (0.04, new), (1, new), (60, new)], 0)
    assert result["last_accel_change_phase_s"] == 0.04
    assert result["unchanged_accel_tail_s"] == 59.96


def test_register_reads_are_fixed_and_non_consuming():
    assert sensor_read_packet("stk_xyz")[:5] == bytes([0xce, 1, 0x1f, 2, 6])
    with pytest.raises(ValueError):
        sensor_read_packet("fifo_data")


def test_queued_reply_is_rejected_before_another_request():
    async def check():
        replies = asyncio.Queue()
        replies.put_nowait((0, bytes(protocol.make_packet(0xce))))
        with pytest.raises(RuntimeError, match="pending"):
            await ce_exchange(None, replies, optical_stop_packet())
    asyncio.run(check())


def test_missing_reply_aborts_instead_of_reusing_another_response():
    class Client:
        async def write_gatt_char(self, *args, **kwargs):
            pass
    async def check():
        with pytest.raises(TimeoutError, match="stale reply"):
            await ce_exchange(Client(), asyncio.Queue(), optical_stop_packet(), timeout=0.001)
    asyncio.run(check())


def test_wrong_diagnostic_reply_is_rejected():
    async def check():
        replies = asyncio.Queue()
        class Client:
            async def write_gatt_char(self, *args, **kwargs):
                replies.put_nowait((0, bytes(protocol.make_packet(0xcd))))
        with pytest.raises(RuntimeError, match="Invalid"):
            await ce_exchange(Client(), replies, optical_stop_packet())
    asyncio.run(check())
