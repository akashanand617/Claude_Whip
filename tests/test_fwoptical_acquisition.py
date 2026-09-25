"""Original optical read/status/parser instructions, explicit peripheral fixtures."""
from pathlib import Path
import struct

import pytest

from whip.fwcontinuity import ProofError
from whip.fwoptical_acquisition import StockOpticalAcquisitionHarness, CHANNELS
from whip.fwoptical_dispatch import BUFFER, STATUS, OPTICAL, CONTEXT

STOCK = (Path(__file__).resolve().parents[1] / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()


def prepared(sensor_kind=0x10):
    h = StockOpticalAcquisitionHarness(STOCK)
    h.arrange(cached_ready=True)
    h.configure_metadata(sensor_kind=sensor_kind)
    return h


def test_actual_read_chain_replaces_status_metadata_classification_mocks():
    h = prepared()
    h.payloads[9] = bytes(range(17))
    assert h.call(0x10F56, CONTEXT) == 0
    assert h.read_requests == [(2, 3), (9, 17), (0x42, 1), (0x40, 1), (0x43, 1),
                               (0x46, 1), (0x44, 1), (0x47, 1)]
    assert h.read_returns == [0] * 8
    assert h.status_returns == h.metadata_returns == h.parser_returns == [0]
    assert h.call(0x10F06, CONTEXT) == 2  # actual short classification path
    assert bytes(h.uc.mem_read(STATUS + 0x18, 4)) == b"\x01\x00\x01\x01"
    assert {0xEDDA, 0xDCCE, 0xDC40, 0x1174C, 0x1181C, 0x106E2, 0x1085A}.issubset(h.executed)
    assert not h.boundaries  # no parsing or classification substitute was used
    assert not h.result_stores and not h.transfers  # no algorithm or TX run


@pytest.mark.parametrize("sensor_kind,status_length,data_register", [(0x10, 3, 9), (0x30, 4, 10)])
def test_selected_sensor_kinds_use_actual_status_lengths_and_metadata_registers(sensor_kind, status_length, data_register):
    h = prepared(sensor_kind)
    assert h.call(0x10F56, CONTEXT) == 0
    assert h.read_requests[:2] == [(2, status_length), (data_register, 17)]


@pytest.mark.parametrize("failed_read", range(8))
def test_any_receive_failure_can_be_hidden_by_top_level_acquisition_success(failed_read):
    h = prepared(); h.read_failures[failed_read] = (1, 0)
    assert h.call(0x10F56, CONTEXT) == 0
    assert h.read_returns[failed_read] == 0xFFFFFFFF
    assert len(h.read_returns) == 8
    assert h.parser_returns == [0]
    assert h.metadata_returns == ([0xFFFFFFFF] if failed_read == 1 else [0])
    assert h.status_returns == ([0xFFFFFFFF] if failed_read == 0 else [0])
    assert bytes(h.uc.mem_read(STATUS + 0x18, 4)) == b"\x01\x00\x01\x01"
    # Read/parsed flags and top-level zero do not establish successful data I/O.


@pytest.mark.parametrize("delivered", [0, 1, 2])
def test_status_reader_copies_partial_or_zero_initialized_bytes_even_on_error(delivered):
    h = prepared(); h.payloads[2] = b"\x01\x23\x45\x67"
    h.read_failures[0] = (1, delivered)
    assert h.call(0x10834, STATUS) == 0
    assert h.status_returns == [0xFFFFFFFF]
    expected = h.payloads[2][:delivered] + bytes(3 - delivered)
    assert bytes(h.uc.mem_read(STATUS + 8, 2)) == expected[:2]
    assert bytes(h.uc.mem_read(STATUS + 11, 2)) == expected[2:] * 2
    assert h.uc.mem_read(STATUS + 0x1B, 1)[0] == 1


def test_status_error_bit_and_bus_read_failure_are_distinct():
    h = prepared(); h.payloads[2] = b"\x10\x00\x00\x00"
    assert h.call(0x10F56, CONTEXT) == 0xFFFFFFFF
    assert h.read_returns == [0] and h.status_returns == [0]
    assert not h.parser_returns and not h.metadata_returns
    # A successful fixture read carrying bit 0x10 causes an acquisition error.
    # A failed read delivering zero bytes did NOT cause that error above.


@pytest.mark.parametrize("fault", ["mutex", "not_ready", "busy"])
def test_failed_read_wrapper_still_allows_cached_ready_processing(fault):
    h = prepared()
    if fault == "mutex": h.mutex_available = False
    elif fault == "not_ready": h.bus_ready = False
    else: h.bus_busy = True
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.acquisition_statuses == [0]
    assert h.read_returns and set(h.read_returns) == {0xFFFFFFFF}
    assert not h.receives
    assert bytes(h.uc.mem_read(OPTICAL + 2, 1)) == b"\x48"
    assert h.result_stores
    # Algorithms and ready provenance are STILL synthetic. This is failure
    # propagation evidence, not a physical stale-heart-rate observation.


def test_already_parsed_cached_status_can_return_success_without_any_read():
    h = prepared(); h.configure_metadata(parsed=True, status_read=True)
    before = bytes(h.uc.mem_read(BUFFER, 0x500))
    assert h.call(0x10F56, CONTEXT) == 0
    assert not h.read_requests and not h.receives
    assert h.parser_returns == [0]
    assert bytes(h.uc.mem_read(BUFFER, 0x500)) == before


def test_failed_metadata_read_preserves_old_values_but_marks_parser_complete():
    h = prepared(); h.configure_metadata(status_read=True)
    h.uc.mem_write(BUFFER + 0xA2, struct.pack("<H", 0x0203))
    h.read_failures[0] = (1, 0)
    assert h.call(0x106E2, BUFFER) == 0
    assert h.metadata_returns == [0xFFFFFFFF]
    # Old packed value is converted by the parser despite the failed refresh.
    assert struct.unpack("<H", h.uc.mem_read(BUFFER + 0xA2, 2))[0] == 103
    assert h.uc.mem_read(STATUS + 0x18, 1)[0] == 1
    assert bytes(h.uc.mem_read(CHANNELS[0] + 6, 1)) == b"\x2a"


def test_completion_operation_is_a_read_not_an_optical_control_write():
    h = prepared(); h.configure_metadata(parsed=True, status_read=True)
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.read_requests == [(0x40, 24)]
    assert h.receives == [(0x40, 24, 0, 24)]
    assert not h.transfers  # actual RX wrapper, never EE12/DBCA TX
    assert bytes(h.uc.mem_read(STATUS + 0x18, 4)) == bytes(4)


def test_all_read_failures_can_reach_real_hr_stores_with_fixture_algorithm_and_ready_state():
    h = prepared()
    h.read_failures = {index: (1, 0) for index in range(9)}
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert len(h.receives) == 9  # status, metadata, six controls, completion read
    assert h.read_returns == [0xFFFFFFFF] * 9
    assert h.acquisition_statuses == [0] and h.parser_returns == [0]
    assert h.metadata_returns == h.status_returns == [0xFFFFFFFF]
    assert bytes(h.uc.mem_read(OPTICAL + 2, 1)) == b"\x48"
    assert h.result_stores and h.optical_state() == 2
    assert not h.transfers and not h.optical_starts
    assert {0x106E2, 0x1085A, 0xEDDA}.isdisjoint(offset for offset, _ in h.boundaries)
    assert 0xEFF8 in {offset for offset, _ in h.boundaries}  # still synthetic!


def test_mutex_release_failure_is_not_reported_by_original_read_wrapper():
    h = prepared(); h.mutex_give_ok = False
    assert h.call(0x10834, STATUS) == 0
    assert h.mutex_events == ["take", "give"]
    assert h.status_returns == h.read_returns == [0]


def test_cached_status_flags_are_not_a_generational_identity():
    h = prepared(); h.configure_metadata(parsed=True, status_read=True)
    assert h.call(0x10F56, CONTEXT) == 0
    assert h.call(0x10F56, CONTEXT) == 0
    assert h.parser_returns == [0, 0] and not h.receives
    # Nothing in these actual paths assigns an acquisition/job identity or
    # distinguishes the two calls. Never set measured=True from return zero.


@pytest.mark.parametrize("offset", [0x107F4, 0x18D7C, 0x10244, 0x13720])
def test_unselected_literals_conversion_classification_and_peripheral_body_stay_closed(offset):
    h = prepared()
    with pytest.raises(ProofError, match="unreviewed execution"):
        h.call(offset)


def test_image_and_receive_fixtures_fail_closed_on_unreviewed_inputs():
    bad = bytearray(STOCK); bad[0x11784] ^= 1
    with pytest.raises(ValueError, match="exact pinned stock"):
        StockOpticalAcquisitionHarness(bytes(bad))
    h = prepared()
    with pytest.raises(ValueError, match="unreviewed optical sensor-kind"):
        h.configure_metadata(sensor_kind=0x20)
    h.payloads[2] = b"\x00"
    with pytest.raises(ProofError, match="short optical fixture payload"):
        h.call(0x10834, STATUS)
