"""Lossless receipt storage against the pinned pre-change ARM implementation.

All acquisition metadata is synthetic. This tests representation, selection and
failure behavior; it does not qualify a physical source, RAM owner or task stack.
"""
import ctypes as c
import hashlib
from pathlib import Path
import random

import pytest

from tests.test_fresh_source import (
    api, compiler, CompactReceipt, Delivery, Source, Bound, Axes, U32,
    fresh, receipt, compact_receipt, IGNORED, ACCEPTED, DELIVER, FAULT,
)  # noqa: F401 — native fixtures
from tests.test_unified_thumb import elf  # noqa: F401
from whip.fwthumb import RuntimeThumb

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "firmware/unified/build-20260924-integrated-switch-v1/unified-test-only.elf"
REFERENCE_SHA256 = "8bf55e59526a56c787b16d9d46a623dd8b9d72574d8a01fb6b6a898aeec8c267"


class PriorDelivery(c.Structure):
    _fields_ = [("values", Axes * 32)] + Delivery._fields_[1:]


class SourceThumb(RuntimeThumb):
    def __init__(self, raw, *, prior=False):
        self.delivery_type = PriorDelivery if prior else Delivery
        super().__init__(raw)
        # Same source ABI on both sides; receipt ABI deliberately differs.
        self.context_size = c.sizeof(Source)
        assert self.context_size == 92
        self.uc.mem_write(self.CONTEXT - 16, b"\xA5" * (self.context_size + 32))
        self.encoding = False

    def _read(self, uc, access, address, size, value, opaque):
        if self.OUTPUT <= address < address + size <= self.OUTPUT + c.sizeof(self.delivery_type):
            return
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        if self.OUTPUT <= address < address + size <= self.OUTPUT + c.sizeof(self.delivery_type):
            return
        if self.encoding and self.BATCH <= address < address + size <= self.BATCH + self.batch_length:
            return
        super()._write(uc, access, address, size, value, opaque)

    def observe(self, source, r, now, *, compact=False, no_output=False):
        self.uc.mem_write(self.CONTEXT, bytes(source))
        self.uc.mem_write(self.OUTPUT - 16, b"\xA5" * (c.sizeof(self.delivery_type) + 32))
        if r is None:
            ptr = 0
        elif compact:
            reduced = CompactReceipt()
            for name, _ in reduced._fields_[:-1]:
                setattr(reduced, name, getattr(r, name))
            ptr = self.raw_input(bytes(reduced))
            self.encoding = True
            try:
                for i in range(min(r.count, 32)):
                    self.call("ws_set_bounds", ptr, i, r.acquired[i].earliest, r.acquired[i].latest)
            finally:
                self.encoding = False
        else:
            ptr = self.raw_input(bytes(r))
        before = bytes(self.uc.mem_read(ptr, self.batch_length)) if ptr else None
        result = self.invoke("ws_observe", ptr, 0 if no_output else self.OUTPUT, now & U32)
        if ptr:
            assert bytes(self.uc.mem_read(ptr, self.batch_length)) == before
        assert bytes(self.uc.mem_read(self.OUTPUT - 16, 16)) == b"\xA5" * 16
        assert bytes(self.uc.mem_read(self.OUTPUT + c.sizeof(self.delivery_type), 16)) == b"\xA5" * 16
        return (result, bytes(self.uc.mem_read(self.CONTEXT, self.context_size)),
                bytes(self.uc.mem_read(self.OUTPUT, c.sizeof(self.delivery_type))))


@pytest.fixture(scope="module")
def arms(elf):
    old = (ROOT / REFERENCE).read_bytes()
    assert hashlib.sha256(old).hexdigest() == REFERENCE_SHA256
    return SourceThumb(old, prior=True), SourceThumb(elf)


def compare(arms, api, s, r, now, *, no_output=False):
    old, new = arms
    expected = old.observe(s, r, now, no_output=no_output)
    actual = new.observe(s, r, now, compact=True, no_output=no_output)
    assert actual[:2] == expected[:2]
    previous = PriorDelivery.from_buffer_copy(expected[2])
    current = Delivery.from_buffer_copy(actual[2])
    if no_output:
        assert expected[2] == b"\xA5" * c.sizeof(PriorDelivery)
        assert actual[2] == b"\xA5" * c.sizeof(Delivery)
    else:
        for name in ("session", "acquisition", "oldest_at", "count"):
            assert getattr(current, name) == getattr(previous, name)
        assert current.count <= 8
        assert [tuple(v.axis) for v in current.values] == [tuple(v.axis) for v in previous.values[:8]]
        assert all(tuple(v.axis) == (0, 0, 0) for v in previous.values[8:])
    native, out = Source.from_buffer_copy(s), Delivery()
    c.memset(c.addressof(out), 0xA5, c.sizeof(out))
    assert api.ws_observe(native, r, None if no_output else out, now & U32) == expected[0]
    # C object padding is not an ABI result on the native compiler.
    assert bytes(native)[:91] == expected[1][:91]
    assert bytes(out)[:61] == actual[2][:61]
    return actual[0], Source.from_buffer_copy(actual[1]), current


