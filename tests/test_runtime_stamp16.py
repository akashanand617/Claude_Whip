"""Generated low16 runtime versus pinned full32 ARM; no accepted source edits.

The 7968-ms bound relies on initialized state, exclusive runtime ownership of
the unchanged 32-entry tap, fresh monotonic time and existing cleanup. Inputs
and completion receipts here are synthetic; this is no physical source proof.
Only live queued timestamps and an awaiting-send timestamp are observable.
Old timestamps in unused slots/empty pending scratch are deliberately ignored.
"""
from collections import Counter
from io import BytesIO
import os
from pathlib import Path
import random
import shutil
import sys

from elftools.elf.elffile import ELFFile
import pytest

from probe.runtime_stamp_budget import build, candidate_sources, replace_once
from tests.test_fwstock_link import STOCK, DESCRIPTOR
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf
from whip.fwthumb import RuntimeThumb

ROOT = Path(__file__).resolve().parents[1]
U32 = 0xFFFFFFFF
HEALTH, ENTERING, GESTURE, RETURNING, FAULT = range(5)
NONE, QUIESCE, HOLD, START, STOP, RELEASE, RESUME = range(7)
BOUND = 32 * 249
STARTS = (0, 0xFFF0, 0xFFFFFFF0)


@pytest.fixture(scope="module")
def stamp_build(tmp_path_factory):
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    assert zig, "pinned Zig required, never skip"
    modules = {str(Path(__file__).relative_to(ROOT)): Path(__file__)}
    for module in tuple(sys.modules.values()):
        path = Path(getattr(module, "__file__", "") or "/").absolute()
        if path.suffix == ".py" and path.is_relative_to(ROOT):
            modules[str(path.relative_to(ROOT))] = path
    execution_inputs = InputSnapshot(modules)
    directory = tmp_path_factory.mktemp("runtime-stamp16") / "evidence"
    report = build(directory, zig)
    execution_inputs.verify()
    inputs = InputSnapshot({n: ROOT / n for n in report["inputs_sha256"]})
    tools = InputSnapshot({"clang": Path(shutil.which("clang")),
                           "zig": Path(shutil.which(zig)), "python": Path(sys.executable)})
    artifacts = InputSnapshot({n: directory / n for n in report["artifacts_sha256"]})
    manifest = InputSnapshot({"budget-report.json": directory / "budget-report.json"})
    assert inputs.hashes == report["inputs_sha256"]
    assert tools.hashes == report["tools_sha256"]
    assert artifacts.hashes == report["artifacts_sha256"]
    binaries = {}
    for label in ("reference", "candidate", "mutant"):
        path = Path(report[label + "_elf"])
        assert path.is_relative_to(directory)
        assert str(path.relative_to(directory)) in artifacts.hashes
        binaries[label] = path.read_bytes()
    yield {**binaries, "report": report, "directory": directory}
    for snapshot in (execution_inputs, inputs, tools, artifacts, manifest):
        snapshot.verify()


class StampThumb(RuntimeThumb):
    def __init__(self, raw):
        super().__init__(raw)
        self.layout = tuple(self.call("proof_layout", i) for i in range(18))
        assert self.layout[0] == self.context_size
        assert self.layout[9] == self.call("proof_tap_offset") == 36
        assert (self.layout[11], self.layout[12], self.layout[13], self.layout[14]) == (212, 192, 204, 208)
        assert self.layout[10] in (1, 2, 4)
        self.invoke("wr_init")

    def byte(self, offset):
        return bytes(self.uc.mem_read(self.CONTEXT + offset, 1))[0]

    def raw(self, offset, count):
        return bytes(self.uc.mem_read(self.CONTEXT + offset, count))

    def raw_output(self):
        return bytes(self.uc.mem_read(self.OUTPUT, 12))

    def tap(self):
        start = self.layout[9]
        return (self.word(start + self.layout[12]), self.word(start + self.layout[12] + 4),
                self.word(start + self.layout[12] + 8), self.byte(start + self.layout[13]),
                self.byte(start + self.layout[13] + 1), self.byte(start + self.layout[13] + 2),
                self.word(start + self.layout[14]))

    def normalized(self):
        layout = self.layout
        _, _, _, head, count, active, _ = self.tap()
        width, anchor = layout[10], self.word(layout[3])
        mask = (1 << (8 * width)) - 1
        stamps = []
        if active:
            for i in range(count):
                index = (head + i) % 32
                low = int.from_bytes(self.raw(layout[1] + index * width, width), "little")
                # Use the latest source, not an arbitrary later idle caller,
                # to normalize stored queue identity before wr_next's tick.
                stamp = low if width == 4 else (anchor - ((anchor - low) & mask)) & U32
                stamps.append(stamp)
        awaiting = self.byte(layout[6])
        return {
            "mode": self.raw(0, 36), "tap": self.raw(layout[9], layout[11]),
            "last_sent": self.word(layout[5]), "awaiting_send": awaiting,
            "have_sent": self.byte(layout[7]), "have_source": self.byte(layout[4]),
            "last_source_at": anchor, "queued_at": tuple(stamps),
            "pending": (self.raw(layout[8], 12), self.word(layout[2])) if awaiting else None,
        }


