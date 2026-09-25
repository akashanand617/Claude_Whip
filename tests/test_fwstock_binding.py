"""Selected exact-stock binding paths. No Bluetooth or physical sensor access."""
from pathlib import Path
import os
import shutil
import struct
import subprocess

import pytest

pytest.importorskip("unicorn", reason="requires requirements-firmware-proof.txt")
from whip.fwcontinuity import BIAS, ProofError  # noqa: E402
from whip.fwhealth_lifecycle import OPTICAL, POST_ENABLE, POST_DISABLE  # noqa: E402
from whip.fwstock_binding import (  # noqa: E402
    StockBindingHarness, MOCK_HEAP, MOCK_TIMER,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def h():
    return StockBindingHarness((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())


@pytest.mark.parametrize("operation,byte", [(0, 0), (1, 0x5A), (2, 0xA5)])
def test_actual_control_write_zero_means_success(h, operation, byte):
    assert h.call(0x12496, operation) == 0
    assert h.transfers == [bytes([0x7B, byte])]
    assert h.target_addresses == [0x33]
    assert h.mutex_events == ["take", "give"]
    assert h.allocations == [12] and h.freed == [MOCK_HEAP]
    assert {0x12496, 0xEE12, 0xDBCA, 0xDB42}.issubset(h.executed)


@pytest.mark.parametrize("failure", ["mutex", "not_ready", "busy", "transfer"])
def test_actual_control_write_errors_return_uint32_max(h, failure):
    if failure == "mutex": h.mutex_available = False
    elif failure == "not_ready": h.bus_ready = False
    elif failure == "busy": h.bus_busy = True
    else: h.transfer_result = 7
    assert h.call(0x12496, 0) == 0xFFFFFFFF
    if failure == "mutex":
        assert h.mutex_events == ["take"] and not h.allocations
    else:
        assert h.mutex_events == ["take", "give"]
        assert h.freed == [MOCK_HEAP]
    assert len(h.delay_calls) == (501 if failure in ("not_ready", "busy") else 0)
    assert h.transfers == ([b"\x7b\x00"] if failure == "transfer" else [])


def test_actual_control_ignores_mutex_release_failure(h):
    h.mutex_give_ok = False
    assert h.call(0x12496, 0) == 0
    assert h.mutex_events == ["take", "give"]


def test_actual_control_allocation_failure_is_not_recoverable(h):
    h.allocate_ok = False
    with pytest.raises(ProofError, match="unmapped/invalid"):
        h.call(0x12496, 0)
    assert h.allocations == [12] and not h.transfers and not h.freed
    assert h.mutex_events == ["take"]  # NULL write faults before release


@pytest.mark.parametrize("operation", [3, 255, 0xFFFFFFFF])
def test_actual_control_unknown_operation_returns_nonzero_without_bus(h, operation):
    assert h.call(0x12496, operation) == 1
    assert not h.mutex_events and not h.transfers


@pytest.mark.parametrize("failure", [False, True])
def test_actual_full_stop_discards_real_zero_success_status(h, failure):
    h.transfer_result = int(failure)
    assert h.call(0x10EAA) == 0
    assert h.transfers == [b"\x7b\xa5", b"\x7b\x00"]
    assert h.mutex_events == ["take", "give", "take", "give"]


def test_hub_creation_records_real_queue_and_task_priority(h):
    assert h.call(0x148C) == 1
    assert h.queue_creates == [(0x208CA8, 32, 8)]
    assert h.task_creates == [(0x208CA4, BIAS + 0x1467, 2560, 2)]


def test_actual_post_then_receive_then_dispatch_is_not_inline(h):
    h.call(POST_ENABLE, 0x80)
    assert h.messages == [(3, 1, 0x80)]
    assert not h.optical_starts and not h.received
    h.run_hub_until_fixture_empty()
    assert h.received == [(3, 1, 0x80)]
    assert h.optical_starts == [(400, 1)]
    assert h.ownership() == 0x80
    assert {0x1466, 0x1420, 0xDD38, 0xF824}.issubset(h.executed)


def test_actual_late_enable_after_stop_restarts_without_generation(h):
    h.set_ownership(0x80)
    h.call(POST_DISABLE, 0xFFFF)
    h.run_hub_until_fixture_empty()
    assert h.ownership() == 0 and h.optical_state() == 0
    assert h.transfers == [b"\x7b\xa5", b"\x7b\x00"]
    h.call(POST_ENABLE, 0x80)
    h.run_hub_until_fixture_empty()
    assert h.ownership() == 0x80 and h.optical_starts == [(400, 1)]


def test_actual_hub_stop_can_clear_flags_with_failed_i2c(h):
    h.set_ownership(0x80)
    h.transfer_result = 1
    h.call(POST_DISABLE, 0xFFFF)
    h.run_hub_until_fixture_empty()
    assert h.ownership() == 0 and h.optical_state() == 0
    assert h.transfers == [b"\x7b\xa5", b"\x7b\x00"]


def test_optical_hub_subtype_three_is_noop_not_completion(h):
    before = bytes(h.uc.mem_read(OPTICAL, 16))
    h.pending.append((3, 3, 0x12345678))
    h.run_hub_until_fixture_empty()
    assert bytes(h.uc.mem_read(OPTICAL, 16)) == before
    assert 0xF934 in h.executed
    assert not h.transfers and not h.optical_starts


@pytest.mark.parametrize("create,start", [(False, False), (False, True), (True, False), (True, True)])
def test_actual_timer_creation_does_not_check_create_result_before_start(h, create, start):
    slot, callback = 0x20C0AC, BIAS + 0xE105
    h.timer_create_ok, h.timer_start_ok = create, start
    assert h.call(0x3E04, slot, callback, 1000, 1) == int(start)
    assert h.timer_calls == [("create", slot, 1, 1000, 1, callback), ("start", slot)]


def test_actual_timer_restart_does_not_replace_callback_or_mode(h):
    slot = 0x20C0AC
    h.uc.mem_write(slot, struct.pack("<I", MOCK_TIMER))
    h.call(0x3E04, slot, BIAS + 0xE105, 77, 0)
    assert h.timer_calls == [("restart", slot, 77)]


@pytest.mark.parametrize("stop,delete", [(False, False), (False, True), (True, False), (True, True)])
def test_actual_timer_cancel_ignores_stop_result_and_has_no_fence(h, stop, delete):
    slot = 0x20C0AC
    h.uc.mem_write(slot, struct.pack("<I", MOCK_TIMER))
    h.timer_stop_ok, h.timer_delete_ok = stop, delete
    assert h.call(0x3E30, slot) == int(delete)
    assert h.timer_calls == [("stop", slot), ("delete", slot)]
    assert struct.unpack("<I", h.uc.mem_read(slot, 4))[0] == MOCK_TIMER


def test_actual_empty_timer_slot_is_silent_zero(h):
    assert h.call(0x3E30, 0x20C0AC) == 0
    assert not h.timer_calls


def test_indicator_cancellation_does_not_invalidate_late_brightness_callback(h):
    h.uc.mem_write(0x209D10, struct.pack("<II", MOCK_TIMER, MOCK_TIMER))
    h.uc.mem_write(0x209D18, struct.pack("<I", 4))
    h.uc.mem_write(0x209D1C, b"\x01")
    h.call(0x3CAC)
    assert [c[:2] for c in h.timer_calls] == [
        ("stop", 0x209D10), ("delete", 0x209D10),
        ("stop", 0x209D14), ("delete", 0x209D14),
    ]
    assert not h.indicator_requests
    assert bytes(h.uc.mem_read(0x209D1C, 1)) == b"\x00"
    h.call(0x3AC4)  # already-dispatched old callback has no generation check
    assert len(h.indicator_requests) == 1
    assert h.indicator_requests[0][0:2] == (100, 1)


@pytest.fixture(scope="module")
def shim(tmp_path_factory):
    pytest.importorskip("elftools")
    pinned = os.environ.get("WHIP_UNIFIED_TEST_ELF")
    if pinned:
        return Path(pinned).read_bytes()  # outer guarded builder binds this ELF
    clang, zig = shutil.which("clang"), os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not clang or not zig:
        pytest.skip("Clang and pinned WHIP_ZIG required for compiled stock ABI shim")
    if subprocess.check_output([zig, "version"], text=True).strip() != "0.15.2":
        pytest.fail("stock ABI proof requires reviewed Zig 0.15.2")
    work = tmp_path_factory.mktemp("stock-binding-arm")
    obj, elf = work / "shim.o", work / "shim-test-only.elf"
    subprocess.run([clang, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
                    "-Oz", "-ffreestanding", "-fno-builtin", "-Wall", "-Wextra", "-Werror",
                    "-std=c11", "-c", str(ROOT / "firmware/unified/stock_binding.c"),
                    "-o", str(obj)], check=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(work / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(work / "local"))
    subprocess.run([zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
                    "-nostdlib", "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
                    "-Wl,-e,wb_stock_stop_writes", "-Wl,--build-id=none", "-Wl,--no-undefined",
                    "-o", str(elf), str(obj)], env=env, check=True)
    return elf.read_bytes()


@pytest.fixture
def bound(h, shim):
    h.load_test_shim(shim)
    return h


def invoke_stop(h):
    pointer = 0x220C00
    h.uc.mem_write(pointer - 16, b"\xa5" * 48)
    result = h.call_shim("wb_stock_stop_writes", pointer)
    assert bytes(h.uc.mem_read(pointer - 16, 16)) == b"\xa5" * 16
    assert bytes(h.uc.mem_read(pointer + 16, 16)) == b"\xa5" * 16
    return result, struct.unpack("<IIII", h.uc.mem_read(pointer, 16))


def test_compiled_heap_free_stop_executes_actual_stock_bus_without_allocator(bound):
    bound.allocate_ok = False  # faulting legacy path cannot be used accidentally
    before = bytes(bound.uc.mem_read(OPTICAL, 16))
    result, report = invoke_stop(bound)
    assert result == 1 and report == (1, 0, 0, 1)
    assert bound.transfers == [b"\x7b\xa5", b"\x7b\x00"]
    assert bound.mutex_events == ["take", "give"]
    assert not bound.allocations and not bound.freed
    assert {0xDB42, 0xDBB8}.issubset(bound.executed)
    assert 0xEE12 not in bound.executed and 0xDBCA not in bound.executed
    assert bytes(bound.uc.mem_read(OPTICAL, 16)) == before  # no synthetic stopped flag


@pytest.mark.parametrize("reset,stop", [(0, 1), (1, 0), (1, 1), (0xFFFFFFFF, 0)])
def test_compiled_stop_retains_both_results_and_attempts_stop_after_reset_error(bound, reset, stop):
    bound.transfer_results.extend([reset, stop])
    result, report = invoke_stop(bound)
    assert result == 0 and report == (1, int(reset != 0), int(stop != 0), 1)
    assert bound.transfers == [b"\x7b\xa5", b"\x7b\x00"]
    assert bound.mutex_events == ["take", "give"]
    assert not bound.allocations


@pytest.mark.parametrize("fault,status", [("not_ready", 2), ("busy", 3)])
def test_compiled_stop_retains_actual_bus_poll_timeout_status(bound, fault, status):
    if fault == "not_ready": bound.bus_ready = False
    else: bound.bus_busy = True
    result, report = invoke_stop(bound)
    assert result == 0 and report == (1, status, status, 1)
    assert not bound.transfers and len(bound.delay_calls) == 1002


def test_compiled_stop_mutex_failure_does_not_touch_bus(bound):
    bound.mutex_available = False
    result, report = invoke_stop(bound)
    assert result == 0 and report == (0, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    assert bound.mutex_events == ["take"] and not bound.transfers


def test_compiled_stop_mutex_release_failure_is_not_write_sequence_success(bound):
    bound.mutex_give_ok = False
    result, report = invoke_stop(bound)
    assert result == 0 and report == (1, 0, 0, 0)


def test_compiled_stop_absent_mutex_and_null_output_are_recoverable(bound):
    bound.uc.mem_write(0x208C98, bytes(4))
    result, report = invoke_stop(bound)
    assert result == 0 and report == (0, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    assert not bound.mutex_events and not bound.transfers
    assert bound.call_shim("wb_stock_stop_writes", 0) == 0
    assert not bound.mutex_events


@pytest.fixture
def producer():
    from whip.fwstock_binding import StockProducerHarness
    return StockProducerHarness((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())


def test_realtime_timer_dispatch_can_restart_run_after_prior_stop(producer):
    h = producer
    h.uc.mem_write(0x209D34, b"\x01")  # mode6 waiting-to-restart flag
    h.uc.mem_write(0x209D37, b"\x06\x01")  # selected mode and substate
    h.uc.mem_write(0x209D3C, struct.pack("<H", 20))
    h.call(0x4722)
    assert h.messages == [(3, 1, 1)]
    assert {0x4722, 0x4518, 0x45D6}.issubset(h.executed)
    assert not h.notifications


def test_realtime_result_can_include_prng_perturbation_of_cached_getter(producer):
    h = producer
    h.uc.mem_write(0x209D33, b"\x01")  # publish on second internal visit
    h.uc.mem_write(0x209D37, b"\x06\x01")
    h.uc.mem_write(0x209D3C, struct.pack("<H", 20))
    h.uc.mem_write(OPTICAL + 2, b"\x48\x00\x02")  # plausible cached72,state2
    h.prng_values.append(2)  # modulo3 minus1 => reported73
    h.call(0x4722)
    assert len(h.notifications) == 1
    assert h.notifications[0][:4] == bytes([0x69, 6, 0, 73])
    assert not h.prng_values and len(h.float_conversions) == 2
    assert not h.transfers  # no physical acquisition in this fixture


@pytest.mark.parametrize("mode,mask", [(1, 1), (3, 0x20), (8, 0x200), (9, 0x400),
                                      (10, 0x100), (11, 0x1000), (12, 0x1301)])
def test_realtime_failure_result_and_cancel_masks_execute_dispatcher(producer, mode, mask):
    h = producer
    h.uc.mem_write(OPTICAL + 3, b"\x01")
    h.uc.mem_write(0x209D37, bytes([mode]))
    h.uc.mem_write(0x209D3C, struct.pack("<H", 6))
    h.call(0x4722)
    assert h.messages == [(3, 2, mask)]
    assert h.timer_calls == [("stop", 0x209D40)]
    assert h.notifications[0][:4] == bytes([0x69, mode, 1, 0])


@pytest.mark.parametrize("activity,parameter", [(1, 10), (3, 2), (4, 4), (7, 3),
                                                (8, 1), (9, 5), (22, 6), (24, 7)])
def test_activity_optical_owner_also_changes_algorithm_working_state(producer, activity, parameter):
    h = producer
    h.uc.mem_write(0x208AA0, b"\x00")
    h.uc.mem_write(0x20BC60, b"\xa5" * 0xBC)
    h.call(0xA88A, activity)
    assert h.messages == [(3, 1, 1)]
    assert h.algorithm_parameters == [(parameter, 65)]
    assert h.timer_calls == [("restart", 0x20BC54, 1000)]
    assert bytes(h.uc.mem_read(0x20BC60, 1)) == b"\x02"
    assert bytes(h.uc.mem_read(0x20BCA2, 1)) == bytes([activity])
    h.call(0xAA00, 1)
    assert h.messages == [(3, 1, 1), (3, 2, 1)]
    assert h.algorithm_parameters[-1] == (0, 0)
    assert h.activity_aggregations == [1]
    assert h.timer_calls[-1] == ("stop", 0x20BC54)
    assert bytes(h.uc.mem_read(0x20BC60, 1)) == b"\x00"
