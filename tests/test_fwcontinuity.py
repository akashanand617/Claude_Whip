"""Real pinned Thumb data path with synthetic I2C and mocked algorithm boundary."""
from pathlib import Path
import ctypes as c
import random
import shutil
import subprocess

import pytest

pytest.importorskip("unicorn", reason="install requirements-firmware-proof.txt for stock execution tests")

from whip.fwcontinuity import (  # noqa: E402
    BUFFER_BYTES, FIFO_DRAIN, SAMPLES, WAKE,
    ProofError, StockMotionHarness,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def stock():
    return (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()


def health_axes(samples):
    return [(second, first, third) for first, second, third in samples]


def batch(n, start=0):
    return [(100 + i, -200 - i, 8005 + i) for i in range(start, start + n)]


@pytest.mark.parametrize("cursor", [0, 6, 180, 480, 486])
@pytest.mark.parametrize("count", [1, 2, 20, 32])
def test_raw_fifo_reads_preserve_every_health_sample(stock, cursor, count):
    h = StockMotionHarness(stock)
    h.set_cursors(cursor, cursor)
    samples = batch(count)
    h.fifo.extend(samples)
    result, seen = h.raw_read(count)
    assert result == 20 and seen == samples
    assert not h.fifo and h.cursor() == (cursor + count * 6) % BUFFER_BYTES
    assert h.cursor(health=True) == cursor  # raw reader never consumes health backlog
    assert h.consume_health() == health_axes(samples)
    assert h.cursor(health=True) == h.cursor()
    assert h.consume_health() == []  # no duplicates


@pytest.mark.parametrize("seed", range(8))
def test_interleaved_raw_reads_match_health_only_baseline(stock, seed):
    plain, gesture = StockMotionHarness(stock), StockMotionHarness(stock)
    rng = random.Random(seed)
    delivered = []
    for index in range(60):
        samples = batch(rng.randrange(1, 33), index * 32)
        delivered.extend(samples)
        plain.fifo.extend(samples)
        gesture.fifo.extend(samples)
        plain.call(FIFO_DRAIN)
        assert gesture.raw_read(len(samples))[1] == samples
        # Additional raw read returns old samples; it MUST NOT renew freshness.
        assert gesture.raw_read(1)[1] == samples[-1:]
        if index % 2 or len(samples) == 32:
            assert gesture.consume_health() == plain.consume_health()
    assert gesture.consume_health() == plain.consume_health()
    assert gesture.health_inputs == plain.health_inputs == health_axes(delivered)


def test_active_wake_discards_unconsumed_health_backlog(stock):
    h = StockMotionHarness(stock)
    h.fifo.extend(batch(5))
    h.call(FIFO_DRAIN)
    assert h.cursor(health=True) == 0 and h.cursor() == 30
    h.call(WAKE)
    assert h.cursor(health=True) == 30
    assert h.consume_health() == []  # negative witness, NOT a desired behavior


@pytest.mark.parametrize("active", [False, True])
def test_cached_raw_values_are_not_freshness(stock, active):
    h = StockMotionHarness(stock)
    h.fifo.extend(batch(1))
    assert h.raw_read()[1] == batch(1)
    h.uc.mem_write(SAMPLES + 1, bytes([active]))
    for _ in range(3):
        code, values = h.raw_read()
        assert values == batch(1)
        assert code == (20 if active else 0)
        assert h.cursor() == 6 and h.cursor(health=True) == 0


def test_full_ring_lap_is_indistinguishable_from_empty(stock):
    h = StockMotionHarness(stock)
    for count in (32, 32, 18):
        h.fifo.extend(batch(count))
        h.call(FIFO_DRAIN)
    assert h.cursor() == h.cursor(health=True) == 0
    assert h.consume_health() == []  # strict pending <82 requirement, not <=82


def test_stock_invalid_third_axis_filter_is_preserved(stock):
    h = StockMotionHarness(stock)
    samples = [(1, 2, 0), (-32768, 32767, -32768), (4, 5, -1), (6, 7, 1)]
    h.fifo.extend(samples)
    assert h.raw_read(4)[1] == samples
    assert h.consume_health() == health_axes([samples[1], samples[3]])


def test_failed_data_read_still_advances_stock_head_with_zero_samples(stock):
    h = StockMotionHarness(stock)
    h.fifo.extend(batch(3))
    h.fifo_data_ok = False
    code, values = h.raw_read(3)
    assert code == 20 and values == [(0, 0, 0)] * 3
    assert h.cursor() == 18 and h.fifo == batch(3)
    assert h.consume_health() == []
    # A source hook must verify successful I2C, not merely a changed head/index.


def test_failed_status_read_does_not_publish_samples(stock):
    h = StockMotionHarness(stock)
    h.fifo.extend(batch(3))
    h.fifo_status_ok = False
    h.call(FIFO_DRAIN)
    assert h.cursor() == h.cursor(health=True) == 0
    assert h.fifo == batch(3)


def test_no_claim_of_arbitrary_firmware_or_peripheral_emulation(stock):
    with pytest.raises(ValueError, match="pinned"):
        StockMotionHarness(stock[:-1])
    h = StockMotionHarness(stock)
    with pytest.raises(ProofError, match="unreviewed execution"):
        h.call(0x450)
    with pytest.raises(ProofError, match="instruction budget"):
        h.call(FIFO_DRAIN, budget=1)


def test_empty_fifo_watchdog_enters_unmodeled_hardware_reset(stock):
    h = StockMotionHarness(stock)
    for _ in range(9):
        h.raw_read()
    with pytest.raises(ProofError, match="unreviewed execution"):
        h.raw_read()  # real stock takes chip-probe/reinitialization path on 10th


def test_read_helpers_reject_ambiguous_counts_and_invalid_cursors(stock):
    h = StockMotionHarness(stock)
    for count in (0, 82, -1):
        with pytest.raises(ValueError):
            h.raw_read(count)
    for cursor in (-6, 1, 492):
        with pytest.raises(ValueError):
            h.set_cursors(cursor, 0)


class Axes(c.Structure):
    _fields_ = [("axis", c.c_int16 * 3)]


class Sample(c.Structure):
    _fields_ = [("sequence", c.c_uint32), ("value", Axes)]


class Tap(c.Structure):
    _fields_ = [("queue", Axes * 32)] + [
        (field, c.c_uint32) for field in ("session", "acquisition", "sequence")
    ] + [("head", c.c_uint8), ("count", c.c_uint8), ("active", c.c_bool), ("fault", c.c_int)]


@pytest.fixture(scope="module")
def tap_api(tmp_path_factory):
    compiler = shutil.which("clang")
    if not compiler:
        pytest.skip("C compiler required")
    out = tmp_path_factory.mktemp("stock-tap") / "tap.so"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                    str(ROOT / "firmware/unified/sample_tap.c"), "-o", str(out)], check=True)
    lib = c.CDLL(str(out))
    ptr = c.POINTER(Tap)
    for name, args, result in [
        ("init", [ptr], None), ("start", [ptr, c.c_uint32, c.c_uint32], c.c_bool),
        ("offer", [ptr, c.c_uint32, c.c_uint32, c.POINTER(Axes), c.c_uint8, c.c_bool], c.c_int),
        ("take", [ptr, c.c_uint32, c.POINTER(Sample)], c.c_bool),
    ]:
        fn = getattr(lib, "wt_" + name)
        fn.argtypes, fn.restype = args, result
    return lib


