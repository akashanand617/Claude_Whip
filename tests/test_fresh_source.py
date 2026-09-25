"""Synthetic physical receipts only: no qualified sensor profile or ring I/O."""
import ctypes as c
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
IGNORED, ACCEPTED, DELIVER, FAULT = range(4)
U32 = 0xFFFFFFFF


class Profile(c.Structure):
    _fields_ = [("config_epoch", c.c_uint32), ("binding_id", c.c_uint32),
                ("evidence_sha256", c.c_uint8 * 32),
                ("observed_frames", c.c_uint32), ("observed_span_ms", c.c_uint32),
                ("minimum_period_ms", c.c_uint16), ("maximum_period_ms", c.c_uint16)] + [
        (n, c.c_uint8) for n in ("timestamp_uncertainty_ms", "chip_id", "range",
                                "bandwidth", "power", "fifo_config")]


class Bound(c.Structure):
    _fields_ = [("earliest", c.c_uint32), ("latest", c.c_uint32)]


class Receipt(c.Structure):
    # Absolute-time test oracle shape retained unchanged. Conversion at the API
    # boundary uses the production checked encoder, never unchecked byte casts.
    _fields_ = [(n, c.c_uint32) for n in ("session", "config_epoch", "binding_id",
                "transaction", "status_at", "completed_at")] + [
        ("requested_bytes", c.c_uint16), ("completed_bytes", c.c_uint16),
        ("fifo_status", c.c_uint8), ("transport_result", c.c_uint8), ("count", c.c_uint8),
        ("bytes", c.c_uint8 * 192), ("acquired", Bound * 32)]


class AgeBound(c.Structure):
    _fields_ = [("earliest_age", c.c_uint8), ("latest_age", c.c_uint8)]


class CompactReceipt(c.Structure):
    _fields_ = Receipt._fields_[:-1] + [("acquired", AgeBound * 32)]


def compact_receipt(lib, r):
    if r is None: return None
    out = CompactReceipt()
    # Copy only common fields, preserving deliberately malformed count/status.
    for name, _ in Receipt._fields_[:-1]: setattr(out, name, getattr(r, name))
    for i in range(min(r.count, 32)):
        lib.ws_set_bounds(out, i, r.acquired[i].earliest, r.acquired[i].latest)
    return out


class Axes(c.Structure):
    _fields_ = [("axis", c.c_int16 * 3)]


class Delivery(c.Structure):
    _fields_ = [("values", Axes * 8)] + [(n, c.c_uint32) for n in (
        "session", "acquisition", "oldest_at")] + [("count", c.c_uint8)]


class Source(c.Structure):
    _fields_ = [("profile", Profile)] + [(n, c.c_uint32) for n in (
        "session", "transaction", "acquisition", "started_at", "last_earliest",
        "last_latest", "last_bucket")] + [(n, c.c_bool) for n in (
        "active", "have_frame", "have_bucket")]


@pytest.fixture(scope="module")
def compiler():
    found = shutil.which("clang") or shutil.which("cc")
    if not found:
        pytest.skip("C compiler required")
    return found


@pytest.fixture(scope="module")
def api(tmp_path_factory, compiler):
    output = tmp_path_factory.mktemp("fresh-source") / "source.so"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    str(ROOT / "firmware/unified/fresh_source.c"), "-o", str(output)], check=True)
    lib = c.CDLL(str(output))
    signatures = {
        "profile_valid": ([c.POINTER(Profile)], c.c_bool),
        "init": ([c.POINTER(Source)], None),
        "start": ([c.POINTER(Source), c.c_uint32, c.POINTER(Profile), c.c_uint32], c.c_bool),
        "stop": ([c.POINTER(Source), c.c_uint32], None),
        "tick": ([c.POINTER(Source), c.c_uint32], c.c_bool),
        "observe": ([c.POINTER(Source), c.POINTER(CompactReceipt), c.POINTER(Delivery), c.c_uint32], c.c_int),
        "set_bounds": ([c.POINTER(CompactReceipt), c.c_uint32, c.c_uint32, c.c_uint32], c.c_bool),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, "ws_" + name)
        fn.argtypes, fn.restype = args, result
    lib.compact_observe = lib.ws_observe
    lib.ws_observe = lambda s, r, d, now: lib.compact_observe(s, compact_receipt(lib, r), d, now)
    return lib


