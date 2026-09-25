"""Offline health adapter receipts, not stock RTOS/I2C completion evidence."""
import ctypes as c
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEALTH, QUIESCING, PAUSED, RESUMING, READY, FAULT = range(6)


class Ticket(c.Structure):
    _fields_ = [("generation", c.c_uint32), ("serial", c.c_uint32), ("job", c.c_uint8)]


class Adapter(c.Structure):
    _fields_ = [("state", c.c_int)] + [(name, c.c_uint32) for name in (
        "generation", "job_generation", "token", "next_serial", "required_jobs",
        "cancelled_jobs", "in_flight", "settings_revision",
    )] + [("jobs", c.c_uint32 * 32)] + [(name, c.c_bool) for name in (
        "inventory_proven", "fenced", "stopped",
    )]


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        pytest.skip("C compiler required")
    output = tmp_path_factory.mktemp("health-adapter") / "adapter.so"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    str(ROOT / "firmware/unified/health_adapter.c"), "-o", str(output)], check=True)
    lib = c.CDLL(str(output))
    ptr, u32 = c.POINTER(Adapter), c.c_uint32
    signatures = {
        "init": ([ptr, u32, c.c_bool], None),
        "begin_quiesce": ([ptr, u32], c.c_bool),
        "cancelled": ([ptr, u32, u32, u32], c.c_bool),
        "fenced": ([ptr, u32, u32], c.c_bool),
        "stopped": ([ptr, u32, u32, c.c_bool], c.c_bool),
        "quiesced": ([ptr, u32], c.c_bool),
        "retirement_allowed": ([ptr, u32], c.c_bool),
        "begin_resume": ([ptr, u32, u32], c.c_bool),
        "resume_ready": ([ptr, u32, u32, u32, c.c_bool, c.c_bool], c.c_bool),
        "can_commit": ([ptr, u32, u32], c.c_bool),
        "commit_health": ([ptr, u32, u32], c.c_bool),
        "job_begin": ([ptr, c.c_uint8, c.POINTER(Ticket)], c.c_bool),
        "run_begin": ([ptr, Ticket], c.c_bool),
        "run_end": ([ptr, Ticket, c.c_bool], c.c_bool),
        "result_allowed": ([ptr, Ticket, c.c_bool], c.c_bool),
        "job_end": ([ptr, Ticket], c.c_bool),
        "fail": ([ptr], None),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, "wh_" + name)
        fn.argtypes, fn.restype = args, result
    return lib


def fresh(api, jobs=0x13):
    h = Adapter()
    api.wh_init(h, jobs, True)
    assert h.state == HEALTH
    return h


def start(api, h, job=0):
    t = Ticket()
    assert api.wh_job_begin(h, job, t)
    return t


def prove_quiet(api, h):
    assert api.wh_cancelled(h, h.token, h.generation, h.required_jobs)
    assert api.wh_fenced(h, h.token, h.generation)
    assert api.wh_stopped(h, h.token, h.generation, True)


def resume(api, h, token=2, revision=17):
    assert api.wh_begin_resume(h, token, revision)
    assert api.wh_resume_ready(h, token, h.generation, revision, True, True)
    assert h.state == READY
    assert api.wh_can_commit(h, token, revision)
    assert api.wh_commit_health(h, token, revision)
    assert h.state == HEALTH


@pytest.mark.parametrize("mask,reviewed", [(0, False), (0, True), (0x13, False)])
def test_unknown_or_empty_inventory_is_closed(api, mask, reviewed):
    h = Adapter()
    api.wh_init(h, mask, reviewed)
    assert h.state == FAULT
    assert not api.wh_begin_quiesce(h, 1)
    assert not api.wh_begin_resume(h, 1, 0)
    assert not api.wh_job_begin(h, 0, Ticket())


def test_receipts_are_ordered_and_ready_is_not_health(api):
    h = fresh(api)
    t = start(api, h)
    assert api.wh_begin_quiesce(h, 1)
    assert not api.wh_run_begin(h, t)
    assert not api.wh_result_allowed(h, t, True)
    assert not api.wh_fenced(h, 1, h.generation)
    assert not api.wh_stopped(h, 1, h.generation, True)
    assert api.wh_cancelled(h, 1, h.generation, 0x3)
    assert not api.wh_fenced(h, 1, h.generation)
    assert api.wh_cancelled(h, 1, h.generation, 0x10)
    assert api.wh_fenced(h, 1, h.generation)
    assert not api.wh_quiesced(h, 1)
    assert api.wh_stopped(h, 1, h.generation, True)
    assert api.wh_quiesced(h, 1)
    assert api.wh_begin_resume(h, 5, 9)
    assert api.wh_resume_ready(h, 5, h.generation, 9, True, True)
    assert not api.wh_job_begin(h, 1, Ticket())
    assert not api.wh_result_allowed(h, t, True)
    assert api.wh_commit_health(h, 5, 9)
    assert not api.wh_run_begin(h, t)
    assert api.wh_job_begin(h, 1, Ticket())


