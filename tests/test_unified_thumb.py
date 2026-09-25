"""Execute compiled C integration on ARM. No stock linker placement is implied."""
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess

import pytest

pytest.importorskip("unicorn", reason="requires requirements-firmware-proof.txt")
pytest.importorskip("elftools", reason="requires requirements-firmware-proof.txt")

from whip.fwthumb import RuntimeThumb, ThumbProofError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HEALTH, ENTERING, GESTURE, RETURNING, FAULT = range(5)
NONE, QUIESCE, HOLD, START, STOP, RELEASE, RESUME = range(7)


@pytest.fixture(scope="module")
def elf(tmp_path_factory):
    pinned = os.environ.get("WHIP_UNIFIED_TEST_ELF")
    if pinned:
        return Path(pinned).read_bytes()
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    compiler = shutil.which("clang")
    if not zig or not compiler:
        pytest.skip("provide WHIP_ZIG or the prebuilt WHIP_UNIFIED_TEST_ELF")
    work = tmp_path_factory.mktemp("arm-link")
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb",
             "-ffreestanding", "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "firmware/unified")]
    from probe.unified_build import SOURCES, SUPPORT_SOURCES
    sources = [f"firmware/unified/{name}.c" for name in SOURCES]
    sources += list(SUPPORT_SOURCES)
    objects = []
    for source in sources:
        out = work / (Path(source).stem + ".o")
        subprocess.run([compiler, *flags, "-c", str(ROOT / source), "-o", str(out)], check=True)
        objects.append(str(out))
    out = work / "unified-test-only.elf"
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(work / "cache"), ZIG_LOCAL_CACHE_DIR=str(work / "local"))
    subprocess.run([zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
                    "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"), "-Wl,-e,wr_init",
                    "-Wl,--build-id=none", "-Wl,--no-undefined", "-o", str(out), *objects],
                   env=env, check=True)
    return out.read_bytes()


@pytest.fixture
def arm(elf):
    h = RuntimeThumb(elf)
    h.invoke("wr_init")
    assert h.word(0) == HEALTH
    assert h.call("proof_tap_offset") == 36
    return h


def enter(h, now=0, baseline=0):
    h.invoke("wr_link", 1, 0, now)
    assert h.invoke("wr_request", 1, now)
    for action in (QUIESCE, HOLD, START):
        assert h.word(4) == action
        assert h.invoke("wr_complete", h.word(12), 1, baseline, now)
    assert h.word(0) == GESTURE
    return h.word(16)


def restore(h, now=0):
    for action in (STOP, RELEASE, RESUME):
        assert h.word(0) == RETURNING and h.word(4) == action
        assert h.invoke("wr_complete", h.word(12), 1, 0, now)
    assert h.word(0) == HEALTH


def offer(h, session, acquisition, count=1, verified=1, now=0, oldest_at=None):
    ptr = h.batch([(123, -8005, 32767)] * count)
    return h.invoke("wr_offer", session, acquisition, ptr, count, verified,
                    now if oldest_at is None else oldest_at, now)


def test_actual_linked_thumb_end_to_end(arm):
    h = arm
    session = enter(h, baseline=10)
    assert not h.invoke("wr_renew", session, 1, 1)  # no sent data
    assert offer(h, session, 11, count=3) == 0
    for sequence in (1, 2, 3):
        assert h.invoke("wr_next", session, h.OUTPUT, 1)
        assert h.output() == (sequence, (123, -8005, 32767))
        assert not h.invoke("wr_next", session, h.OUTPUT, 1)  # one in flight
        assert not h.invoke("wr_renew", session, sequence, 1)  # not yet sent
        assert h.invoke("wr_sent", session, sequence, 1, 1)
        assert h.invoke("wr_renew", session, sequence, 1)
        assert not h.invoke("wr_renew", session, sequence, 2)  # replay
        assert not h.invoke("wr_renew", session, sequence + 1, 2)  # future
    assert h.invoke("wr_request", 0, 3)
    restore(h, 3)
    assert not h.invoke("wr_next", session, h.OUTPUT, 3)