class Pair:
    def __init__(self, evidence, candidate="candidate"):
        self.old, self.new = (StampThumb(evidence[n]) for n in ("reference", candidate))
        assert self.old.context_size == 408
        self.check()

    def check(self):
        left, right = self.old.normalized(), self.new.normalized()
        assert left == right, (left, right)

    def invoke(self, operation, *args):
        results = tuple(h.invoke("wr_" + operation, *(n & U32 for n in args))
                        for h in (self.old, self.new))
        if operation not in ("init", "link", "tick"):
            assert results[0] == results[1], (operation, args, results)
        self.check()
        return results[0]

    def enter(self, now=0, baseline=0):
        self.invoke("link", 1, 0, now)
        assert self.invoke("request", 1, now)
        for action in (QUIESCE, HOLD, START):
            assert self.old.word(4) == action
            assert self.invoke("complete", self.old.word(12), 1, baseline, now)
        assert self.old.word(0) == GESTURE
        return self.old.word(16)

    def restore(self, now):
        # The explicit fresh Health request also handles an expired prior
        # RETURNING phase; never manufacture a current completion after idle.
        assert self.invoke("request", 0, now)
        for action in (STOP, RELEASE, RESUME):
            assert (self.old.word(0), self.old.word(4)) == (RETURNING, action)
            assert self.invoke("complete", self.old.word(12), 1, 0, now)
        assert self.old.word(0) == HEALTH

    def offer(self, session, acquisition, now, *, oldest=None, count=1, verified=True, null=False):
        values = [((acquisition + i) % 65536 - 32768, -8005, 32767) for i in range(min(max(count, 1), 32))]
        for h in (self.old, self.new):
            h.batch(values)
        return self.invoke("offer", session, acquisition, 0 if null else self.old.BATCH,
                           count, int(verified), now if oldest is None else oldest, now)

    def next(self, session, now, null=False):
        for h in (self.old, self.new):
            h.uc.mem_write(h.OUTPUT, b"\xa5" * 12)
        accepted = self.invoke("next", session, 0 if null else self.old.OUTPUT, now)
        assert self.old.raw_output() == self.new.raw_output()
        if not accepted:
            assert self.old.raw_output() == b"\xa5" * 12
        return self.old.output() if accepted else None


def test_generated_build_preserves_whole_inventory_and_refuses_production(stamp_build):
    r = stamp_build["report"]
    assert (r["object_count"], r["function_count"], r["constant_count"]) == (25, 146, 3)
    assert r["persistent_ram_saving_bytes"] == 64 and r["persistent_planning_bytes"] == 1180
    assert r["unchanged_queue_capacity"] == 32 and r["live_head_maximum_age_ms"] == BOUND
    assert r["strict_missing_binding_refusal"] and r["append_lower_bound_over_bytes"] > 0
    assert not any(r[n] for n in ("original_core_changed", "hardware_access", "flashable",
                                  "whole_code_fit_proven", "ram_ownership_proven"))
    layouts = [StampThumb(stamp_build[n]).layout for n in ("reference", "candidate", "mutant")]
    assert [v[0] for v in layouts] == [408, 344, 312]
    assert [v[10] for v in layouts] == [4, 2, 1]
    assert [v[15] for v in layouts] == [880, 816, 784]
    # Narrow array alignment reuses two padding bytes before the queue; later
    # full32 fields realign, so the total retained saving is64, not66.
    assert [v[1] for v in layouts] == [268, 266, 266]
    for i in (5, 6, 7, 8, 9, 11, 12, 13, 14):
        assert len({v[i] for v in layouts}) == 1
    for i in (2, 3, 4, 16, 17):
        assert layouts[0][i] - layouts[1][i] == 64
    exports = []
    for label in ("reference", "candidate", "mutant"):
        raw = stamp_build[label]
        with pytest.raises(ValueError):
            inspect_elf(raw, STOCK, DESCRIPTOR)
        exports.append(Counter(s.name for s in ELFFile(BytesIO(raw)).get_section_by_name(".symtab").iter_symbols()
                               if s["st_info"]["type"] == "STT_FUNC" and s["st_info"]["bind"] == "STB_GLOBAL"))
    assert exports[0] == exports[1] == exports[2]


