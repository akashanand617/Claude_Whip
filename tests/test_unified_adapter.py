"""Component integration with synthetic receipts, never installed stock bindings."""
import ctypes as c
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEALTH, ENTERING, GESTURE, RETURNING, FAULT = range(5)
NONE, QUIESCE, HOLD, START, STOP, RELEASE, RESUME = range(7)
WH_HEALTH, WH_QUIESCING, WH_PAUSED, WH_RESUMING, WH_READY, WH_FAULT = range(6)
IGNORED, ACCEPTED, DELIVER, SOURCE_FAULT = range(4)
HELD_PROOF, STOP_PROOF, RELEASE_PROOF = 0x0F, 0x70, 0x82
U32 = 0xFFFFFFFF


@pytest.fixture(scope="module")
def native_api(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if not compiler:
        pytest.skip("C compiler required")
    output = tmp_path_factory.mktemp("unified-adapter") / "adapter.so"
    modules = ("mode_controller", "sample_tap", "runtime", "health_adapter", "fresh_source", "adapter")
    subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-shared", "-fPIC", "-I", str(ROOT / "firmware/unified"),
                    *[str(ROOT / f"firmware/unified/{m}.c") for m in modules],
                    str(ROOT / "tests/native/adapter_proof.c"), "-o", str(output)], check=True)
    lib = c.CDLL(str(output))
    lib.proof_adapter_size.argtypes, lib.proof_adapter_size.restype = [], c.c_uint32
    lib.proof_adapter_get.argtypes = [c.c_void_p, c.c_uint32]
    lib.proof_adapter_get.restype = c.c_uint32
    lib.proof_adapter_call.argtypes = [c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32)]
    lib.proof_adapter_call.restype = c.c_uint32
    return lib