@pytest.mark.parametrize("start", [0, U32 - 99, 0x7FFFFFF0])
@pytest.mark.parametrize("period", [1, 10, 13, 20, 40])
def test_compact_and_prior_arm_select_identical_full_streams(arms, api, start, period):
    s = fresh(api, start=start, period=period)
    selected = []
    # Vary transaction sizes, including multi-frame batches. Never change the
    # profile or Health's raw bytes to make the storage representation fit.
    offset = 0
    for count in (1, 2, 3, 1, 4, 2, 5, 1):
        times = tuple(start + offset + i * period for i in range(count))
        r = receipt(times, transaction=s.transaction + 1)
        now = times[-1] + 2
        r.completed_at = now & U32
        result, s, d = compare(arms, api, s, r, now)
        assert result in (ACCEPTED, DELIVER)
        if result == DELIVER:
            selected.extend(tuple(v.axis) for v in d.values[:d.count])
        offset += count * period
    assert selected and s.active


def test_compiled_scratch_bound_covers_every_window_phase(arms):
    _, current = arms
    assert current.call("proof_source_delivery_frames") == 8
    assert current.call("proof_source_delivery_size") == c.sizeof(Delivery) == 64
    # All possible first-endpoint phases and all spans allowed by <250ms.
    # This deliberately uses the conservative window-only bound; it does not
    # assume a valid prior bucket/physical cadence to squeeze it down to seven.
    largest = 0
    for phase in range(40):
        for span in range(250):
            buckets = (phase + span) // 40 - phase // 40 + 1
            assert buckets <= 8
            largest = max(largest, buckets)
    assert largest == 8


@pytest.mark.parametrize("start", [0, U32 - 19, 0x7FFFFFF0])
def test_maximum_healthy_batch_and_boundary_phases_match_prior_arm(arms, api, start):
    for phase in range(40):
        s = fresh(api, start=start, period=40)
        times = tuple(start + t for t in range(phase, 250, 40))
        r = receipt(times)
        result, after, d = compare(arms, api, s, r, times[-1])
        assert result == DELIVER and d.count == len(times) and d.count in (6, 7)
        assert after.active and d.oldest_at == times[0] & U32


@pytest.mark.parametrize("start", [0, U32 - 19])
def test_nonzero_acquisition_uncertainty_remains_exact(arms, api, start):
    for phase in (0, 10, 37):
        for width in (1, 2):
            s = fresh(api, start=start, period=20)
            s.profile.minimum_period_ms, s.profile.maximum_period_ms = 18, 22
            times = tuple(start + phase + i * 20 for i in range(8))
            r = receipt(times)
            for b in r.acquired[:r.count]: b.latest = (b.latest + width) & U32
            r.status_at = (times[-1] + width) & U32
            r.completed_at = (times[-1] + width + 1) & U32
            result, after, d = compare(arms, api, s, r, r.completed_at)
            assert result == DELIVER and d.count in (4, 5) and after.active


@pytest.mark.parametrize("start", [0, U32 - 19, 0x7FFFFFF0])
def test_conservative_eight_frame_bound_does_not_assume_valid_prior_progress(arms, api, start):
    s = fresh(api, start=start, period=10)
    s.profile.minimum_period_ms, s.profile.maximum_period_ms = 1, 40
    # Deliberately inconsistent externally populated state, NOT a valid API
    # history or physical witness. The old observer admits eight selections
    # here. Keep that behavior and its guards instead of assuming a seventh-slot
    # bound that would depend on stronger retained-state invariants.
    s.have_frame, s.have_bucket = True, False
    s.last_earliest = s.last_latest = (start + 38) & U32
    times = tuple(start + t for t in (39, 79, 119, 159, 199, 239, 279, 280))
    r = receipt(times)
    for i in range(8): r.bytes[6 * i] = i + 1
    result, after, d = compare(arms, api, s, r, start + 280)
    assert result == DELIVER and d.count == 8 and after.active
    assert [v.axis[0] for v in d.values] == [i + 1 - 32768 for i in range(8)]