def test_actual_thumb_unsigned_division_support(arm):
    rng = random.Random(0xD171DE)
    edges = (0, 1, 2, 3, 10, 40, 249, 250, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFE, 0xFFFFFFFF)
    cases = [(n, d) for n in edges for d in edges if d]
    cases += [(rng.randrange(2**32), rng.randrange(1, 2**32)) for _ in range(512)]
    for numerator, denominator in cases:
        assert arm.call("__aeabi_uidiv", numerator, denominator) == numerator // denominator
    # Not a production division-by-zero ABI claim: this helper defines zero.
    assert arm.call("__aeabi_uidiv", 17, 0) == 0


@pytest.mark.parametrize("destination,source,length", [(4, 0, 24), (0, 4, 24), (0, 0, 28), (0, 4, 0)])
def test_actual_thumb_overlapping_memmove_support(arm, destination, source, length):
    initial = bytes(range(32))
    for offset in range(0, 32, 4):
        arm.write_word(offset, int.from_bytes(initial[offset:offset + 4], "little"))
    expected = bytearray(initial)
    expected[destination:destination + length] = initial[source:source + length]
    arm.call("__aeabi_memmove4", arm.CONTEXT + destination, arm.CONTEXT + source, length)
    assert bytes(arm.uc.mem_read(arm.CONTEXT, 32)) == bytes(expected)


class AdapterThumb(RuntimeThumb):
    CONTEXT_SIZE_SYMBOL = "proof_adapter_size"
    CONTEXT_MAX_BYTES = 2048

    def op(self, operation, *values):
        assert len(values) <= 12
        data = struct.pack("<12I", *(v & 0xFFFFFFFF for v in values), *([0] * (12 - len(values))))
        return self.invoke("proof_adapter_call", operation, self.raw_input(data))

    def get(self, key):
        return self.invoke("proof_adapter_get", key)


@pytest.fixture
def integrated(elf):
    h = AdapterThumb(elf)
    assert h.op(0, 0x1F, 1, 1)  # Explicitly invented profile; no production binding.
    h.op(2, 1, 0, 0)
    return h


def adapter_quiet(h, now):
    token, generation = h.get(2), h.get(5)
    assert h.op(5, token, generation, 0x1F, now)
    assert h.op(6, token, generation, now)
    assert h.op(7, token, generation, 1, now)


def adapter_start_pending(h, now=0):
    assert h.op(3, 1, now)
    assert (h.get(0), h.get(1), h.get(9)) == (ENTERING, QUIESCE, 0)
    adapter_quiet(h, now)
    token, session = h.get(2), h.get(3)
    assert h.op(8, token, session, HOLD, 0x0F, 1, 2, now)
    assert (h.get(0), h.get(1), h.get(6)) == (ENTERING, START, 1)
    # A generic action receipt cannot declare a fresh producer started.
    assert not h.op(8, h.get(2), session, START, 0xFFFFFFFF, 1, 2, now)
    return session


def adapter_restore(h, now, revision=7):
    assert h.op(3, 0, now)
    assert (h.get(0), h.get(1), h.get(6)) == (RETURNING, STOP, 0)
    session = h.get(3)
    assert h.op(8, h.get(2), session, STOP, 0x70, 1, 2, now)
    assert h.op(8, h.get(2), session, RELEASE, 0x82, 1, 2, now)
    token = h.get(2)
    assert h.op(11, token, revision, now)
    if not h.get(16):
        adapter_quiet(h, now)
    assert h.op(12, token, h.get(5), revision, 1, 1, now)
    assert (h.get(0), h.get(9)) == (RETURNING, 0)
    # The binding must reread current settings at the final atomic commit.
    assert not h.op(13, token, revision + 1, now)
    assert h.get(0) == RETURNING and h.get(9) == 0
    assert h.op(12, token, h.get(5), revision + 1, 1, 1, now)
    assert h.op(13, token, revision + 1, now)
    assert (h.get(0), h.get(9), h.get(6)) == (HEALTH, 1, 0)


@pytest.mark.parametrize("bad_index", range(12))
def test_thumb_late_batch_failure_never_starts_or_publishes(integrated, bad_index):
    h = integrated
    session = adapter_start_pending(h)
    assert h.op(10, session, 1, 0, 12, 223, 223, 223, 128, bad_index) == 3
    assert (h.get(0), h.get(1), h.get(6), h.get(7)) == (RETURNING, STOP, 0, 0)
    assert not h.op(14, session, 223)