def profile(period=20):
    p = Profile(config_epoch=1, binding_id=2, observed_frames=101,
                observed_span_ms=period * 100, minimum_period_ms=period,
                maximum_period_ms=period, timestamp_uncertainty_ms=2,
                chip_id=0x23, range=5, bandwidth=15, power=0x74, fifo_config=0xC8)
    # Test-only made-up identifier; never exported as a qualified profile.
    p.evidence_sha256[0] = 0xEE
    return p


def fresh(api, start=0, period=20):
    s, p = Source(), profile(period)
    api.ws_init(s)
    assert api.ws_start(s, 1, p, start)
    return s


def test_start_can_copy_its_own_retained_profile_across_sessions(api):
    s = Source()
    s.profile = profile()
    before = bytes(s.profile)
    for session in (1, 2, 3):
        assert api.ws_start(s, session, c.byref(s.profile), session * 40)
        assert bytes(s.profile) == before and s.active and s.session == session
        assert not api.ws_start(s, session + 1, c.byref(s.profile), session * 40)
        assert bytes(s.profile) == before
        api.ws_stop(s, session)
    assert not api.ws_start(s, 3, c.byref(s.profile), 200)


def receipt(times=(0,), session=1, transaction=1, completed=None):
    r = Receipt(session=session, config_epoch=1, binding_id=2, transaction=transaction,
                count=len(times), fifo_status=len(times), requested_bytes=len(times) * 6,
                completed_bytes=len(times) * 6)
    r.status_at = times[-1] & U32 if times else 0
    r.completed_at = r.status_at if completed is None else completed & U32
    for i, t in enumerate(times):
        r.acquired[i] = Bound(t & U32, t & U32)
        # Includes signed extremes and a genuine zero, not a sentinel.
        raw = b"\x00\x80\xff\x7f\x00\x00"
        for j, v in enumerate(raw):
            r.bytes[i * 6 + j] = v
    return r


@pytest.mark.parametrize("field,value", [
    ("config_epoch", 0), ("binding_id", 0), ("observed_frames", 0),
    ("observed_frames", U32), ("observed_span_ms", 1),
    ("minimum_period_ms", 0), ("maximum_period_ms", 41),
    ("maximum_period_ms", 19), ("timestamp_uncertainty_ms", 40),
    ("chip_id", 0x22), ("range", 8), ("bandwidth", 10),
    ("power", 0x7C), ("fifo_config", 0xC0),
])
def test_invalid_profile_refused_before_start(api, field, value):
    p, s = profile(), Source()
    setattr(p, field, value)
    assert not api.ws_profile_valid(p)
    assert not api.ws_start(s, 1, p, 0)
    assert not s.active


def test_absent_evidence_or_profile_is_closed(api):
    p, s = profile(), Source()
    p.evidence_sha256[0] = 0
    assert not api.ws_profile_valid(p)
    assert not api.ws_profile_valid(None)
    assert not api.ws_start(s, 1, None, 0)