@pytest.mark.parametrize("start", [0, U32 - 19])
@pytest.mark.parametrize("count", [7, 8])
def test_native_compact_delivery_has_exact_writable_extent(api, start, count):
    class Guarded(c.Structure):
        _fields_ = [("before", c.c_uint8 * 16), ("delivery", Delivery), ("after", c.c_uint8 * 16)]
    for late_fault in (False, True):
        g = Guarded()
        c.memset(c.addressof(g), 0xA5, c.sizeof(g))
        s = fresh(api, start=start, period=40)
        offsets = tuple(range(0, 241, 40))
        if count == 8:
            s.profile.minimum_period_ms, s.profile.maximum_period_ms = 1, 40
            s.have_frame, s.have_bucket = True, False
            s.last_earliest = s.last_latest = (start + 38) & U32
            offsets = (39, 79, 119, 159, 199, 239, 279, 280)
        r = receipt(tuple(start + t for t in offsets))
        if late_fault:
            r.acquired[count - 1].latest = (r.acquired[count - 1].latest + 3) & U32
            r.status_at = r.completed_at = (start + offsets[-1] + 3) & U32
        result = api.ws_observe(s, r, g.delivery, r.completed_at)
        assert result == (FAULT if late_fault else DELIVER)
        assert bytes(g.before) == bytes(g.after) == b"\xA5" * 16
        assert g.delivery.count == (0 if late_fault else count)
        if late_fault: assert bytes(g.delivery) == bytes(64)


@pytest.mark.parametrize("start", [0, U32 - 99])
def test_old_new_arm_boundary_and_corruption_agreement(arms, api, start):
    rng = random.Random(0xA6E)
    cases = []
    for field, value in (
        ("config_epoch", 2), ("binding_id", 9), ("transaction", 0), ("transaction", 2),
        ("fifo_status", 0x81), ("fifo_status", 0xA0), ("fifo_status", 0),
        ("transport_result", 1), ("requested_bytes", 5), ("completed_bytes", 0),
        ("completed_bytes", 7), ("count", 33), ("session", 2),
    ):
        r = receipt((start,))
        setattr(r, field, value)
        cases.append((r, start))
    for delta in (-0x80000000, -65536, -257, -256, -250, -249, -1,
                  0, 1, 2, 39, 40, 249, 250, 255, 256, 257, 65536, 0x7FFFFFFF):
        for field in ("status_at", "completed_at", "earliest", "latest", "now"):
            r, now = receipt((start,)), start
            if field in ("earliest", "latest"):
                setattr(r.acquired[0], field, (start + delta) & U32)
            elif field == "now": now += delta
            else: setattr(r, field, (start + delta) & U32)
            cases.append((r, now))
    # Arbitrary endpoint words exercise wrap/poison without deriving them from
    # the new encoder. Explicit cases above retain meaningful near-boundary data.
    for _ in range(40):
        r = receipt((start,))
        r.acquired[0] = Bound(rng.getrandbits(32), rng.getrandbits(32))
        cases.append((r, start))
    for r, now in cases:
        compare(arms, api, fresh(api, start=start), r, now)


@pytest.mark.parametrize("prior_batch", [False, True])
def test_arm_late_failures_never_commit_partial_progress(arms, api, prior_batch):
    s = fresh(api)
    first = 0
    if prior_batch:
        _, s, _ = compare(arms, api, s, receipt((0, 20, 40, 60, 80)), 80)
        first = 100
    for index in range(12):
        r = receipt(tuple(range(first, first + 240, 20)), transaction=s.transaction + 1)
        # Remains byte-encodable even at the last frame; rejected inside the
        # observer, after earlier output scratch writes. Not an encoder poison.
        r.status_at = r.completed_at = first + 223
        r.acquired[index].latest += 3
        encoded = compact_receipt(api, r)
        assert encoded.transport_result == 0
        result, out, d = compare(arms, api, s, r, first + 223)
        assert result == FAULT and not out.active and not d.count
        out.active = s.active
        assert bytes(out)[:91] == bytes(s)[:91]


def test_arm_empty_exhausted_null_and_old_session_agreement(arms, api):
    s = fresh(api)
    for r in (None, receipt(())):
        compare(arms, api, s, r, 0)
    compare(arms, api, s, receipt(), 0, no_output=True)
    for field in ("transaction", "acquisition"):
        exhausted = Source.from_buffer_copy(s)
        setattr(exhausted, field, U32)
        assert compare(arms, api, exhausted, receipt(), 0)[0] == FAULT
    assert compare(arms, api, s, receipt(session=2), 9000)[0] == IGNORED
    s.active = False
    assert compare(arms, api, s, receipt(), 9000)[0] == IGNORED


