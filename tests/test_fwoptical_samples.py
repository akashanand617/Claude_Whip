"""Optical sample cursor/retirement witnesses with no physical ring operation."""
from pathlib import Path
import struct

import pytest

from whip.fwcontinuity import ProofError
from whip.fwoptical_samples import StockOpticalSamplesHarness
from whip.fwoptical_dispatch import BUFFER, STATUS

STOCK = (Path(__file__).resolve().parents[1] / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()


def prepared(**kwargs):
    h = StockOpticalSamplesHarness(STOCK)
    h.configure_samples(**kwargs)
    h.payloads[0xFF] = b"\x12\x34\xab\xcd" + bytes(124)
    return h


def words(h, count=2):
    return struct.unpack("<" + "H" * count, h.uc.mem_read(BUFFER + 0xA8, count * 2))


def test_original_sample_reader_moves_cursor_and_unpacks_big_endian_words():
    h = prepared()
    assert h.read_samples() == 0
    assert h.transfers == [b"\xfe\x00"]
    assert h.receives == [(0xFF, 4, 0, 4)]
    assert h.cursor_writes == [(0x11A7A, 1, 4)]
    assert words(h) == (0x1234, 0xABCD)
    assert h.uc.mem_read(BUFFER + 0xA6, 1)[0] == 2
    assert h.sample_returns == [0] and not h.boundaries


@pytest.mark.parametrize("stage", ["write", "read", "partial_read"])
def test_original_reader_advances_cursor_before_failed_io_and_does_not_roll_back(stage):
    h = prepared(); h.uc.mem_write(BUFFER + 0xA8, b"\xa5" * 4)
    if stage == "write": h.transfer_result = 1
    else: h.read_failures[0] = (1, 2 if stage == "partial_read" else 0)
    assert h.read_samples() == 0xFFFFFFFA  # -6
    assert h.cursor_writes == [(0x11A7A, 1, 4)]
    assert h.uc.mem_read(STATUS + 0xA, 1)[0] == 4
    assert words(h) == (0xA5A5, 0xA5A5)
    assert h.uc.mem_read(BUFFER + 0xA6, 1)[0] == 0
    assert bool(h.receives) is (stage != "write")
    assert h.read_samples() == 0xFFFFFFFE  # -2: no new bytes at same cursor
    assert len(h.transfers) == 1


@pytest.mark.parametrize("old,new,layout", [(124, 0, 1), (126, 2, 1), (92, 0, 0), (94, 2, 0)])
def test_selected_wrap_uses_fixture_bytes_and_preserves_word_order(old, new, layout):
    h = prepared(old=old, new=new, layout=layout)
    assert h.read_samples() == 0
    assert h.transfers == [bytes([0xFE, old])]
    assert h.receives == [(0xFF, 4, 0, 4)]
    assert h.uc.mem_read(STATUS + 0xA, 1)[0] == new
    assert words(h) == (0x1234, 0xABCD)


@pytest.mark.parametrize("kind", [0x10, 0x30])
def test_successful_ready_helper_is_executed_not_assigned_by_test(kind):
    h = prepared(sensor_kind=kind)
    assert h.call(0x10610, BUFFER) == 0
    assert h.uc.mem_read(STATUS + 0x19, 2) == b"\x01\x01"
    assert words(h) == (0x1234, 0xABCD)
    assert {0x10610, 0x11994, 0x124C6}.issubset(h.executed)


def test_failed_read_attempt_is_latched_but_old_ready_flag_is_not_cleared():
    h = prepared(ready=1); h.read_failures[0] = (1, 0)
    assert h.call(0x10610, BUFFER) == 0xFFFFFFFA
    assert h.uc.mem_read(STATUS + 0x19, 2) == b"\x01\x01"
    before = len(h.receives)
    assert h.call(0x10610, BUFFER) == 0  # attempted flag skips the failed acquisition
    assert len(h.receives) == before


@pytest.mark.parametrize("ready", [0, 1, 2])
def test_stock_buffer_clear_is_conditional_on_ready_state(ready):
    h = prepared(ready=ready)
    h.uc.mem_write(BUFFER + 0xA6, b"\x02")
    h.uc.mem_write(BUFFER + 0xA8, b"\xa5" * 128)
    h.call(0xFBC0, BUFFER)
    assert bytes(h.uc.mem_read(BUFFER + 0xA8, 128)) == (bytes(128) if ready else b"\xa5" * 128)
    assert h.uc.mem_read(BUFFER + 0xA6, 1)[0] == (0 if ready else 2)
    assert not h.transfers and not h.receives
    assert h.uc.mem_read(STATUS + 0x1A, 1)[0] == ready


def test_literal_island_and_neighboring_reader_are_not_silently_admitted():
    h = prepared()
    for offset in (0x11B14, 0x11C9C, 0x115F4):
        with pytest.raises(ProofError, match="unreviewed execution"):
            h.call(offset)