@pytest.mark.parametrize("fail_consumer", [False, True])
def test_compiled_tap_observes_stock_publication_without_affecting_health(stock, tap_api, fail_consumer):
    """Stock ARM execution + native C observer, NOT a linked ARM stock adapter."""
    h = StockMotionHarness(stock)
    tap = Tap()
    tap_api.wt_init(tap)
    assert tap_api.wt_start(tap, 1, 0)
    acquisition = 0
    results, observed = [], []

    def publish(samples, verified):
        nonlocal acquisition
        acquisition += 1
        array = (Axes * len(samples))(*[Axes((c.c_int16 * 3)(*v)) for v in samples])
        results.append(tap_api.wt_offer(tap, 1, acquisition, array, len(samples), verified))
        if not fail_consumer:
            out = Sample()
            while tap_api.wt_take(tap, 1, out):
                observed.append((out.sequence, tuple(out.value.axis)))

    h.on_publish = publish
    all_samples = []
    for index in range(120):
        samples = batch(20, index * 20)
        all_samples.extend(samples)
        h.fifo.extend(samples)
        h.call(FIFO_DRAIN)
        assert h.consume_health() == health_axes(samples)
    assert h.health_inputs == health_axes(all_samples)
    if fail_consumer:
        assert results[:2] == [0, 3]  # WT_OK, WT_OVERFLOW; subsequent offers stale
        assert not tap.active and tap.count == 0
    else:
        assert results == [0] * 120
        assert observed == list(enumerate(all_samples, start=1))
