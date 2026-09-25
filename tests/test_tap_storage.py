"""Actual ARM FIFO storage compaction versus retained pre-change C and a deque.

Same 32-entry capacity, output ABI and failure behavior. This does not provide
physical samples, safe ring RAM ownership, stock hooks or timing qualification.
"""
from collections import deque
import random
import struct

import pytest

from tests.test_unified_thumb import elf  # noqa: F401
from whip.fwthumb import RuntimeThumb

U32 = 0xFFFFFFFF


class CurrentTap(RuntimeThumb):
    CONTEXT_SIZE_SYMBOL = "proof_tap_size"


class ReferenceTap(RuntimeThumb):
    CONTEXT_SIZE_SYMBOL = "proof_old_tap_size"


class Pair:
    def __init__(self, binary):
        self.new, self.old = CurrentTap(binary), ReferenceTap(binary)
        assert (self.new.context_size, self.old.context_size) == (212, 404)
        self.meta = (self.new.call("proof_tap_sequence_offset") - 8,
                     self.old.call("proof_old_tap_sequence_offset") - 8)
        assert self.meta == (192, 384)
        self.invoke("init")

    def states(self):
        return tuple(struct.unpack("<IIIBBBxI", bytes(h.uc.mem_read(h.CONTEXT + off, 20)))
                     for h, off in zip((self.new, self.old), self.meta, strict=True))

    def invoke(self, operation, *args):
        results = (self.new.invoke("wt_" + operation, *args),
                   self.old.invoke("proof_old_tap_" + operation, *args))
        if operation not in ("init", "stop"):
            assert results[0] == results[1], (operation, args, results)
        states = self.states()
        assert states[0] == states[1], (operation, args, states)
        return results[0]

    def offer(self, session, acquisition, values, *, count=None, verified=True, null=False):
        for h in (self.new, self.old):
            h.batch(values)
        return self.invoke("offer", session, acquisition, 0 if null else self.new.BATCH,
                           len(values) if count is None else count, int(verified))

    def take(self, session, *, null=False):
        for h in (self.new, self.old):
            h.uc.mem_write(h.OUTPUT, b"\xa5" * 12)
        result = self.invoke("take", session, 0 if null else self.new.OUTPUT)
        if result:
            assert self.new.output() == self.old.output()
            return self.new.output()
        for h in (self.new, self.old):
            assert bytes(h.uc.mem_read(h.OUTPUT, 12)) == b"\xa5" * 12
        return None


def axes(start, count):
    return [((start + i) % 65536 - 32768, 32767 - (i % 65536), -8005)
            for i in range(count)]


@pytest.mark.parametrize("head", range(32))
def test_every_ring_index_preserves_backlog_when_new_batches_wrap(elf, head):
    p = Pair(elf)
    assert p.invoke("start", 1, 0)
    acquisition = 0
    if head:
        prefix = axes(0, head)
        assert p.offer(1, 1, prefix) == 0
        acquisition = 1
        for sequence, value in enumerate(prefix, 1):
            assert p.take(1) == (sequence, value)
    first, second = axes(100, 31), axes(1000, 16)
    assert p.offer(1, acquisition + 1, first) == 0
    expected = deque(enumerate(first, head + 1))
    for _ in range(15): assert p.take(1) == expected.popleft()
    assert p.offer(1, acquisition + 2, second) == 0
    expected.extend(enumerate(second, head + 32))
    assert p.states()[0][4] == len(expected) == 32  # Capacity has not shrunk.
    while expected: assert p.take(1) == expected.popleft()
    assert p.take(1) is None


@pytest.mark.parametrize("remaining", [1, 2, 16, 31, 32])
def test_sequence_maximum_is_delivered_exactly_and_never_wraps(elf, remaining):
    p = Pair(elf)
    assert p.invoke("start", 1, 0)
    for h, off in zip((p.new, p.old), p.meta, strict=True):
        h.write_word(off + 8, U32 - remaining)  # Empty queue, valid boundary fixture.
    values = axes(123, remaining)
    assert p.offer(1, 1, values) == 0
    for sequence, value in enumerate(values, U32 - remaining + 1):
        assert p.take(1) == (sequence, value)
    assert p.offer(1, 2, [(1, 2, 3)]) == 4
    assert p.take(1) is None
    assert not p.invoke("start", 1, 0)
    assert p.invoke("start", 2, 0)
    assert p.offer(2, 1, [(4, 5, 6)]) == 0
    assert p.take(2) == (1, (4, 5, 6))


def test_exhaustion_with_pending_entries_discards_all_without_exposing_a_partial_batch(elf):
    p = Pair(elf)
    assert p.invoke("start", 1, U32 - 1)
    for h, off in zip((p.new, p.old), p.meta, strict=True): h.write_word(off + 8, U32 - 3)
    assert p.offer(1, U32, axes(10, 2)) == 0
    assert p.take(1) == (U32 - 2, axes(10, 1)[0])
    assert p.offer(1, 0, axes(20, 2)) == 4
    assert p.take(1) is None
    assert p.states()[0][4:] == (0, 0, 4)


@pytest.mark.parametrize("fault", ["overflow", "zero", "too_many", "null", "unverified", "replay", "missing"])
def test_bad_batch_preserves_failure_and_discards_backlog(elf, fault):
    p = Pair(elf)
    assert p.invoke("start", 1, 0)
    assert p.offer(1, 1, axes(10, 31)) == 0
    count = {"zero": 0, "too_many": 33}.get(fault, 2)
    acquisition = {"replay": 1, "missing": 3}.get(fault, 2)
    assert p.offer(1, acquisition, axes(20, 2), count=count, null=fault == "null",
                   verified=fault != "unverified") == (3 if fault == "overflow" else 2)
    assert p.take(1) is None
    assert not p.invoke("start", 1, 0)


@pytest.mark.parametrize("seed", range(12))
def test_interleaved_arm_traces_match_old_implementation_and_independent_fifo(elf, seed):
    rng = random.Random(seed)
    p = Pair(elf)
    session, acquisition, sequence = 1, U32 - 2, 0
    expected = deque()
    assert p.invoke("start", session, acquisition)
    for step in range(160):
        operation = rng.randrange(10)
        if operation < 5 and len(expected) < 32:
            count = rng.randint(1, 32 - len(expected))
            values = axes(seed * 5000 + step * 32, count)
            acquisition = (acquisition + 1) & U32
            assert p.offer(session, acquisition, values) == 0
            expected.extend(enumerate(values, sequence + 1))
            sequence += count
        elif operation < 8:
            assert p.take(session) == (expected.popleft() if expected else None)
        elif operation == 8:
            p.invoke("stop", session - 1)
            assert p.take(session - 1) is None
            assert p.offer(session - 1, acquisition, [(0, 0, 0)], verified=False) == 1
            assert p.take(session, null=True) is None
            assert not p.invoke("start", session, 0)
        else:
            p.invoke("stop", session)
            assert p.take(session) is None
            expected.clear()
            session += 1
            acquisition, sequence = U32 - 2, 0
            assert p.invoke("start", session, acquisition)
        state = p.states()[0]
        assert state[:3] == (session, acquisition, sequence)
        assert state[4:] == (len(expected), 1, 0)
    while expected: assert p.take(session) == expected.popleft()
