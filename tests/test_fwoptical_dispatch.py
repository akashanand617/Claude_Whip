"""Optical event lifetime and actual result stores; no ring access or deployment."""
from pathlib import Path
import struct

import pytest

from tests.test_health_adapter import api, fresh, start, prove_quiet, resume  # noqa: F401
from whip.fwcontinuity import BIAS, ProofError
from whip.fwhealth_lifecycle import POST_DISABLE
from whip.fwoptical_dispatch import (
    StockOpticalDispatchHarness, CONTEXT, DRIVER_TABLE, ALGORITHM_TABLE,
    BUFFER, STATUS, CALLBACK_TABLE, OPTICAL, FLAGS, SPO2_RESULT,
)

STOCK = (Path(__file__).resolve().parents[1] / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()


def prepared(mode=0, **kwargs):
    h = StockOpticalDispatchHarness(STOCK, **kwargs)
    h.arrange(mode=mode, owner=0x80 if mode else 0x10)
    h.algorithm_fixture = 98 if mode else 72
    return h


@pytest.mark.parametrize("producer", [0xD8F0, 0xD9F8])
@pytest.mark.parametrize("accepted", [False, True])
def test_actual_gpio_or_software_producer_posts_identical_untagged_message(producer, accepted):
    h = prepared(); h.queue_accepts = accepted
    h.call(producer)
    assert h.post_attempts == [(3, 0, 0)]
    assert h.messages == ([(3, 0, 0)] if accepted else [])
    assert not h.received and not h.acquisition_statuses and not h.result_stores
    if producer == 0xD8F0:
        assert [c[0] for c in h.gpio_calls] == [
            0x1399A, 0x1396E, 0x1399A, 0x13988, 0x1399A, 0x13980,
            0x1399A, 0x1396E, 0x1399A, 0x13988]
        assert [args[1] for addr, args in h.gpio_calls if addr in (0x1396E, 0x13988)] == [0, 1, 1, 0]
        # The GPIO wrapper restores its controls even when queue send fails.
    else:
        assert not h.gpio_calls


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize("cached_ready", [False, True])
@pytest.mark.parametrize("error_bit_set", [False, True])
def test_actual_processor_ignores_acquisition_status_and_uses_cached_ready_state(mode, cached_ready, error_bit_set):
    h = prepared(mode)
    h.arrange(mode=mode, cached_ready=cached_ready, error_bit_set=error_bit_set)
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.received == [(3, 0, 0)]
    assert h.acquisition_statuses == [0xFFFFFFFF if error_bit_set else 0]
    assert (0x106E2 in [offset for offset, _ in h.boundaries]) is not error_bit_set
    assert bool(h.result_stores) == cached_ready
    if cached_ready:
        target = SPO2_RESULT if mode else OPTICAL + 2
        assert bytes(h.uc.mem_read(target, 1)) == bytes([h.algorithm_fixture])
        assert h.optical_state() == 2
        assert {0xF7A8, 0xF774, 0xF308, 0x10F56, 0x10834, 0x10FAA, 0x11216}.issubset(h.executed)
    assert bytes(h.uc.mem_read(STATUS + 0x18, 4)) == bytes(4)  # actual completion stores
    assert not h.i2c_calls and not h.transfers and not h.notifications
    # Algorithm/classification outputs are fixtures, NOT verified measurements.


@pytest.mark.parametrize("mode", [0, 1])
def test_disable_followed_by_old_event_can_restore_result_state_with_zero_owners(mode):
    h = prepared(mode); h.arrange(mode=mode, error_bit_set=True)
    h.call(POST_DISABLE, 0xFFFF)
    h.run_hub_until_fixture_empty()
    assert h.ownership() == 0 and h.optical_state() == 0
    assert h.transfers == [b"\x7b\xa5", b"\x7b\x00"]
    assert not h.result_stores
    # A producer that was delayed before posting has no origin token to check.
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.ownership() == 0 and h.optical_state() == 2
    assert h.acquisition_statuses == [0xFFFFFFFF] and h.result_stores
    assert not h.optical_starts  # Result state revived without a normal enable.
    assert len(h.transfers) == 2  # No new RUN or physical sample claimed.


@pytest.mark.parametrize("mode", [0, 1])
def test_zero_acquisition_pointer_error_is_also_ignored_before_downstream_boundary(mode):
    h = prepared(mode)
    h.uc.mem_write(DRIVER_TABLE + 0x10, bytes(4))
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.acquisition_statuses == [0xFFFFFFFE]
    assert bytes(h.uc.mem_read(CONTEXT + 0xC, 4)) == bytes(4)
    assert h.result_stores
    # The algorithm itself is intercepted; this does NOT prove its real null
    # handling or that it could return a valid result with that context.


def test_unknown_indirect_algorithm_callback_is_not_silently_executed():
    h = prepared()
    h.uc.mem_write(CALLBACK_TABLE + 8, struct.pack("<I", 0x30041))
    h.call(0xD9F8)
    with pytest.raises(ProofError, match="unreviewed execution"):
        h.run_hub_until_fixture_empty()
    assert not h.result_stores


@pytest.mark.parametrize("mode", [0, 1])
def test_unread_device_status_is_not_replaced_by_cached_fixture(mode):
    h = prepared(mode)
    h.uc.mem_write(STATUS + 0x1B, bytes(1))
    h.call(0xD9F8)
    with pytest.raises(ProofError, match="unreviewed execution"):
        h.run_hub_until_fixture_empty()
    assert not h.result_stores
    # Stops at real status read 0x1174c, not an assumed I2C success.


@pytest.mark.parametrize("state", ["quiescing", "paused", "resumed_old", "fresh_health"])
def test_compiled_ticket_predicate_can_reject_old_dispatch_only_if_original_ticket_is_retained(api, state):
    adapter = fresh(api, jobs=1); original = start(api, adapter)
    # True below is an explicitly synthetic source/provenance control, not a
    # claim that stock's ready byte or this processing event is measured.
    h = prepared(admission=lambda: api.wh_result_allowed(adapter, original, True))
    h.call(0xD9F8)
    if state != "fresh_health":
        assert api.wh_begin_quiesce(adapter, 1)
        if state in ("paused", "resumed_old"):
            prove_quiet(api, adapter)  # TEST receipts, not the physical ring.
        if state == "resumed_old":
            resume(api, adapter)
            start(api, adapter)  # new serial; keep ORIGINAL in closure
    before = bytes(h.uc.mem_read(OPTICAL, 16))
    h.run_hub_until_fixture_empty()
    allowed = state == "fresh_health"
    assert h.admissions == [allowed]
    assert bool(h.acquisition_statuses) == bool(h.result_stores) == allowed
    if not allowed:
        assert bytes(h.uc.mem_read(OPTICAL, 16)) == before
        assert not h.boundaries


def test_stamping_current_ticket_at_dequeue_wrongly_accepts_old_message(api):
    adapter = fresh(api, jobs=1); start(api, adapter)
    current = []
    h = prepared(admission=lambda: api.wh_result_allowed(adapter, current[0], True))
    h.call(0xD9F8)  # Stock queue contains no serial/generation to recover later.
    assert api.wh_begin_quiesce(adapter, 1); prove_quiet(api, adapter)
    resume(api, adapter); current.append(start(api, adapter))
    h.run_hub_until_fixture_empty()
    assert h.admissions == [True] and h.result_stores
    # This negative witness forbids implementing the binding this way.


def test_entry_check_alone_does_not_fence_a_pause_between_admission_and_result_stores(api):
    adapter = fresh(api, jobs=1); ticket = start(api, adapter)
    h = prepared(admission=lambda: api.wh_result_allowed(adapter, ticket, True))
    paused_at = []

    def interleave(uc, address, size, opaque):
        if address == BIAS + 0xF432:
            assert api.wh_begin_quiesce(adapter, 1)
            paused_at.append(address)

    h.uc.hook_add(h.u.UC_HOOK_CODE, interleave)
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert paused_at and h.admissions == [True] and h.result_stores
    assert not api.wh_result_allowed(adapter, ticket, True)
    # Stock direct stores never called the predicate again. Production needs
    # common serialization and/or final commit guards, not this entry-only demo.


@pytest.mark.parametrize("mode", [0, 1])
def test_nonmeasurement_classification_resets_algorithm_but_publishes_no_value(mode):
    h = prepared(mode); h.classification_fixture = 1
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.optical_state() == 3 and not h.result_stores
    assert (0x14904 if mode else 0x191BC) in h.mock_calls
    assert not h.notifications


def test_late_processing_has_immediate_notification_sinks_not_only_scheduled_aggregation():
    h = prepared(); h.arrange(error_bit_set=True)
    h.raw_reporting_fixture = True
    h.uc.mem_write(BUFFER + 0xA6, b"\x01")  # one cached algorithm buffer element
    h.uc.mem_write(0x208C47, b"\x01")  # exact stock C5-report branch selector
    h.call(POST_DISABLE, 0xFFFF); h.run_hub_until_fixture_empty()
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert h.ownership() == 0 and not h.optical_starts
    assert h.acquisition_statuses == [0xFFFFFFFF]
    assert [(offset, len(packet)) for offset, packet in h.notifications] == [
        (0x4766, 11), (0x6828, 12)]
    assert h.notifications[1][1][1] == 72
    # Payloads are emulator fixtures, never real health data. Transmission and
    # any already queued notifications remain unexecuted boundaries.


def test_completion_metadata_clear_does_not_clear_the_published_cached_hr_result():
    h = prepared(); h.arrange(error_bit_set=True)
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    assert bytes(h.uc.mem_read(STATUS + 0x18, 4)) == bytes(4)
    assert h.call(0xF74C) == 72
    # An actual getter continues returning the fixture result after all four
    # lower readiness/status bytes were cleared. Neither is provenance.


def test_failed_acquisition_result_can_reach_later_scheduled_aggregation_without_a_new_enable():
    h = prepared(1); h.arrange(mode=1, error_bit_set=True)
    h.uc.mem_write(SPO2_RESULT + 1, b"\x0e")  # pending old reporting callback
    h.call(POST_DISABLE, 0xFFFF); h.run_hub_until_fixture_empty()
    h.call(0xD9F8); h.run_hub_until_fixture_empty()
    h.call(0xE104)  # execute the unchanged later scheduled callback
    assert h.acquisition_statuses == [0xFFFFFFFF]
    assert h.spo2_aggregate_inputs == [98]
    assert h.ownership() == 0 and not h.optical_starts
    assert h.post_attempts == [(3, 2, 0xFFFF), (3, 0, 0), (3, 2, 0x80)]
    # Aggregation remains intercepted: no persistence, packet or phone claim.


def test_selected_modes_and_code_spans_do_not_admit_unknown_dispatch_or_literal_execution():
    h = prepared()
    with pytest.raises(ValueError, match="unreviewed processing mode"):
        h.arrange(mode=7)
    for offset in (0xF350, 0xF5C0, 0x1174C):
        with pytest.raises(ProofError, match="unreviewed execution"):
            h.call(offset)


def test_stock_identity_is_pinned_and_no_mutated_or_v2_image_is_accepted():
    bad = bytearray(STOCK); bad[0xF31C] ^= 1
    with pytest.raises(ValueError, match="exact pinned stock"):
        StockOpticalDispatchHarness(bytes(bad))