@pytest.mark.parametrize("period", [10, 13, 20, 40])
def test_physical_bucket_selection_not_fixed_decimation(api, period):
    s, d = fresh(api, period=period), Delivery()
    selected = []
    originals = []
    for n, t in enumerate(range(0, 1000, period), 1):
        r = receipt((t,), transaction=n)
        before = bytes(r)
        result = api.ws_observe(s, r, d, t)
        assert result in (ACCEPTED, DELIVER)
        assert bytes(r) == before  # No Health-owned input mutation.
        if result == DELIVER:
            assert d.count == 1 and d.acquisition == len(selected) + 1
            assert tuple(d.values[0].axis) == (-32768, 32767, 0)
            selected.append(d.oldest_at)
            originals.append(t)
    assert len(selected) == 25
    assert selected == originals and [t // 40 for t in selected] == list(range(25))


def test_all_or_nothing_copy_and_no_axis_reordering(api):
    s, d = fresh(api), Delivery()
    r = receipt((0, 20, 40, 60, 80))
    r.bytes[12:18] = (1, 0, 2, 0, 3, 0)
    assert api.ws_observe(s, r, d, 80) == DELIVER
    assert d.count == 3 and d.oldest_at == 0
    assert tuple(d.values[1].axis) == (1, 2, 3)
    r.bytes[12] = 99
    assert d.values[1].axis[0] == 1


@pytest.mark.parametrize("bad_index", range(12))
@pytest.mark.parametrize("prior_batch", [False, True])
def test_late_rejection_clears_scratch_and_commits_no_progress(api, bad_index, prior_batch):
    s, d = fresh(api), Delivery()
    first = 0
    if prior_batch:
        assert api.ws_observe(s, receipt((0, 20, 40, 60, 80)), d, 80) == DELIVER
        first = 100
    expected = Source.from_buffer_copy(s)
    expected.active = False
    r = receipt(tuple(range(first, first + 240, 20)), transaction=s.transaction + 1)
    # For later indices, earlier samples already filled caller-owned scratch.
    r.acquired[bad_index].latest += 3
    before = bytes(r)
    c.memset(c.addressof(d), 0xA5, c.sizeof(d))
    assert api.ws_observe(s, r, d, first + 223) == FAULT
    assert bytes(r) == before and bytes(s) == bytes(expected)
    assert (d.session, d.acquisition, d.oldest_at, d.count) == (0, 0, 0, 0)
    assert all(tuple(v.axis) == (0, 0, 0) for v in d.values)


def test_arm_selector_local_stack_budget(tmp_path, compiler):
    # This guards only a compiled local frame, NOT ring-task stack headroom or
    # nested calls/interrupts. Keep the caller-owned delivery from being copied
    # back onto this already stack-constrained path.
    target = tmp_path / "source.o"
    subprocess.run([compiler, "--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
                    "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11",
                    "-Wall", "-Wextra", "-Werror", "-fstack-usage", "-c",
                    str(ROOT / "firmware/unified/fresh_source.c"), "-o", str(target)], check=True)
    frames = [line.split("\t") for line in target.with_suffix(".su").read_text().splitlines()]
    selected = [parts for parts in frames if parts[0].endswith(":ws_observe")]
    assert len(selected) == 1
    assert selected[0][2] == "static" and 0 < int(selected[0][1]) <= 112


def test_post_decode_exhaustion_clears_scratch_and_commits_no_progress(api):
    s, d = fresh(api), Delivery()
    s.acquisition = U32
    expected = Source.from_buffer_copy(s)
    expected.active = False
    r = receipt((0, 20, 40, 60, 80))
    assert api.ws_observe(s, r, d, 80) == FAULT
    assert bytes(s) == bytes(expected)
    assert (d.session, d.acquisition, d.oldest_at, d.count) == (0, 0, 0, 0)
    assert all(tuple(v.axis) == (0, 0, 0) for v in d.values)


@pytest.mark.parametrize("field,value", [
    ("config_epoch", 2), ("binding_id", 9), ("transaction", 0), ("transaction", 2),
    ("fifo_status", 0x81), ("fifo_status", 0xA0), ("fifo_status", 0),
    ("transport_result", 1), ("requested_bytes", 5), ("completed_bytes", 0),
    ("completed_bytes", 7), ("count", 33), ("status_at", U32),
    ("completed_at", 1),
])
def test_bad_receipt_fails_without_delivery(api, field, value):
    s, r, d = fresh(api), receipt(), Delivery(count=9)
    setattr(r, field, value)
    assert api.ws_observe(s, r, d, 0) == FAULT
    assert not s.active and d.count == 0 and s.transaction == 0
    assert not api.ws_start(s, 1, profile(), 0)


def test_full_fifo_or_unbounded_i2c_latency_has_no_overflow_proof(api):
    for count, span in ((32, 0), (30, 40), (1, 249)):
        s, d = fresh(api, period=1), Delivery()
        r = receipt(tuple(range(count)), completed=count - 1 + span)
        assert api.ws_observe(s, r, d, r.completed_at) == FAULT
        assert not s.active and not d.count


def test_headroom_boundary_and_empty_transactions(api):
    s, d = fresh(api, period=1), Delivery()
    assert api.ws_observe(s, receipt(tuple(range(31))), d, 30) == DELIVER
    empty = receipt((), transaction=2)
    empty.status_at = empty.completed_at = 31
    assert api.ws_observe(s, empty, d, 31) == ACCEPTED
    assert d.count == 0 and s.transaction == 2
    assert api.ws_tick(s, 279)
    assert not api.ws_tick(s, 280)  # Empty snapshots cannot renew physical age.


@pytest.mark.parametrize("times", [(40,), (0, 40), (0, 0), (0, 19), (0, 21)])
def test_cached_missing_out_of_order_or_wrong_period_not_fresh(api, times):
    s, r, d = fresh(api), receipt(times), Delivery()
    assert api.ws_observe(s, r, d, max(times)) == FAULT
    assert d.count == 0 and s.transaction == 0


def test_timestamp_bound_cannot_straddle_bucket_or_overlap_previous(api):
    s, r, d = fresh(api, period=1), receipt((0, 39)), Delivery()
    s.profile.maximum_period_ms = 40
    r.acquired[1].latest = 41
    r.status_at = r.completed_at = 41
    assert api.ws_observe(s, r, d, 41) == FAULT
    s = fresh(api, period=1)
    s.profile.timestamp_uncertainty_ms = 20
    s.profile.maximum_period_ms = 40
    r = receipt((10, 15))
    r.acquired[0].latest = 20
    r.acquired[1].latest = 25
    r.status_at = r.completed_at = 25
    assert api.ws_observe(s, r, d, 25) == FAULT


def test_no_clock_future_callback_time_or_stale_acquisition(api):
    for earliest, latest, status, now in ((0, 0, 250, 250), (1, 1, 0, 0),
                                          (0, 3, 3, 3), (U32, U32, 0, 0)):
        s, r, d = fresh(api), receipt(), Delivery()
        r.acquired[0] = Bound(earliest, latest)
        r.status_at = r.completed_at = status
        assert api.ws_observe(s, r, d, now) == FAULT


def test_clock_wrap_and_expiration(api):
    start, d = U32 - 19, Delivery()
    s = fresh(api, start=start)
    r = receipt((start, start + 20, start + 40))
    assert api.ws_observe(s, r, d, (start + 40) & U32) == DELIVER
    assert d.count == 2 and d.oldest_at == start
    assert api.ws_tick(s, (start + 289) & U32)
    assert not api.ws_tick(s, (start + 290) & U32)


def test_old_sessions_stop_and_replay_never_reactivate(api):
    s, d = fresh(api), Delivery()
    assert api.ws_observe(s, receipt(), d, 0) == DELIVER
    assert api.ws_observe(s, receipt(), d, 0) == FAULT
    assert not api.ws_start(s, 1, profile(), 0)
    assert api.ws_start(s, 2, profile(), 20)
    saved = bytes(s)
    assert api.ws_observe(s, receipt(session=1), d, 9000) == IGNORED
    api.ws_stop(s, 1)
    assert bytes(s) == saved
    api.ws_stop(s, 2)
    assert not s.active and not api.ws_start(s, 2, profile(), 20)


def test_counter_exhaustion_and_null_output_close(api):
    for field in ("transaction", "acquisition"):
        s, r, d = fresh(api), receipt(), Delivery()
        setattr(s, field, U32)
        assert api.ws_observe(s, r, d, 0) == FAULT
        assert not d.count
    s = fresh(api)
    assert api.ws_observe(s, receipt(), None, 0) == FAULT


def test_native_source_stress(tmp_path, compiler):
    output = tmp_path / "source-stress"
    subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=undefined", "-fno-sanitize-recover=all",
                    "-I", str(ROOT / "firmware/unified"),
                    str(ROOT / "firmware/unified/fresh_source.c"),
                    str(ROOT / "tests/native/fresh_source_stress.c"), "-o", str(output)], check=True)
    result = json.loads(subprocess.check_output([str(output)], text=True))
    assert result["sessions"] == 10000 and result["delivered"] == 250000