def test_inflight_run_must_end_before_cancel_fence_and_stop(api):
    h = fresh(api)
    t = start(api, h)
    assert api.wh_run_begin(h, t)
    assert not api.wh_run_begin(h, t)
    assert api.wh_begin_quiesce(h, 1)
    assert not api.wh_cancelled(h, 1, h.generation, 1)
    assert not api.wh_job_end(h, t)
    assert not api.wh_fenced(h, 1, h.generation)
    assert api.wh_run_end(h, t, True)  # real operation completes after pause began
    assert not api.wh_run_end(h, t, True)
    prove_quiet(api, h)
    assert api.wh_quiesced(h, 1)


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_partial_entry_resume_requires_new_quiet_receipts(api, stage):
    h = fresh(api)
    assert api.wh_begin_quiesce(h, 1)
    old_generation = h.generation
    if stage >= 1:
        assert api.wh_cancelled(h, 1, old_generation, h.required_jobs)
    if stage >= 2:
        assert api.wh_fenced(h, 1, old_generation)
    assert api.wh_begin_resume(h, 5, 19)
    assert not api.wh_resume_ready(h, 5, h.generation, 19, True, True)
    assert not api.wh_cancelled(h, 1, old_generation, h.required_jobs)
    assert not api.wh_stopped(h, 1, old_generation, False)
    assert h.state == RESUMING
    prove_quiet(api, h)
    assert api.wh_resume_ready(h, 5, h.generation, 19, True, True)
    assert api.wh_commit_health(h, 5, 19)


@pytest.mark.parametrize("stage", [0, 1, 2, 3])
def test_retirement_allows_quiet_resume_but_never_ready_or_unproved_recovery(api, stage):
    h = fresh(api)
    assert not api.wh_retirement_allowed(h, 0)
    assert api.wh_begin_quiesce(h, 1)
    if stage >= 1:
        assert api.wh_cancelled(h, 1, h.generation, h.required_jobs)
    if stage >= 2:
        assert api.wh_fenced(h, 1, h.generation)
    if stage >= 3:
        assert api.wh_stopped(h, 1, h.generation, True)
    assert bool(api.wh_retirement_allowed(h, 1)) == (stage == 3)
    assert api.wh_begin_resume(h, 5, 19)
    assert not api.wh_retirement_allowed(h, 1)
    assert not api.wh_quiesced(h, 5)  # RESUMING is not relabeled as PAUSED.
    assert bool(api.wh_retirement_allowed(h, 5)) == (stage == 3)
    if stage < 3:
        prove_quiet(api, h)
    before = bytes(h)
    assert api.wh_retirement_allowed(h, 5)
    assert bytes(h) == before
    assert api.wh_resume_ready(h, 5, h.generation, 19, True, True)
    assert not api.wh_retirement_allowed(h, 5)
    assert api.wh_commit_health(h, 5, 19)
    assert not api.wh_retirement_allowed(h, 5)


@pytest.mark.parametrize("missing", ["inventory", "jobs", "cancelled", "flight", "fence", "stop"])
@pytest.mark.parametrize("resuming", [False, True])
def test_retirement_rechecks_every_quiet_requirement(api, missing, resuming):
    h = fresh(api)
    assert api.wh_begin_quiesce(h, 1)
    prove_quiet(api, h)
    if resuming:
        assert api.wh_begin_resume(h, 5, 19)
    assert api.wh_retirement_allowed(h, h.token)
    if missing == "inventory": h.inventory_proven = False
    elif missing == "jobs": h.required_jobs = 0
    elif missing == "cancelled": h.cancelled_jobs &= ~1
    elif missing == "flight": h.in_flight = 1
    elif missing == "fence": h.fenced = False
    else: h.stopped = False
    assert not api.wh_retirement_allowed(h, h.token)