class NativeAdapter:
    def __init__(self, lib):
        self.lib = lib
        size = lib.proof_adapter_size()
        assert 0 < size <= 4096
        self.context = (c.c_uint64 * ((size + 7) // 8))()
        self.size = size

    def call(self, op, *args):
        assert len(args) <= 12
        return self.lib.proof_adapter_call(self.context, op, (c.c_uint32 * 12)(*args))

    def get(self, key):
        return self.lib.proof_adapter_get(self.context, key)

    def snapshot(self):
        return bytes(self.context)[:self.size]


@pytest.fixture
def a(native_api):
    result = NativeAdapter(native_api)
    initialize(result)
    return result


def initialize(a, jobs=3, inventory=1, profile=1, now=0):
    assert a.call(0, jobs, inventory, profile)
    assert a.call(2, 1, 0, now)


def quiet(a, now=0):
    token, generation = a.get(2), a.get(5)
    assert a.call(5, token, generation, 3, now)
    assert a.call(6, token, generation, now)
    assert a.call(7, token, generation, 1, now)


def physical(a, proof, now=0, token=None, session=None, action=None, epoch=1, binding=2):
    return a.call(8, a.get(2) if token is None else token,
                  a.get(3) if session is None else session,
                  a.get(1) if action is None else action, proof, epoch, binding, now)


def enter_start(a, now=0):
    assert a.call(3, 1, now)
    assert (a.get(0), a.get(1), a.get(4), a.get(9)) == (ENTERING, QUIESCE, WH_QUIESCING, 0)
    quiet(a, now)
    assert (a.get(1), a.get(4)) == (HOLD, WH_PAUSED)
    assert physical(a, HELD_PROOF, now)
    assert (a.get(0), a.get(1), a.get(6), a.get(7)) == (ENTERING, START, 1, 0)


def observe(a, transaction=1, first=0, count=1, now=None, fault=0, session=None):
    status = (first + max(count - 1, 0) * 20) & U32
    return a.call(10, a.get(3) if session is None else session, transaction, first,
                  count, status, status, status if now is None else now, fault)


def gesture(a, now=0):
    enter_start(a, now)
    assert observe(a, first=now) == DELIVER
    assert (a.get(0), a.get(1), a.get(4), a.get(7)) == (GESTURE, NONE, WH_PAUSED, 1)


def returning_to_resume(a, now=0):
    assert a.call(3, 0, now)
    assert (a.get(0), a.get(1), a.get(6), a.get(7), a.get(8)) == (RETURNING, STOP, 0, 0, 0)
    assert physical(a, STOP_PROOF, now)
    assert a.get(1) == RELEASE
    assert physical(a, RELEASE_PROOF, now)
    assert a.get(1) == RESUME and not a.get(9)


def finish_resume(a, now=0, revision=17):
    token = a.get(2)
    assert a.call(11, token, revision, now)
    quiet(a, now)  # Also exercises fresh proof after partial entry.
    assert a.call(12, token, a.get(5), revision, 1, 1, now)
    assert (a.get(0), a.get(4), a.get(9)) == (RETURNING, WH_READY, 0)
    assert a.call(13, token, revision, now)
    assert (a.get(0), a.get(1), a.get(4), a.get(9), a.get(6)) == (HEALTH, NONE, WH_HEALTH, 1, 0)


@pytest.mark.parametrize("jobs,inventory,profile", [(0, 0, 0), (0, 1, 1), (3, 0, 1), (3, 1, 0)])
def test_unavailable_capability_keeps_boot_health_untouched(native_api, jobs, inventory, profile):
    a = NativeAdapter(native_api)
    initialize(a, jobs, inventory, profile)
    assert a.get(0) == HEALTH and a.get(9) == 1
    before = a.snapshot()
    assert not a.call(3, 1, 100)
    assert a.snapshot() == before
    assert a.get(1) == NONE and a.get(2) == 0
    assert not a.call(22, 1) and not a.call(22, 2)  # Decorative/raw denied.


def test_profile_removal_and_busy_prepare(a):
    assert not a.call(1, 0)
    assert not a.call(3, 1, 0) and a.get(9)
    assert a.call(1, 1)
    enter_start(a)
    old = a.snapshot()
    assert not a.call(1, 0)
    assert a.snapshot() == old


def test_one_owned_profile_controls_hold_and_cannot_change_during_entry(a):
    assert a.call(24, 11, 12)
    assert (a.get(30), a.get(31)) == (11, 12)
    assert a.call(3, 1, 0)
    quiet(a)
    before = a.snapshot()
    assert not a.call(24, 99, 100)
    assert a.snapshot() == before
    assert not physical(a, HELD_PROOF, epoch=1, binding=2)
    assert physical(a, HELD_PROOF, epoch=11, binding=12)
    assert (a.get(30), a.get(31), a.get(6)) == (11, 12, 1)


def test_profile_survives_normal_health_return_and_new_gesture(a):
    gesture(a)
    returning_to_resume(a, 1)
    finish_resume(a, 2)
    assert (a.get(30), a.get(31), a.get(22)) == (1, 2, 1)
    expected_session = a.get(2) + 1  # Sessions use the next operation token.
    gesture(a, 3)
    assert a.get(3) == expected_session


def test_quiesce_waits_for_real_inflight_drain_and_fence(a):
    generation = a.get(26)
    serial = a.call(17, 0)
    assert serial and a.call(18, generation, serial, 0)
    assert a.call(3, 1, 0)
    token, closing = a.get(2), a.get(5)
    assert not a.call(5, token, closing, 3, 0)
    assert not a.call(6, token, closing, 0)
    assert not a.call(7, token, closing, 1, 0)
    assert not a.call(18, generation, serial, 0)
    assert not a.call(20, generation, serial, 0, 1)
    assert a.call(19, generation, serial, 0, 1, 0)
    quiet(a)
    assert a.get(1) == HOLD


@pytest.mark.parametrize("missing", [1, 2, 4, 8])
def test_hold_requires_every_physical_postcondition(a, missing):
    assert a.call(3, 1, 0)
    quiet(a)
    old = a.snapshot()
    assert not physical(a, HELD_PROOF ^ missing)
    assert a.snapshot() == old
    assert physical(a, HELD_PROOF)
    assert a.get(1) == START


@pytest.mark.parametrize("wrong", ["token", "session", "epoch", "binding"])
def test_hold_receipt_identity_is_bound(a, wrong):
    assert a.call(3, 1, 0)
    quiet(a)
    kwargs = {wrong: 99}
    old = a.snapshot()
    assert not physical(a, HELD_PROOF, **kwargs)
    assert a.snapshot() == old


def test_start_cannot_be_completed_by_generic_receipt(a):
    enter_start(a)
    assert not physical(a, U32, action=START)
    assert not a.call(14, a.get(3), 0)
    assert (a.get(0), a.get(7), a.get(18)) == (ENTERING, 0, 0)
    assert observe(a, count=0) == ACCEPTED
    assert a.get(1) == START and not a.get(7)
    assert observe(a, transaction=2, first=20) == DELIVER
    assert a.get(0) == GESTURE and a.get(7) == 1 and a.get(24) == 64


def test_start_without_first_acquisition_times_out_closed(a):
    enter_start(a)
    a.call(4, 249)
    assert a.get(1) == START
    a.call(4, 250)
    assert (a.get(0), a.get(1), a.get(6)) == (RETURNING, STOP, 0)


@pytest.mark.parametrize("fault", [1, 2, 4, 8, 16, 32, 64])
def test_first_acquisition_failure_never_publishes_gesture(a, fault):
    enter_start(a)
    assert observe(a, fault=fault) == SOURCE_FAULT
    assert (a.get(0), a.get(1), a.get(6), a.get(7)) == (RETURNING, STOP, 0, 0)


@pytest.mark.parametrize("bad_index", range(12))
def test_late_batch_failure_never_starts_or_publishes(a, bad_index):
    enter_start(a)
    session = a.get(3)
    assert a.call(10, session, 1, 0, 12, 223, 223, 223, 128, bad_index) == SOURCE_FAULT
    assert (a.get(0), a.get(1), a.get(6), a.get(7)) == (RETURNING, STOP, 0, 0)
    assert not a.call(14, session, 223)


def test_acquisition_is_selected_copied_and_sent_before_renew(a):
    gesture(a)
    session = a.get(3)
    assert a.get(19) == 0 and a.get(24) == 32
    assert not a.call(16, session, 1, 0)
    seq = a.call(14, session, 0)
    assert seq == 1 and a.get(8)
    assert not a.call(14, session, 0)
    assert not a.call(16, session, seq, 0)
    assert a.call(15, session, seq, 1, 0)
    assert a.call(16, session, seq, 0)
    assert not a.call(16, session, seq, 0)
    assert observe(a, transaction=2, first=20, count=2) == DELIVER
    assert a.get(19) == 40 and a.get(24) == 65


@pytest.mark.parametrize("cause", ["disconnect", "charge", "source", "send", "pending_age"])
def test_failures_stop_software_but_keep_physical_cleanup_obligations(a, cause):
    gesture(a)
    session = a.get(3)
    assert a.call(14, session, 0) == 1
    now = 0
    if cause == "disconnect":
        a.call(2, 0, 0, 0)
    elif cause == "charge":
        a.call(2, 1, 1, 0)
    elif cause == "source":
        assert observe(a, transaction=2, first=20, fault=1) == SOURCE_FAULT
        now = 20
    elif cause == "send":
        assert a.call(15, session, 1, 0, 0)
    else:
        assert observe(a, transaction=2, first=20, count=10) == DELIVER
        now = 250
        assert not a.call(15, session, 1, 1, now)
    assert (a.get(0), a.get(1), a.get(6), a.get(8), a.get(7)) == (RETURNING, STOP, 0, 0, 0)
    assert not physical(a, STOP_PROOF ^ 0x40, now)
    assert a.get(1) == STOP
    assert physical(a, STOP_PROOF, now)
    assert not physical(a, RELEASE_PROOF ^ 2, now)
    assert a.get(1) == RELEASE
    assert physical(a, RELEASE_PROOF, now)
    assert not a.get(9) and a.get(1) == RESUME


@pytest.mark.parametrize("stage", ["quiesce", "hold", "start", "gesture"])
def test_partial_entry_and_full_return_require_fresh_resume_proof(a, stage):
    if stage in ("start", "gesture"):
        enter_start(a)
        if stage == "gesture":
            assert observe(a) == DELIVER
    else:
        assert a.call(3, 1, 0)
        if stage == "hold":
            quiet(a)
    returning_to_resume(a)
    token = a.get(2)
    assert not physical(a, U32, action=RESUME)
    assert not a.call(13, token, 17, 0)
    assert a.call(11, token, 17, 0)
    if stage == "quiesce":
        assert not a.call(12, token, a.get(5), 17, 1, 1, 0)
        assert not a.call(13, token, 17, 0)
    quiet(a)
    assert a.call(12, token, a.get(5), 17, 1, 1, 0)
    assert not a.get(9)
    assert a.call(13, token, 17, 0)
    assert a.get(0) == HEALTH and a.get(9)


def test_settings_change_invalidates_ready_before_atomic_commit(a):
    gesture(a)
    returning_to_resume(a)
    token = a.get(2)
    assert a.call(11, token, 17, 0)
    assert not a.call(12, token, a.get(5), 18, 1, 1, 0)
    assert a.get(17) == 18 and a.get(4) == WH_RESUMING
    assert a.call(12, token, a.get(5), 18, 1, 1, 0)
    assert not a.call(13, token, 19, 0)
    assert (a.get(0), a.get(4), a.get(9), a.get(17)) == (RETURNING, WH_RESUMING, 0, 19)
    assert not a.call(13, token, 19, 0)
    assert a.call(12, token, a.get(5), 19, 1, 1, 0)
    assert a.call(13, token, 19, 0)
    assert (a.get(0), a.get(4), a.get(9)) == (HEALTH, WH_HEALTH, 1)


@pytest.mark.parametrize("preserved,rebound", [(0, 1), (1, 0), (0, 0)])
def test_bad_resume_postcondition_reports_fault_and_requires_recovery(a, preserved, rebound):
    gesture(a)
    returning_to_resume(a)
    token = a.get(2)
    assert a.call(11, token, 17, 0)
    assert not a.call(12, token, a.get(5), 17, preserved, rebound, 0)
    assert (a.get(0), a.get(1), a.get(4), a.get(9)) == (FAULT, NONE, WH_FAULT, 0)
    assert not a.call(3, 1, 0)
    returning_to_resume(a)
    finish_resume(a)


def test_known_health_failure_is_not_misreported_as_health(a):
    generation = a.get(26)
    serial = a.call(17, 0)
    assert a.call(18, generation, serial, 0)
    assert not a.call(19, generation, serial, 0, 0, 0)
    assert (a.get(0), a.get(1), a.get(4), a.get(9)) == (FAULT, NONE, WH_FAULT, 0)
    returning_to_resume(a)
    finish_resume(a)


def test_health_job_serial_exhaustion_reports_fault(a):
    assert not a.call(23, 0)
    assert (a.get(0), a.get(1), a.get(4), a.get(9)) == (FAULT, NONE, WH_FAULT, 0)


def test_fresh_acquisition_and_successful_sends_do_not_renew_phone_lease(a):
    gesture(a)
    session = a.get(3)
    sequence = a.call(14, session, 0)
    assert a.call(15, session, sequence, 1, 0)
    assert a.call(16, session, sequence, 0)
    for now in range(40, 30000, 40):
        assert observe(a, transaction=1 + now // 40, first=now - 20, count=2) == DELIVER
        sequence = a.call(14, session, now)
        assert sequence and a.call(15, session, sequence, 1, now)
    assert a.get(0) == GESTURE and a.get(29) == 30000
    a.call(4, 30000)
    assert (a.get(0), a.get(1), a.get(6), a.get(20)) == (RETURNING, STOP, 0, 2)


@pytest.mark.parametrize("stage", [QUIESCE, HOLD, START, STOP, RELEASE])
def test_explicit_action_failure_retains_cleanup_or_reports_cleanup_fault(a, stage):
    assert a.call(3, 1, 0)
    if stage != QUIESCE:
        quiet(a)
    if stage in (START, STOP, RELEASE):
        assert physical(a, HELD_PROOF)
    if stage in (STOP, RELEASE):
        assert a.call(3, 0, 0)
    if stage == RELEASE:
        assert physical(a, STOP_PROOF)
    token, session = a.get(2), a.get(3)
    assert a.get(1) == stage
    assert a.call(9, token, session, stage, 0)
    assert (a.get(0), a.get(1)) == ((FAULT, NONE) if stage in (STOP, RELEASE)
                                  else (RETURNING, STOP))
    assert not a.get(6) and not a.get(9)


def test_old_health_ticket_never_starts_or_publishes_after_resume(a):
    generation, serial = a.get(26), a.call(17, 0)
    gesture(a)
    returning_to_resume(a)
    finish_resume(a)
    fresh_serial = a.call(17, 0)
    assert fresh_serial > serial
    assert not a.call(18, generation, serial, 0)
    assert not a.call(20, generation, serial, 0, 1)
    assert a.call(18, a.get(26), fresh_serial, 0)


def test_old_source_send_action_and_health_receipts_cannot_touch_new_session(a):
    gesture(a)
    old_session, old_wh_token, old_generation = a.get(3), a.get(21), a.get(5)
    returning_to_resume(a)
    old_resume_token = a.get(2)
    finish_resume(a)
    gesture(a, now=100)
    before = a.snapshot()
    assert observe(a, session=old_session, now=99999) == IGNORED
    assert not a.call(15, old_session, 1, 0, 99999)
    assert not a.call(16, old_session, 1, 99999)
    assert not a.call(5, old_wh_token, old_generation, 3, 99999)
    assert not physical(a, STOP_PROOF, 99999, token=old_resume_token,
                        session=old_session, action=STOP)
    assert not a.call(13, old_resume_token, 17, 99999)
    assert a.snapshot() == before


@pytest.mark.parametrize("late_action", ["quiesce", "hold", "resume"])
def test_expired_action_receipt_does_not_resurrect(a, late_action):
    assert a.call(3, 1, 0)
    token, generation = a.get(2), a.get(5)
    if late_action == "quiesce":
        assert not a.call(5, token, generation, 3, 3000)
    elif late_action == "hold":
        quiet(a)
        assert not physical(a, HELD_PROOF, 3000)
    else:
        returning_to_resume(a)
        token = a.get(2)
        assert a.call(11, token, 17, 0)
        quiet(a)
        assert a.call(12, token, a.get(5), 17, 1, 1, 0)
        assert not a.call(13, token, 17, 3000)
    assert a.get(0) in (RETURNING, FAULT) and not a.get(9) and not a.get(6)


def test_clock_wrap_integrated_and_stale_first_sample(a):
    now = U32 - 19
    gesture(a, now=now)
    assert observe(a, transaction=2, first=(now + 20) & U32, count=2) == DELIVER
    assert a.get(0) == GESTURE
    returning_to_resume(a, (now + 50) & U32)
    finish_resume(a, (now + 50) & U32)


def test_repeated_end_to_end_sessions_have_no_cursor_or_ticket_reuse(a):
    previous_session = 0
    for n in range(1000):
        now = n * 100
        gesture(a, now)
        assert a.get(3) > previous_session
        previous_session = a.get(3)
        assert a.call(14, previous_session, now) == 1
        assert a.call(15, previous_session, 1, 1, now)
        assert a.call(16, previous_session, 1, now)
        returning_to_resume(a, now + 1)
        finish_resume(a, now + 1, revision=n)