@pytest.mark.parametrize("jobs,proven,profile", [(0, 0, 0), (31, 0, 1), (31, 1, 0)])
def test_thumb_unavailable_gesture_preserves_default_health(elf, jobs, proven, profile):
    h = AdapterThumb(elf)
    h.op(0, jobs, proven, profile)
    h.op(2, 1, 0, 0)
    assert not h.op(3, 1, 0)
    assert (h.get(0), h.get(1), h.get(2), h.get(9)) == (HEALTH, NONE, 0, 1)


def test_thumb_single_profile_copy_is_stable_across_start_and_reentry(integrated):
    h = integrated
    assert (h.get(30), h.get(31)) == (1, 2)
    session = adapter_start_pending(h)
    assert not h.op(24, 9, 10)
    assert (h.get(30), h.get(31)) == (1, 2)
    assert h.op(10, session, 1, 0, 1, 0, 0, 0, 0) == 2
    adapter_restore(h, 1)
    assert (h.get(30), h.get(31), h.get(22)) == (1, 2, 1)
    expected_session = h.get(2) + 1
    assert adapter_start_pending(h, 2) == expected_session > session


@pytest.mark.parametrize("now", [0, 0xFFFFFFE0])
def test_thumb_integrated_fresh_source_and_health_resume(integrated, now):
    h = integrated
    old_serial = h.op(17, 0)
    old_generation = h.get(26)
    assert old_serial and h.op(18, old_generation, old_serial, 0)
    assert h.op(3, 1, now)
    assert not h.op(5, h.get(2), h.get(5), 31, now)  # RUN has not finished.
    assert h.op(19, old_generation, old_serial, 0, 1, now)
    # Idempotent request does not renew/relabel the old Health work.
    session = adapter_start_pending(h, now)
    assert h.op(10, session, 1, now, 4, now + 60, now + 61, now + 61, 0) == 2
    assert (h.get(0), h.get(7), h.get(24)) == (GESTURE, 2, 32)
    for sequence in (1, 2):
        assert h.op(14, session, now + 61) == sequence
        assert not h.op(16, session, sequence, now + 61)
        assert h.op(15, session, sequence, 1, now + 61)
        assert h.op(16, session, sequence, now + 61)
    adapter_restore(h, now + 62)
    assert not h.op(20, old_generation, old_serial, 0, 1)
    new_serial = h.op(17, 0)
    assert new_serial > old_serial
    assert h.op(20, h.get(26), new_serial, 0, 1)
    assert not h.op(20, h.get(26), new_serial, 0, 0)


@pytest.mark.parametrize("fault", [1, 2, 4, 8, 16, 32, 64])
def test_thumb_integrated_bad_first_acquisition_never_enters_gesture(integrated, fault):
    h = integrated
    session = adapter_start_pending(h)
    assert h.op(10, session, 1, 0, 4, 60, 61, 61, fault) == 3
    assert (h.get(0), h.get(1), h.get(6), h.get(7), h.get(9)) == (RETURNING, STOP, 0, 0, 0)
    adapter_restore(h, 62)


def test_thumb_integrated_partial_entry_requires_fresh_cleanup_proof(integrated):
    h = integrated
    assert h.op(3, 1, 0)
    old_token, old_generation = h.get(2), h.get(5)
    adapter_restore(h, 1)
    newer = adapter_start_pending(h, 2)
    assert not h.op(7, old_token, old_generation, 0, 2)
    assert h.op(10, newer - 1, 1, 2, 1, 2, 2, 2, 127) == 0
    assert (h.get(0), h.get(1), h.get(6)) == (ENTERING, START, 1)
    h.op(4, 252)
    assert (h.get(0), h.get(1), h.get(6)) == (RETURNING, STOP, 0)


@pytest.mark.parametrize("failure", ["physical_run", "serial_exhaustion"])
def test_thumb_real_health_fault_is_reported_and_recovery_needs_receipts(integrated, failure):
    h = integrated
    if failure == "physical_run":
        serial = h.op(17, 0)
        generation = h.get(26)
        assert h.op(18, generation, serial, 0)
        assert not h.op(19, generation, serial, 0, 0, 1)
    else:
        h.op(23, 1)
    assert (h.get(0), h.get(1), h.get(9)) == (FAULT, NONE, 0)
    assert not h.op(3, 1, 1)
    adapter_restore(h, 2)


