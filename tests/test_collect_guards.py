"""
The collector refuses the wrong ring and stock firmware, and will not cue a
gesture until motion packets are actually arriving.
"""
import asyncio

import pytest

from probe import collect
from whip import capture, protocol


def _info(name, firmware):
    return capture.DeviceInfo(address="X", name=name, firmware=firmware)


def test_the_project_ring_on_gesture_firmware_passes():
    collect.check_ring(_info("R02_CC07", "RT02CR_3.12.07_260514"), "R02_CC07", allow_stock=False)
    collect.check_ring(_info("COLMI R02_CC07", "RT02CR_3.12.07_260514"), "R02_CC07", allow_stock=False)


def test_another_unit_is_refused_unless_any_ring():
    with pytest.raises(SystemExit, match="not 'R02_CC07'"):
        collect.check_ring(_info("COLMI R02_D507", "RT02CR_3.12.07_260514"), "R02_CC07", allow_stock=False)
    collect.check_ring(_info("COLMI R02_D507", "RT02CR_3.12.07_260514"), None, allow_stock=False)


def test_stock_firmware_is_refused_unless_allowed():
    with pytest.raises(SystemExit, match="stock"):
        collect.check_ring(_info("R02_CC07", "RT02CR_3.12.02_260824"), "R02_CC07", allow_stock=False)
    collect.check_ring(_info("R02_CC07", "RT02CR_3.12.02_260824"), "R02_CC07", allow_stock=True)
    assert protocol.is_expected_ring("COLMI R02_CC07") and not protocol.is_expected_ring("COLMI R02_D507")


def test_no_motion_packets_aborts_before_any_cue():
    rec = capture.Capture(device=_info("R02_CC07", "RT02CR_3.12.07_260514"), started_wall=0.0,
                          param=protocol.RAW_ENABLE_ALL, label="t")
    rec.records.append((0.1, bytes([0xA1, 0xFF]) + bytes(14)))          # the stock-firmware error reply
    with pytest.raises(SystemExit, match="not streaming"):
        asyncio.run(collect.wait_for_data(rec, seconds=0.3, min_packets=3))
    for i in range(3):
        rec.records.append((0.2 + i * 0.04, bytes([0xA1, 0x03]) + bytes(14)))
    asyncio.run(collect.wait_for_data(rec, seconds=0.3, min_packets=3))