@pytest.mark.parametrize("phase", ["pause", "resume"])
def test_physical_stop_failure_never_becomes_success(api, phase):
    h = fresh(api)
    assert api.wh_begin_quiesce(h, 1)
    if phase == "resume":
        assert api.wh_begin_resume(h, 3, 11)
    assert api.wh_cancelled(h, h.token, h.generation, h.required_jobs)
    assert api.wh_fenced(h, h.token, h.generation)
    assert not api.wh_stopped(h, h.token, h.generation, False)
    assert h.state == FAULT and not h.stopped
    assert not api.wh_commit_health(h, h.token, 11)
    assert api.wh_begin_resume(h, 5, 12)
    assert not api.wh_resume_ready(h, 5, h.generation, 12, True, True)
    prove_quiet(api, h)
    assert api.wh_resume_ready(h, 5, h.generation, 12, True, True)


@pytest.mark.parametrize("preserved,rebound", [(False, False), (False, True), (True, False)])
def test_resume_cannot_claim_preservation_or_scheduler_by_default(api, preserved, rebound):
    h = fresh(api)
    assert api.wh_begin_quiesce(h, 1)
    prove_quiet(api, h)
    assert api.wh_begin_resume(h, 2, 17)
    assert not api.wh_resume_ready(h, 2, h.generation, 17, preserved, rebound)
    assert h.state == FAULT


@pytest.mark.parametrize("when", ["prepare", "commit"])
def test_changed_current_settings_require_fresh_resume_binding(api, when):
    h = fresh(api)
    assert api.wh_begin_quiesce(h, 1)
    prove_quiet(api, h)
    assert api.wh_begin_resume(h, 2, 17)
    if when == "prepare":
        assert not api.wh_resume_ready(h, 2, h.generation, 18, True, True)
    else:
        assert api.wh_resume_ready(h, 2, h.generation, 17, True, True)
        assert not api.wh_can_commit(h, 2, 18)
        assert not api.wh_commit_health(h, 2, 18)
    assert h.state == RESUMING and h.settings_revision == 18
    assert not api.wh_job_begin(h, 0, Ticket())
    assert api.wh_resume_ready(h, 2, h.generation, 18, True, True)
    assert api.wh_commit_health(h, 2, 18)


def test_job_identity_is_boot_unique_even_without_mode_change(api):
    h = fresh(api)
    t = start(api, h)
    assert not api.wh_job_begin(h, 0, Ticket())
    assert not api.wh_result_allowed(h, t, False)  # PRNG/fallback never measured
    assert api.wh_result_allowed(h, t, True)
    assert api.wh_job_end(h, t)
    newer = start(api, h)
    assert newer.serial > t.serial and newer.generation == t.generation
    assert not api.wh_run_begin(h, t)
    assert not api.wh_result_allowed(h, t, True)
    assert not api.wh_job_end(h, t)
    assert api.wh_result_allowed(h, newer, True)


@pytest.mark.parametrize("job", [2, 3, 5, 31, 32, 255])
def test_unknown_jobs_are_denied(api, job):
    h = fresh(api)
    assert not api.wh_job_begin(h, job, Ticket())
    forged = Ticket(h.generation, 1, job)
    assert not api.wh_run_begin(h, forged)
    assert not api.wh_run_end(h, forged, True)
    assert not api.wh_result_allowed(h, forged, True)
    assert not api.wh_job_end(h, forged)


def test_job_31_bit_is_defined_unsigned(api):
    h = fresh(api, 0x80000000)
    t = start(api, h, 31)
    assert api.wh_run_begin(h, t)
    assert api.wh_run_end(h, t, True)
    assert api.wh_begin_quiesce(h, 1)
    prove_quiet(api, h)
    resume(api, h)


def test_unknown_cancel_jobs_and_stale_receipts_do_not_pollute_new_operation(api):
    h = fresh(api)
    assert api.wh_begin_quiesce(h, 7)
    before = bytes(h)
    for token, generation, mask in [(6, h.generation, 0x13), (7, h.generation - 1, 0x13),
                                     (7, h.generation, 0), (7, h.generation, 4)]:
        assert not api.wh_cancelled(h, token, generation, mask)
        assert bytes(h) == before
    for token in (0, 1, 7):
        assert not api.wh_begin_quiesce(h, token)
        assert bytes(h) == before


@pytest.mark.parametrize("counter", ["generation", "next_serial"])
def test_exhaustion_never_reuses_identity(api, counter):
    h = fresh(api)
    setattr(h, counter, 0xFFFFFFFF)
    if counter == "generation":
        assert not api.wh_begin_quiesce(h, 1)
    else:
        assert not api.wh_job_begin(h, 0, Ticket())
    assert h.state == FAULT


def test_failed_run_closes_health_gate(api):
    h = fresh(api)
    t = start(api, h)
    assert api.wh_run_begin(h, t)
    assert not api.wh_run_end(h, t, False)
    assert h.state == FAULT and h.in_flight == 0
    assert not api.wh_result_allowed(h, t, True)