@pytest.mark.parametrize("cause", ["disconnect", "charging", "lease", "cancel", "send_failure"])
def test_exit_drops_pending_and_queued_samples(arm, cause):
    h = arm
    session = enter(h)
    assert offer(h, session, 1, count=3) == 0
    assert h.invoke("wr_next", session, h.OUTPUT, 0)
    now = 30000 if cause == "lease" else 1
    if cause == "disconnect": h.invoke("wr_link", 0, 0, now)
    elif cause == "charging": h.invoke("wr_link", 1, 1, now)
    elif cause == "lease": h.invoke("wr_tick", now)
    elif cause == "cancel": h.invoke("wr_request", 0, now)
    else: assert h.invoke("wr_sent", session, 1, 0, now)
    assert h.word(0) == RETURNING
    assert not h.invoke("wr_sent", session, 1, 1, now)
    assert not h.invoke("wr_next", session, h.OUTPUT, now)
    restore(h, now)
    newer = enter(h, now)
    assert newer > session
    assert offer(h, session, 2, verified=0, now=now) == 1
    assert not h.invoke("wr_sent", session, 1, 0, now)
    assert h.word(0) == GESTURE


@pytest.mark.parametrize("cause", ["overflow", "missing", "replay", "unverified"])
def test_acquisition_fault_returns_through_cleanup(arm, cause):
    session = enter(arm)
    assert offer(arm, session, 1, count=32 if cause == "overflow" else 1) == 0
    acquisition = {"missing": 3, "replay": 1}.get(cause, 2)
    assert offer(arm, session, acquisition, verified=int(cause != "unverified"), now=1) != 0
    assert arm.word(0) == RETURNING and arm.word(4) == STOP
    assert not arm.invoke("wr_next", session, arm.OUTPUT, 0)
    restore(arm)


@pytest.mark.parametrize("step", range(3))
@pytest.mark.parametrize("failure", ["timeout", "failed"])
def test_partial_entry_failure_never_streams(arm, step, failure):
    h = arm
    h.invoke("wr_link", 1, 0, 0)
    h.invoke("wr_request", 1, 0)
    for _ in range(step): h.invoke("wr_complete", h.word(12), 1, 0, 0)
    token = h.word(12)
    if failure == "timeout":
        assert not h.invoke("wr_complete", token, 1, 0, 3000)
    else:
        assert h.invoke("wr_complete", token, 0, 0, 0)
    assert h.word(0) == RETURNING
    assert offer(h, h.word(16), 1, now=3000 if failure == "timeout" else 0) == 1


@pytest.mark.parametrize("step", range(3))
def test_failed_cleanup_stays_fault_not_health(arm, step):
    session = enter(arm)
    assert offer(arm, session, 1) == 0
    arm.invoke("wr_request", 0, 1)
    for _ in range(step): arm.invoke("wr_complete", arm.word(12), 1, 0, 1)
    arm.invoke("wr_complete", arm.word(12), 0, 0, 1)
    assert arm.word(0) == FAULT
    assert not arm.invoke("wr_next", session, arm.OUTPUT, 2)
    assert not arm.invoke("wr_request", 1, 2)
    arm.invoke("wr_request", 0, 2)
    restore(arm, 2)


def test_acquisition_and_clock_rollover(arm):
    now = 0xFFFFFF80
    session = enter(arm, now, 0xFFFFFFFE)
    for acquisition, instant in [(0xFFFFFFFF, now), (0, 20), (1, 40)]:
        assert offer(arm, session, acquisition, now=instant) == 0
        assert arm.invoke("wr_next", session, arm.OUTPUT, instant)
        sequence = arm.output()[0]
        assert arm.invoke("wr_sent", session, sequence, 1, instant)
        assert arm.invoke("wr_renew", session, sequence, instant)
    arm.invoke("wr_tick", 30040)
    assert arm.word(0) == RETURNING


def test_token_and_sequence_exhaustion(arm):
    arm.write_word(12, 0xFFFFFFFF)
    arm.invoke("wr_link", 1, 0, 0)
    assert not arm.invoke("wr_request", 1, 0)
    assert arm.word(0) == FAULT
    arm.invoke("wr_init")
    session = enter(arm)
    tap_offset = arm.call("proof_tap_offset")
    sequence_offset = arm.call("proof_tap_sequence_offset")
    arm.write_word(tap_offset + sequence_offset, 0xFFFFFFFE)
    assert offer(arm, session, 1, count=2) == 4
    assert arm.word(0) == RETURNING