def test_all_bounded_ages_reconstruct_losslessly_at_both_wraps():
    assert BOUND == 7968 < 65536
    for now in (0, 1, 0xFFFF, 0x10000, 0xFFFFFFFF):
        for age in range(BOUND + 1):
            original = (now - age) & U32
            assert (now - (original & 0xFFFF)) & 0xFFFF == age
            assert (now - ((now - (original & 0xFFFF)) & 0xFFFF)) & U32 == original


@pytest.mark.parametrize("start", STARTS)
def test_full32_capacity_and_249_250_boundaries_across_clock_wrap(stamp_build, start):
    for age in (0, 249, 250, 255, 256, 498, 499, 65535, 65536):
        p = Pair(stamp_build)
        session = p.enter(start)
        assert p.offer(session, 1, start) == 0
        if age >= 250:
            assert p.offer(session, 2, (start + 249) & U32) == 0
        sample = p.next(session, (start + age) & U32)
        assert bool(sample) == (age < 250)
        if age >= 250:
            assert p.old.word(0) == RETURNING and not p.old.tap()[5]


@pytest.mark.parametrize("start", STARTS)
def test_maximal_live_backlog_7968_age_is_not_modular_alias(stamp_build, start):
    p = Pair(stamp_build)
    session = p.enter(start)
    for i in range(32):
        assert p.offer(session, i + 1, (start + 249 * i) & U32) == 0
        assert p.old.tap()[4] == i + 1
        assert p.old.normalized()["queued_at"][0] == start
    assert not p.next(session, (start + BOUND) & U32)
    assert (p.old.word(0), p.old.word(4)) == (RETURNING, STOP)


def test_every_physical_queue_head_retains_full_capacity_and_order(stamp_build):
    for head in range(32):
        p = Pair(stamp_build)
        session = p.enter(0xFFF0)
        acquisition = 0
        if head:
            assert p.offer(session, 1, 0xFFF0, count=head) == 0
            acquisition = 1
            for sequence in range(1, head + 1):
                assert p.next(session, 0xFFF1)[0] == sequence
                assert p.invoke("sent", session, sequence, 1, 0xFFF1)
        assert p.old.tap()[3:5] == (head, 0)
        assert p.offer(session, acquisition + 1, 0xFFF2, count=32) == 0
        assert p.old.tap()[4] == 32
        for sequence in range(head + 1, head + 33):
            assert p.next(session, 0x10001)[0] == sequence
            assert p.invoke("sent", session, sequence, 1, 0x10001)
        assert not p.next(session, 0x10001)


@pytest.mark.parametrize("start", STARTS)
def test_pending_retains_full_timestamp_while_fresh_source_advances(stamp_build, start):
    p = Pair(stamp_build)
    session = p.enter(start)
    assert p.offer(session, 1, start) == 0
    assert p.next(session, start)[0] == 1
    assert p.offer(session, 2, (start + 249) & U32) == 0
    assert p.old.word(p.old.layout[2]) == p.new.word(p.new.layout[2]) == start
    assert not p.invoke("sent", session, 1, 1, (start + 256) & U32)
    assert p.old.word(0) == RETURNING


@pytest.mark.parametrize("fault", ["overflow", "zero", "large", "null", "unverified", "replay", "missing"])
def test_bad_acquisition_preserves_cleanup_and_drops_whole_backlog(stamp_build, fault):
    p = Pair(stamp_build)
    session = p.enter()
    assert p.offer(session, 1, 0, count=31) == 0
    count = {"zero": 0, "large": 33}.get(fault, 2)
    acquisition = {"replay": 1, "missing": 3}.get(fault, 2)
    assert p.offer(session, acquisition, 1, count=count, null=fault == "null",
                   verified=fault != "unverified") == (3 if fault == "overflow" else 2)
    assert p.old.word(0) == RETURNING and p.old.tap()[4:6] == (0, 0)
    assert not p.next(session, 1)


@pytest.mark.parametrize("phase", ["entering", "gesture", "returning"])
def test_idle_action_and_stream_cleanup_precedes_old_stamp_access(stamp_build, phase):
    for start in (0, 0xFFFFFF00):
        p = Pair(stamp_build)
        if phase == "entering":
            p.invoke("link", 1, 0, start)
            assert p.invoke("request", 1, start)
        else:
            session = p.enter(start)
            assert p.offer(session, 1, start, count=32) == 0
            if phase == "returning":
                assert p.invoke("request", 0, start)
        old_token = p.old.word(12)
        p.invoke("tick", (start + 65536) & U32)
        assert p.old.word(0) == (FAULT if phase == "returning" else RETURNING)
        assert not p.old.tap()[4] and not p.old.tap()[5]
        assert not p.invoke("complete", old_token, 1, 0, (start + 65536) & U32)


