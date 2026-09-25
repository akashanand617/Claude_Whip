"""OFF-RING counterexamples for an unsafe *proposed*, unimplemented binding.

The retained callbacks/connection reuse are explicit fixtures. Actual ARM
mailbox/owner/dispatcher code executes, but these tests do NOT claim the ring
stack actually replays callbacks or lacks a disconnect drain. They establish
why a current-ID lookup is not a substitute for that still-missing proof.
"""
import struct

import pytest

from tests.test_control_owner import (
    owner_build, OwnerThumb, BASE, INBOX, WD_IDLE, WD_CLOSED, WD_RECEIVING,
    WD_WAITING, HEALTH_MODE, ENTERING, QUIESCE,
)
from tests.test_unified_wire import frames, request
from whip.fwtransport import StockTransportHarness, DATA
from tests.test_fwstock_link import STOCK


def reopen_same_stack_id(h, generation=8):
    # The stack's short ID remains3 across the synthetic disconnect/reconnect.
    # No real callback fence is claimed: deliberately retain old packets in
    # the Python caller to challenge a proposed unsafe lookup at delivery.
    h.uc.mem_write(0x209E12, b'\x03')
    assert h.close_input(generation=7) and h.step(1)
    assert h.state() == WD_CLOSED and h.mode() == HEALTH_MODE
    assert h.function('wim_retire', INBOX, 7)
    assert h.function('wco_open', BASE, generation, 0, 2)
    assert h.state() == WD_IDLE
    assert bytes(h.uc.mem_read(0x209E12, 1)) == b'\x03'
    assert struct.unpack('<I', h.uc.mem_read(INBOX, 4))[0] == generation


@pytest.mark.parametrize('relabel', [False, True])
@pytest.mark.parametrize('request_id', [1, 0xFFFFFFFF])
def test_current_generation_lookup_can_authorize_old_gesture_request(owner_build, relabel, request_id):
    h = OwnerThumb(owner_build['elf'], profile=True)
    old = frames(1, request_id, request(3))  # Old opt-in, unchanged per-boot ID.
    reopen_same_stack_id(h)
    before = bytes(h.uc.mem_read(BASE, 880))
    # THIS is the invalid proposed binding, not production code: resolving
    # current generation at callback entry loses the event's original owner.
    generation = struct.unpack('<I', h.uc.mem_read(INBOX, 4))[0] if relabel else 7
    for packet in old:
        assert bool(h.post(packet, received=3, generation=generation)) == relabel
    if not relabel:
        assert bytes(h.uc.mem_read(BASE, 880)) == before
    assert h.step(3)
    if relabel:
        assert (h.state(), h.mode(), h.mode(4)) == (WD_WAITING, ENTERING, QUIESCE)
    else:
        assert (h.state(), h.mode()) == (WD_IDLE, HEALTH_MODE)
    # Even the unsafe fixture has NOT proved physical Gesture. It has begun
    # unauthorized software entry; no STOP, source or hardware receipt follows.
    assert not h.transfers and not h.timer_calls and not h.clock_reads


@pytest.mark.parametrize('preserve_arrival', [False, True])
def test_recapturing_callback_time_also_hides_upstream_delay(owner_build, preserve_arrival):
    h = OwnerThumb(owner_build['elf'], profile=True)
    old = frames(1, 42, request(3))
    reopen_same_stack_id(h)
    # Both cases deliberately use the wrong generation. Original timing can
    # catch this long delay, but cannot fix the3ms case above. A callback-entry
    # clock cannot retroactively measure when the upstream work was scheduled.
    for packet in old:
        assert h.post(packet, received=0 if preserve_arrival else 9000, generation=8)
    assert h.step(9000)
    assert h.state() == (WD_CLOSED if preserve_arrival else WD_WAITING)
    assert h.mode() == (HEALTH_MODE if preserve_arrival else ENTERING)
    assert not h.transfers and not h.timer_calls


def test_first_fragment_only_never_enters_gesture_even_after_mislabel(owner_build):
    h = OwnerThumb(owner_build['elf'], profile=True)
    old = frames(1, 1, request(3))
    reopen_same_stack_id(h)
    assert h.post(old[0], received=3, generation=8) and h.step(3)
    assert (h.state(), h.mode()) == (WD_RECEIVING, HEALTH_MODE)
    # The complete old frame pair is the counterexample; no early-fragment
    # publication or weakened existing assembler check is needed to produce it.
    assert h.post(old[1], received=4, generation=8) and h.step(4)
    assert (h.state(), h.mode()) == (WD_WAITING, ENTERING)


@pytest.mark.parametrize('write_type', [0, 1, 2, 3, 0x100, 0xDEADBEEF])
def test_stock_write_does_not_establish_seventh_argument_contract(write_type):
    h = StockTransportHarness(STOCK)
    h.uc.mem_write(DATA, bytes(range(20)))
    output = DATA + 128
    h.uc.mem_write(output, b'\xa5' * 4)
    reads = []

    def capture(uc, access, address, size, value, opaque):
        if h.STACK <= address < h.STACK + 12:
            reads.append((address - h.STACK, size))

    h.uc.hook_add(h.u.UC_HOOK_MEM_READ, capture)
    assert h.call(0x7ACE, 3, 4, 2, write_type, 20, DATA, output) == 0
    assert h.legacy_receives == [(DATA, 20, bytes(range(20)))]
    assert set(reads) == {(0, 4), (4, 4)}
    assert bytes(h.uc.mem_read(output, 4)) == b'\xa5' * 4
    # Compatible SDK declares stack+8 as a post-write function OUTPUT pointer,
    # not context. Stock does not load it; this proves neither the installed
    # stack's seventh-argument validity nor permission to clear/dereference it.
