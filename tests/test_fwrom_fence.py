"""Actual compiled barrier and captured ROM; explicitly mocked queue kernel."""
import struct

import pytest

from whip.fwrom_execution import ROMFenceHarness
from whip.fwthumb import ThumbProofError
from tests.test_fwstock_link import linked, STOCK, DESCRIPTOR  # noqa: F401
from tests.test_fwrom_execution import CAPTURE


def harness(linked):
    return ROMFenceHarness(linked, STOCK, DESCRIPTOR, CAPTURE)


@pytest.mark.parametrize("early", [False, True])
@pytest.mark.parametrize("result", [0, 1, 2, 255, 0xFFFFFFFF])
def test_compiled_fence_executes_captured_marshalling_and_callback_dispatch(linked, early, result):
    h = harness(linked)
    h.send_result, h.early = result, early
    assert bool(h.invoke("wf_request", 11)) == (result == 1)
    assert [address for address, _ in h.boundaries].count(0xEAB2) == 1
    assert bool(h.callbacks) == (result == 1 and early)
    if h.callbacks:
        # ROM delivered while C was still in enqueue; accepted was still false.
        assert h.callbacks == [(h.CONTEXT, 11, 0)]
    else:
        assert not h.invoke("wf_complete", 11)
    h.dispatch()
    assert bool(h.invoke("wf_complete", 11)) == (result == 1)
    assert not h.invoke("wf_complete", 11)
    assert not h.messages and h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0
    if result != 1:
        assert not h.invoke("wf_request", 12)
        assert not h.callbacks


def test_old_queued_callback_is_dispatched_but_does_not_acknowledge_new_ticket(linked):
    h = harness(linked)
    assert h.invoke("wf_request", 11)
    assert h.invoke("wf_abandon", 11)
    assert h.invoke("wf_request", 12)
    assert len(h.messages) == 2
    h.dispatch(limit=1)
    assert h.callbacks == [(h.CONTEXT, 11, 1)]
    assert h.word(4) == 0 and not h.invoke("wf_complete", 12)
    h.dispatch()
    assert h.callbacks[-1] == (h.CONTEXT, 12, 1)
    assert h.invoke("wf_complete", 12)
    assert not h.invoke("wf_request", 12)


def test_captured_dispatch_ignores_late_callback_after_abandon(linked):
    h = harness(linked)
    assert h.invoke("wf_request", 19)
    assert h.invoke("wf_abandon", 19)
    h.dispatch()
    assert h.callbacks == [(h.CONTEXT, 19, 0)]
    assert h.word(4) == 0 and not h.invoke("wf_complete", 19)


def test_null_queue_guard_avoids_captured_rom_assertion_and_is_permanent(linked):
    h = harness(linked)
    h.uc.mem_write(h.QUEUE_SLOT, bytes(4))
    assert not h.invoke("wf_request", 1)
    assert h.word(0) == 0 and bytes(h.uc.mem_read(h.CONTEXT + 10, 1)) == b"\x01"
    h.uc.mem_write(h.QUEUE_SLOT, struct.pack("<I", h.QUEUE))
    assert not h.invoke("wf_request", 2)
    assert not h.boundaries and not h.callbacks
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 0


@pytest.mark.parametrize("field,value", [(0, 3), (1, 0x40A95), (2, 0x200000)])
def test_unreviewed_command_callback_or_context_cannot_silently_execute(linked, field, value):
    h = harness(linked)
    assert h.invoke("wf_request", 5)
    packet = list(struct.unpack("<4I", h.messages.pop()))
    packet[field] = value  # Deliberately corrupted synthetic kernel message.
    h.messages.append(struct.pack("<4I", *packet))
    with pytest.raises(ThumbProofError): h.dispatch()


def test_rom_queue_word_is_not_a_general_ram_access_permission(linked):
    h = harness(linked)
    with pytest.raises(ThumbProofError, match="read outside"):
        h._read(h.uc, h.u.UC_MEM_READ, h.QUEUE_SLOT + 4, 4, 0, None)
    with pytest.raises(ThumbProofError, match="write outside"):
        h._write(h.uc, h.u.UC_MEM_WRITE, h.QUEUE_SLOT, 4, 0, None)