def test_native_stress_sanitizers(tmp_path):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("Clang sanitizer support required")
    output = tmp_path / "health-stress"
    subprocess.run([compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(ROOT / "firmware/unified"),
                    str(ROOT / "tests/native/health_adapter_stress.c"),
                    str(ROOT / "firmware/unified/health_adapter.c"), "-o", str(output)], check=True)
    result = subprocess.run([str(output)], text=True, capture_output=True, check=True)
    report = json.loads(result.stdout)
    assert report["cycles"] == 20000
    assert report["measured"] == 320000 and report["stale_rejected"] == 320000
    assert report["context_bytes"] <= 192  # local test budget, NOT ring allocation
    assert not result.stderr


def test_armv6m_freestanding_compile(tmp_path):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("Clang ARM compiler required")
    output = tmp_path / "health.o"
    subprocess.run([compiler, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
                    "-Oz", "-ffreestanding", "-fno-builtin", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-c", str(ROOT / "firmware/unified/health_adapter.c"), "-o", str(output)], check=True)
    assert output.read_bytes()[:4] == b"\x7fELF"


def stock_bridge(api, name, *, measured_fixture=False):
    pytest.importorskip("unicorn")
    from whip.fwhealth_adapter import SCHEDULED_JOBS, StockPublicationHarness

    h = fresh(api, jobs=1)  # synthetic inventory, NOT real inventory attestation
    ticket = start(api, h)
    job = next(j for j in SCHEDULED_JOBS if j.name == name)
    stock = StockPublicationHarness(
        (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes(), job,
        lambda measured: api.wh_result_allowed(h, ticket, measured),
        verified_source_fixture=measured_fixture,
    )
    return h, ticket, stock


def prime_timeout(stock, *, direct_value=None):
    """Explicit stock RAM inputs; no actual sensor or scheduled timer execution."""
    import struct
    name = stock.job.name
    if name == "hr":
        stock.uc.mem_write(0x20C0C0, b"\x01")  # active scheduled result publisher
        stock.uc.mem_write(0x20C0D0, struct.pack("<H", 49))
        stock.uc.mem_write(0x20C028, bytes([direct_value or 0]))  # fallback getter
    elif name == "spo2":
        stock.uc.mem_write(0x20C0A8, bytes([direct_value or 0, 64]))
    elif name == "owner_200":
        stock.uc.mem_write(0x20C0E4, bytes([direct_value or 0, 0, 50]))
    elif name == "owner_100":
        stock.uc.mem_write(0x20C0F8, bytes([0, 59, 0, direct_value or 0]))
    else:
        stock.uc.mem_write(0x20C100, bytes([direct_value or 0, 0, 49]))


@pytest.mark.parametrize("name,expected", [
    ("hr", 46), ("spo2", 99), ("owner_200", 36),
    ("owner_100", 36), ("owner_1000", 160),
])
@pytest.mark.parametrize("paused", [False, True])
def test_actual_stock_generated_results_are_not_measured(api, name, expected, paused):
    # Even an incorrectly optimistic source fixture cannot promote an observed
    # PRNG-generated path into a measured result in this observer.
    h, ticket, stock = stock_bridge(api, name, measured_fixture=True)
    prime_timeout(stock)
    stock.prng_values.append(6)
    if name == "hr" and paused:
        assert api.wh_begin_quiesce(h, 1)
    stock.call(stock.job.callback)
    if name != "hr":
        assert not stock.publication_attempts
        if paused:
            assert api.wh_begin_quiesce(h, 1)
        # Generated value persists in stock RAM until the next timer callback.
        stock.call(stock.job.callback)
    assert stock.generated and not stock.prng_values
    assert stock.publication_attempts == [(expected, False, False)]
    assert stock.accepted_results == []
    assert stock.timer_cancel_requests == [stock.job.timer]
    assert stock.messages == [(3, 2, stock.job.mask)]
    assert not api.wh_result_allowed(h, ticket, False)


@pytest.mark.parametrize("name,value", [
    ("hr", 72), ("spo2", 98), ("owner_200", 40),
    ("owner_100", 40), ("owner_1000", 160),
])
@pytest.mark.parametrize("paused", [False, True])
def test_actual_stock_publication_boundary_obeys_captured_ticket(api, name, value, paused):
    h, ticket, stock = stock_bridge(api, name, measured_fixture=True)
    prime_timeout(stock, direct_value=value)
    if paused:
        assert api.wh_begin_quiesce(h, 1)
    stock.call(stock.job.callback)
    assert not stock.generated
    assert stock.publication_attempts == [(value, True, not paused)]
    assert stock.accepted_results == ([] if paused else [value])
    assert stock.timer_cancel_requests == [stock.job.timer]


def test_plausible_stock_value_is_not_proof_of_measurement(api):
    _, _, stock = stock_bridge(api, "spo2")
    prime_timeout(stock, direct_value=98)
    stock.call(stock.job.callback)
    assert stock.publication_attempts == [(98, False, False)]


def test_old_stock_callback_not_relabeled_after_resume(api):
    h, old, stock = stock_bridge(api, "spo2", measured_fixture=True)
    prime_timeout(stock, direct_value=98)
    assert api.wh_begin_quiesce(h, 1)
    prove_quiet(api, h)
    resume(api, h)
    new = start(api, h)
    assert new.serial != old.serial and new.generation != old.generation
    stock.call(stock.job.callback)
    assert stock.publication_attempts == [(98, True, False)]
    assert api.wh_result_allowed(h, new, True)


def start_harness():
    pytest.importorskip("unicorn")
    from whip.fwhealth_adapter import StockStartHarness
    return StockStartHarness((ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes())


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("enabled", [False, True])
def test_actual_stock_schedule_start_posts_and_timer_abi(index, enabled):
    from whip.fwhealth_adapter import SCHEDULED_JOBS
    from whip.fwcontinuity import BIAS
    stock = start_harness()
    job = SCHEDULED_JOBS[index]
    stock.settings_enabled_fixture = enabled
    stock.call(job.start)
    assert stock.messages == ([(3, 1, job.mask)] if enabled else [])
    assert stock.timer_starts == ([(job.timer, BIAS + job.callback + 1, 1000, 1)]
                                  if enabled else [])
    assert not stock.optical_starts  # POST is not executed physical START


def test_actual_stock_alternate_hr_start_uses_same_timer_and_callback():
    from whip.fwcontinuity import BIAS
    stock = start_harness()
    stock.call(0xE51C)
    assert stock.messages == [(3, 1, 0x10)]
    assert stock.timer_starts == [(0x20C0C4, BIAS + 0xE384 + 1, 1000, 1)]


def test_actual_stock_opcode_1e_owns_separate_job_until_timeout():
    from whip.fwcontinuity import BIAS
    stock = start_harness()
    packet = 0x220500  # fixture memory only
    stock.uc.mem_write(packet, b"\x1e\x01" + bytes(14))
    stock.call(0x4E4A, packet)
    assert stock.messages == [(3, 1, 0x4000)]
    assert stock.timer_starts == [(0x209D44, BIAS + 0x4E0C + 1, 1000, 1)]
    stock.call(0x4E0C)
    assert stock.realtime_results == [(0x1E, 0)]
    stock.uc.mem_write(0x208C4C, b"\x01")
    stock.call(0x4E0C)
    assert stock.messages == [(3, 1, 0x4000), (3, 2, 0x4000)]
    assert stock.timer_cancel_requests == [0x209D44]


def test_actual_stock_opcode_1e_explicit_stop_is_only_intent():
    stock = start_harness()
    packet = 0x220500
    stock.uc.mem_write(packet, b"\x1e\x01" + bytes(14))
    stock.call(0x4E4A, packet)
    stock.uc.mem_write(packet + 1, b"\x02")
    stock.call(0x4E4A, packet)
    assert stock.messages == [(3, 1, 0x4000), (3, 2, 0x4000)]
    assert stock.timer_cancel_requests == [0x209D44]
    assert stock.optical_writes == []  # queued STOP has not touched hardware


def test_actual_stock_wear_probe_writes_two_deferred_result_pointers():
    import struct
    from whip.fwcontinuity import BIAS
    stock = start_harness()
    first, second = 0x220500, 0x220501
    stock.uc.mem_write(first, b"\xee\xee")
    stock.call(0xDE38, first)
    stock.call(0xDE38, second)
    assert stock.messages == [(3, 1, 2)]
    assert stock.timer_starts == [(0x20C018, BIAS + 0xDE04 + 1, 2500, 1)]
    assert bytes(stock.uc.mem_read(0x20C030, 8)) == struct.pack("<II", first, second)
    stock.call(0xDE04)
    assert bytes(stock.uc.mem_read(first, 2)) == b"\x01\x01"
    assert bytes(stock.uc.mem_read(0x20C02C, 12)) == bytes(12)
    assert stock.messages == [(3, 1, 2), (3, 2, 2)]
    assert stock.timer_cancel_requests == [0x20C018]