def test_emulator_does_not_supply_rom_or_hardware(arm):
    with pytest.raises(ValueError): arm.call("vendor_optical_start")
    with pytest.raises(ThumbProofError, match="instruction budget"):
        arm.call("wr_init", arm.CONTEXT, budget=1)
    with pytest.raises(ThumbProofError):
        arm.call("wr_init", 0x20BD98)  # actual stock RAM intentionally unmapped


def test_populated_batch_bounds_are_enforced(arm):
    session = enter(arm)
    arm.batch([(1, 2, 3)])
    with pytest.raises(ThumbProofError, match="read outside populated"):
        arm.invoke("wr_offer", session, 1, arm.BATCH, 2, 1, 0, 0)


def test_unused_emulator_ram_cannot_hide_a_bad_pointer(arm):
    with pytest.raises(ThumbProofError, match="read outside populated"):
        arm.call("wm_optics_allowed", arm.RAM + 0x4000)


@pytest.mark.parametrize("seed", range(8))
def test_randomized_linked_runtime_never_sends_outside_gesture(arm, seed):
    rng = random.Random(seed)
    h, now = arm, 0
    coverage = dict(offers=0, sends=0, renewals=0, stale=0, exits=0, entries=0)
    for cycle in range(12):
        session = enter(h, now)
        coverage["entries"] += 1
        for acquisition in range(1, rng.randrange(4, 12)):
            now += rng.randrange(1, 100)
            assert offer(h, session, acquisition, count=2, now=now) == 0
            coverage["offers"] += 1
            assert offer(h, session - 1, acquisition, now=now, verified=0) == 1
            assert not h.invoke("wr_complete", h.word(12) - 1, 1, 0, now)
            coverage["stale"] += 1
            for _ in range(2):
                assert h.invoke("wr_next", session, h.OUTPUT, now)
                sequence = h.output()[0]
                assert not h.invoke("wr_sent", session, sequence + 1, 0, now)
                assert h.invoke("wr_sent", session, sequence, 1, now)
                assert h.invoke("wr_renew", session, sequence, now)
                coverage["sends"] += 1
                coverage["renewals"] += 1
            assert h.word(0) == GESTURE and not h.invoke("wm_optics_allowed")
        # Every seed exercises each exit class, with randomized healthy traffic.
        cause = cycle % 4
        if cause == 0: h.invoke("wr_link", 0, 0, now)
        elif cause == 1: h.invoke("wr_link", 1, 1, now)
        elif cause == 2:
            now += 250
            h.invoke("wr_tick", now)
        else: h.invoke("wr_request", 0, now)
        assert h.word(0) == RETURNING
        assert not h.invoke("wr_next", session, h.OUTPUT, now)
        restore(h, now)
        coverage["exits"] += 1
    assert min(coverage.values()) >= 12  # active-path coverage cannot be vacuous


def test_old_backlog_cannot_renew_after_source_stalls(arm):
    session = enter(arm)
    assert offer(arm, session, 1, count=32) == 0
    assert arm.invoke("wr_next", session, arm.OUTPUT, 1)
    assert arm.invoke("wr_sent", session, 1, 1, 1)
    assert arm.invoke("wr_renew", session, 1, 1)
    assert not arm.invoke("wr_next", session, arm.OUTPUT, 5000)
    assert not arm.invoke("wr_renew", session, 2, 5000)
    assert arm.word(0) == RETURNING


@pytest.mark.parametrize("pending", [False, True])
def test_new_acquisitions_do_not_refresh_old_queued_or_pending_samples(arm, pending):
    session = enter(arm)
    assert offer(arm, session, 1) == 0
    if pending: assert arm.invoke("wr_next", session, arm.OUTPUT, 1)
    assert offer(arm, session, 2, now=200) == 0
    if pending:
        assert not arm.invoke("wr_sent", session, 1, 1, 250)
    else:
        assert not arm.invoke("wr_next", session, arm.OUTPUT, 250)
    assert arm.word(0) == RETURNING


@pytest.mark.parametrize("oldest", [0xFFFFFFFF, 0, 2])
def test_replayed_backdated_or_future_acquisition_time_is_rejected(arm, oldest):
    session = enter(arm)
    assert offer(arm, session, 1) == 0
    assert offer(arm, session, 2, now=1, oldest_at=oldest) == 2
    assert arm.word(0) == RETURNING
