"""Pinned stock instructions, controlled mock boundaries; NO hardware claims."""
from pathlib import Path
import math

import pytest

pytest.importorskip("unicorn", reason="install requirements-firmware-proof.txt")

from whip.fwcontinuity import ProofError  # noqa: E402
from whip.fwhealth_lifecycle import (  # noqa: E402
    HUB_QUEUE_SLOT, OPTICAL_ABSENT, OPTICAL_CONFIG, OPTICAL_CONTROL, OPTICAL_DISABLE,
    OPTICAL_ENABLE, POST_DISABLE, POST_ENABLE, STK_ACTIVE_CONFIG,
    STK_IDLE_CONFIG, SPO2_CALLBACK, SPO2_RESULT, StockLifecycleHarness, StockFeedHarness,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def h():
    return StockLifecycleHarness((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())


def test_active_config_is_stock_cadence_not_a_25hz_program(h):
    h.call(STK_ACTIVE_CONFIG)
    assert h.stk_writes == [(0x11, 0x74), (0x10, 0x0F), (0x3E, 0xC8)]


@pytest.mark.parametrize("failed_register", [0x11, 0x10])
def test_active_config_final_success_hides_earlier_write_failures(h, failed_register):
    h.stk_failed_registers.add(failed_register)
    assert h.call(STK_ACTIVE_CONFIG) == 1
    assert (failed_register, 0x74 if failed_register == 0x11 else 0x0F) in h.stk_writes


@pytest.mark.parametrize("failed_register", [0x11, 0x10])
def test_idle_config_ignores_power_and_bandwidth_write_failures(h, failed_register):
    h.stk_failed_registers.add(failed_register)
    assert h.call(STK_IDLE_CONFIG) == 1
    assert h.stk_writes[-3:] == [(0x11, 0x80), (0x10, 0x0A), (0x11, 0x7C)]


def test_idle_config_does_check_earlier_motion_config_failure(h):
    h.stk_failed_registers.add(0x28)
    assert h.call(STK_IDLE_CONFIG) == 0


@pytest.mark.parametrize("operation,value", [(0, 0), (1, 0x5A), (2, 0xA5)])
def test_vc_control_values_execute_original_instructions(h, operation, value):
    assert h.call(OPTICAL_CONTROL, operation) == 0
    assert h.optical_writes == [(0x7B, bytes([value]))]


def test_vc_control_reports_mock_i2c_failure(h):
    h.optical_write_ok = False
    assert h.call(OPTICAL_CONTROL, 0) == 0xFFFFFFFF


def test_vc_control_unknown_operation_returns_one_without_bus_access(h):
    assert h.call(OPTICAL_CONTROL, 99) == 1
    assert h.optical_writes == []


@pytest.mark.parametrize("mode", [0, 1, 2, 3])
@pytest.mark.parametrize("config_rate", [200, 400, 600])
def test_disable_spo2_owner_can_restart_other_health_owner_in_any_state(h, mode, config_rate):
    h.set_ownership(0x90, state=mode)  # SpO2 0x80 plus scheduled HR 0x10
    h.uc.mem_write(OPTICAL_CONFIG, config_rate.to_bytes(2, "little") + b"\x01")
    h.call(OPTICAL_DISABLE, 0x80)
    assert h.ownership() == 0x10
    assert h.optical_writes == [(0x7B, b"\xa5"), (0x7B, b"\x00")]
    assert h.optical_starts == [(config_rate, 0)]  # retains config field, changes mode
    assert h.optical_state() == (1 if mode == 2 else mode)


def test_disable_all_clears_mask_and_state_but_ignores_failed_stop_writes(h):
    h.set_ownership(0x1311)
    h.optical_write_ok = False
    h.call(OPTICAL_DISABLE, 0xFFFF)
    assert h.ownership() == 0 and h.optical_state() == 0
    assert h.optical_writes == [(0x7B, b"\xa5"), (0x7B, b"\x00")]
    assert not h.optical_starts  # mask/state are NOT physical STOP confirmation


def test_absent_flag_short_circuits_disable_without_clearing_mask(h):
    h.set_ownership(0x10)
    h.uc.mem_write(OPTICAL_ABSENT, b"\x01")
    h.call(OPTICAL_DISABLE, 0xFFFF)
    assert h.ownership() == 0x10 and not h.optical_writes


@pytest.mark.parametrize("mask,expected", [(0x10, (200, 0)), (0x80, (400, 1)),
                                         (0x40, (200, 7)), (0x800, (200, 7))])
def test_enables_choose_expected_stock_modes_at_mock_start(h, mask, expected):
    h.set_ownership(0, state=0)
    h.call(OPTICAL_ENABLE, mask)
    assert h.ownership() == mask and h.optical_state() == 1
    assert h.optical_starts == [expected]


def test_legacy_owner_0x40_swallows_new_requests(h):
    h.set_ownership(0x40)
    h.call(OPTICAL_ENABLE, 0x10)
    assert h.ownership() == 0x40 and not h.optical_starts


def test_raw_owner_0x800_does_not_prevent_health_restart(h):
    h.set_ownership(0x800)
    h.call(OPTICAL_ENABLE, 0x80)
    assert h.ownership() == 0x880 and h.optical_starts == [(400, 1)]


def test_probe_failure_keeps_ownership_clear_and_sets_failure(h):
    h.set_ownership(0, state=0)
    h.probe_ok = False
    h.call(OPTICAL_ENABLE, 0x10)
    assert h.ownership() == 0 and h.optical_state() == 3
    assert not h.optical_starts


@pytest.mark.parametrize("entry,subtype", [(POST_ENABLE, 1), (POST_DISABLE, 2)])
@pytest.mark.parametrize("accepts", [True, False])
def test_post_is_only_queue_acceptance_never_physical_completion(h, entry, subtype, accepts):
    h.queue_accepts = accepts
    h.set_ownership(0x10)
    assert h.call(entry, 0xFFFF) == accepts
    assert h.post_attempts == [(3, subtype, 0xFFFF)]
    assert h.messages == (h.post_attempts if accepts else [])
    assert h.ownership() == 0x10 and not h.optical_writes


def test_missing_queue_cannot_deliver_quiesce(h):
    h.uc.mem_write(HUB_QUEUE_SLOT, bytes(4))
    assert h.call(POST_DISABLE, 0xFFFF) == 0
    assert not h.post_attempts


@pytest.mark.parametrize("prng,expected", [([6], 99), ([7, 3], 96), ([0, 0], 93)])
def test_uncancelled_spo2_timeout_can_report_a_non_sensor_fallback(h, prng, expected):
    # 64 prior timer invocations, no optical result; no start was performed.
    h.uc.mem_write(SPO2_RESULT, bytes([0, 64]))
    h.prng_values.extend(prng)
    h.call(SPO2_CALLBACK)
    assert h.uc.mem_read(SPO2_RESULT, 1)[0] == expected
    assert not h.prng_values and not h.spo2_aggregate_inputs
    assert not h.optical_starts and not h.optical_writes
    h.call(SPO2_CALLBACK)
    assert h.spo2_aggregate_inputs == [expected]
    assert h.timer_cancel_requests == [SPO2_RESULT + 4]
    assert h.messages == [(3, 2, 0x80)]
    # The store boundary was MOCKED: this is evidence for delivery of a generated
    # value to aggregation, NOT a test of actual history/NVM/phone publication.


def test_whitelist_does_not_expand_to_optical_hardware_or_unknown_firmware(h):
    with pytest.raises(ProofError, match="unreviewed execution"):
        h.call(0x11246)
    with pytest.raises(ProofError, match="unreviewed optical I2C"):
        h.call(0xEE12, 0x42, h.OUTPUTS[0], 1)


def test_health_front_end_feeds_each_valid_fifo_sample_without_3_to_1_decimation():
    h = StockFeedHarness((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())
    samples = [(i * 173 - 2300, i * -91 + 780, 8005 - i * 32) for i in range(31)]
    h.fifo.extend(samples)
    h.raw_read(31)
    expected_axes = [(b, a, c) for a, b, c in samples]
    assert h.consume_health() == expected_axes
    expected = []
    old = 0
    for axes in expected_axes:
        magnitude = math.isqrt(sum(math.trunc(v / 8) ** 2 for v in axes)) * 8
        old = (3 * old + 7 * magnitude) // 10 if old else magnitude
        expected.append(old)
    assert h.filtered_magnitudes == expected
    assert len(h.filtered_magnitudes) == len(samples)
    assert h.consume_health() == []


@pytest.mark.parametrize("value,expected", [(0, 10), (12, 12), (25, 25), (255, 40)])
def test_candidate_count_parameter_is_a_clamped_byte_not_a_sensor_write(value, expected):
    h = StockFeedHarness((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())
    h.call(0x1DD54, value)
    assert h.uc.mem_read(0x2085EE, 1)[0] == expected
    assert not h.i2c_calls and not h.filtered_magnitudes