@pytest.mark.parametrize("charging", [False, True])
def test_link_cleanup_and_stale_send_never_restore_old_queue(stamp_build, charging):
    p = Pair(stamp_build)
    session = p.enter(10)
    assert p.offer(session, 1, 10, count=32) == 0
    assert p.next(session, 10)[0] == 1
    p.invoke("link", int(charging), int(charging), 11)
    assert p.old.word(0) == RETURNING and p.old.tap()[4] == 0
    assert not p.invoke("sent", session, 1, 1, 11)
    p.restore(11)
    new_session = p.enter(12)
    assert new_session > session
    assert p.offer(session, 2, 12) == 1
    assert not p.next(session, 12)
    assert p.offer(new_session, 1, 12) == 0
    assert p.next(new_session, 12)[0] == 1


def test_empty_pending_scratch_is_not_a_live_timestamp(stamp_build):
    p = Pair(stamp_build)
    session = p.enter(65536)
    assert not p.next(session, 65536)
    # Existing full32 fallback writes stale unused-slot zero. Low16 rebuilds a
    # different empty scratch value; neither is observable while awaiting=false.
    assert p.old.word(p.old.layout[2]) == 0
    assert p.new.word(p.new.layout[2]) == 65536
    assert not p.invoke("sent", session, 1, 1, 65536)
    assert p.offer(session, 1, 65536) == 0
    assert p.next(session, 65536)[0] == 1
    assert p.old.word(p.old.layout[2]) == p.new.word(p.new.layout[2]) == 65536


def test_counter_wrap_and_sequence_exhaustion_keep_original_failure(stamp_build):
    p = Pair(stamp_build)
    session = p.enter(baseline=U32 - 1)
    assert p.offer(session, U32, 0) == 0
    assert p.next(session, 0)[0] == 1
    assert p.invoke("sent", session, 1, 1, 0)
    assert p.offer(session, 0, 1) == 0
    assert p.next(session, 1)[0] == 2
    assert p.invoke("sent", session, 2, 1, 1)
    for h in (p.old, p.new):
        h.write_word(h.layout[9] + h.layout[12] + 8, U32 - 1)  # valid empty-queue boundary fixture
    assert p.offer(session, 1, 2) == 0
    assert p.next(session, 2)[0] == U32
    assert p.invoke("sent", session, U32, 1, 2)
    assert p.offer(session, 2, 3) == 4
    assert p.old.word(0) == RETURNING


@pytest.mark.parametrize("seed", range(8))
def test_seeded_persistent_runtime_traces_match_all_live_state(stamp_build, seed):
    rng = random.Random(0x51A60000 + seed)
    p = Pair(stamp_build)
    now = U32 - 300 if seed & 1 else 65000
    p.enter(now)
    for _ in range(180):
        now = (now + rng.choice((0, 1, 5, 40, 249, 250, 65536))) & U32
        state, session = p.old.word(0), p.old.word(16)
        if state in (RETURNING, FAULT):
            p.restore(now)
            p.enter(now)
            continue
        operation = rng.randrange(9)
        _, acquisition, sequence, _, count, _, _ = p.old.tap()
        if operation < 3:
            p.offer(session, (acquisition + 1) & U32, now, count=rng.randint(1, min(8, 33 - count)))
        elif operation == 3:
            p.next(session, now)
        elif operation == 4:
            pending = p.old.word(p.old.layout[8])
            p.invoke("sent", session, pending + (rng.randrange(5) == 0), int(rng.randrange(8) != 0), now)
        elif operation == 5:
            last = p.old.word(p.old.layout[5])
            p.invoke("renew", session, last + rng.randrange(2), now)
        elif operation == 6:
            p.invoke("tick", now)
        elif operation == 7:
            p.offer((session - 1) & U32, acquisition, now, verified=False)
            assert not p.next((session - 1) & U32, now)
        else:
            p.invoke("request", int(rng.randrange(4) != 0), now)


def test_naive_low8_mutant_actually_delivers_expired_head(stamp_build):
    p = Pair(stamp_build, candidate="mutant")
    session = p.enter()
    assert p.offer(session, 1, 0) == 0
    assert p.offer(session, 2, 249) == 0  # last source is fresh, oldest head is not
    with pytest.raises(AssertionError, match="next"):
        p.next(session, 256)
    assert p.old.word(0) == RETURNING
    assert p.new.word(0) == GESTURE and p.new.output()[0] == 1
    assert p.new.word(p.new.layout[2]) == 256  # stale t=0 was falsely relabeled


@pytest.mark.parametrize("bits", [0, 32])
def test_generator_refuses_unreviewed_stamp_width(bits):
    with pytest.raises(ValueError, match="only reviewed16"):
        candidate_sources(bits)


@pytest.mark.parametrize("source", ["missing", "anchor anchor"])
def test_generator_refuses_missing_or_repeated_source_anchor(source):
    with pytest.raises(ValueError, match="anchor changed"):
        replace_once(source, "anchor", "replacement")