def test_arm_encoder_indices_and_sticky_error(arms):
    _, h = arms
    assert not h.call("ws_set_bounds", 0, 0, 0, 0)
    for index in (0, 31, 32, U32):
        r = CompactReceipt(status_at=0, transport_result=7)
        ptr = h.raw_input(bytes(r))
        h.encoding = True
        try:
            assert bool(h.call("ws_set_bounds", ptr, index, U32, U32)) == (index < 32)
            saved = CompactReceipt.from_buffer_copy(bytes(h.uc.mem_read(ptr, c.sizeof(r))))
            assert saved.transport_result == (7 if index < 32 else 1)
            if index < 32:
                assert saved.acquired[index].earliest_age == saved.acquired[index].latest_age == 1
        finally:
            h.encoding = False


@pytest.mark.parametrize("status", [0, U32 - 99])
def test_checked_encoder_boundaries_canaries_and_sticky_failure(api, status):
    class Guarded(c.Structure):
        _fields_ = [("before", c.c_uint8 * 16), ("receipt", CompactReceipt),
                    ("after", c.c_uint8 * 16)]
    assert c.sizeof(CompactReceipt) == 288
    assert CompactReceipt.bytes.offset == 31 and CompactReceipt.acquired.offset == 223
    ages = (-0x80000000, -65536, -256, -1, 0, 1, 249, 250, 255, 256, 257, 65536, 0x7FFFFFFF)
    for index in (0, 31, 32, U32):
        for first in ages:
            for last in ages:
                g = Guarded()
                c.memset(c.addressof(g), 0xA5, c.sizeof(g))
                g.receipt.status_at = status
                g.receipt.transport_result = 7  # Encoding may not clear I/O error.
                expected = bytearray(bytes(g))
                valid = index < 32 and 0 <= last <= first < 250
                if valid:
                    pos = 16 + CompactReceipt.acquired.offset + 2 * index
                    expected[pos:pos + 2] = bytes((first, last))
                else:
                    expected[16 + CompactReceipt.transport_result.offset] = 1
                assert bool(api.ws_set_bounds(g.receipt, index, (status - first) & U32,
                                              (status - last) & U32)) == valid
                assert bytes(g) == expected
    assert not api.ws_set_bounds(None, 0, 0, 0)


@pytest.mark.parametrize("start", [0, U32 - 99])
def test_every_raw_age_pair_against_independent_window_predicate(api, start):
    # All 65536 representations, bypassing the encoder: malformed raw ages
    # must fail too. At status=start+249 the first 40ms bucket requires ages
    # 210..249; both endpoints must stay in it and uncertainty is at most 2ms.
    original = fresh(api, start=start)
    r = CompactReceipt(session=1, config_epoch=1, binding_id=2, transaction=1,
                       status_at=(start + 249) & U32, completed_at=(start + 249) & U32,
                       requested_bytes=6, completed_bytes=6, fifo_status=1, count=1)
    for first in range(256):
        for last in range(256):
            s, d = Source.from_buffer_copy(original), Delivery()
            r.acquired[0].earliest_age, r.acquired[0].latest_age = first, last
            result = api.compact_observe(s, r, d, (start + 249) & U32)
            valid = 210 <= last <= first <= 249 and first - last <= 2
            assert result == (DELIVER if valid else FAULT)
            assert s.active == valid and d.count == int(valid)
            if valid:
                assert d.oldest_at == (start + 249 - first) & U32
            else:
                assert bytes(d) == bytes(c.sizeof(d))


def test_full_unmasked_fifo_status_and_count_space(api):
    # Full status equality must retain the old overflow rejection. Exercise
    # every u8 status/count pair, including malformed counts beyond the array.
    original = fresh(api, period=1)
    for count in range(256):
        now = max(0, count - 1) if count <= 32 else 0
        r = CompactReceipt(session=1, config_epoch=1, binding_id=2, transaction=1,
                           status_at=now, completed_at=now, count=count,
                           requested_bytes=count * 6, completed_bytes=count * 6)
        for i in range(min(count, 32)):
            if count <= 32:
                assert api.ws_set_bounds(r, i, i, i)
        for status in range(256):
            s, d = Source.from_buffer_copy(original), Delivery()
            r.fifo_status = status
            result = api.compact_observe(s, r, d, now)
            expected = (ACCEPTED if not count else DELIVER) if count == status < 32 else FAULT
            assert result == expected
            assert s.active == (expected != FAULT)
