"""Combined selected startup paths in ONE persistent ARM context, OFF-RING.

This composes the real slot adapter/gate, original service setup, advertisement
builder and resubmission. Skipped boot/configuration, source MAC, callback bodies,
ROM and ID lifetime remain explicit fixtures. The two call orders are test
orders, not an assertion of the physical boot sequence or all-root closure.
"""
import struct

import pytest

from tests.test_stock_event_gate import gate_build, slot_build, GateHarness
from tests.test_stock_service_slot import OLD_SLOT, EVENT
from tests.test_wechat_advertising import AdvertisingHarness, AD, OTHER_AD, ad_elements
from whip.fwcontinuity import BIAS
from whip.fwwechat_advertising import advertising_plan


class StartupHarness(GateHarness):
    def __init__(self, build, result, assigned, gap_status):
        super().__init__(build)
        self.mac, self.status = bytes.fromhex("30324133cc07"), gap_status
        self.gap_calls, self.boundaries = [], []
        expected = bytearray(self.uc.mem_read(BIAS, len(self.image)))
        for edit in advertising_plan(self.image):
            assert expected[edit.file_offset:edit.file_offset + 2] == edit.before
            self.uc.mem_write(BIAS + edit.file_offset, edit.after)
            expected[edit.file_offset:edit.file_offset + 2] = edit.after
        allowed = {o + i for o in (0x76DE, 0x7788, 0x77AC) for i in range(4)}
        allowed |= {e.file_offset + i for e in advertising_plan(self.image) for i in range(2)}
        assert len(allowed) == 38
        assert bytes(self.uc.mem_read(BIAS, len(self.image))) == expected
        assert {i for i, (a, b) in enumerate(zip(self.image, expected)) if a != b} <= allowed
        self.uc.mem_write(AD, b"\xc7" * 31)
        self.uc.mem_write(OTHER_AD, bytes(range(31)))
        self.registration_results.extend([(1, 0), (1, 1), (1, 2), (result, assigned), (1, 4)])

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        # Reuse only the advertising harness's explicit handled branches; its
        # base fallback is NOT used. Other instructions stay gate/slot reviewed.
        ranges = ((0x72C4, 0x72C8), (0x7498, 0x74F2), (0x74F4, 0x74F8),
                  (0x75FA, 0x7606), (0x7666, 0x766A), (0x15B30, 0x15B4C))
        if (offset in (0x72C8, 0x74F8, 0x7606) or
                any(lo <= offset and offset + size <= hi for lo, hi in ranges) or
                (address == 0x4926 and uc.reg_read(self.registers[0]) == 0x3300)):
            return AdvertisingHarness._code(self, uc, address, size, opaque)
        return super()._code(uc, address, size, opaque)

    def advertisement(self, entry):
        before = bytes(self.uc.mem_read(0x200000, 0x30000))
        self.call(entry)
        after = bytes(self.uc.mem_read(0x200000, 0x30000))
        assert all(a == b or AD <= 0x200000 + i < AD + 12 or
                   self.STACK - 1024 <= 0x200000 + i < self.STACK + 32
                   for i, (a, b) in enumerate(zip(before, after)))
        assert self.uc.mem_read(OTHER_AD, 31) == bytes(range(31))


@pytest.mark.parametrize("advertise_first", [False, True])
@pytest.mark.parametrize("result,assigned,gap_status", [(1, 3, 0), (0, 3, 1), (1, 255, 255)])
def test_selected_startup_paths_preserve_ids_callbacks_and_packed_advertisement(
        gate_build, advertise_first, result, assigned, gap_status):
    h = StartupHarness(gate_build, result, assigned, gap_status)
    if advertise_first:
        h.advertisement(0x72C4)
    h.call(0x76B8)
    assert len(h.registrations) == 5 and h.stack_calls[0][0] == 0x3100
    expected_id = assigned if result == 1 and assigned != 255 else 255
    assert h.separate_id() == expected_id
    assert h.uc.mem_read(OLD_SLOT, 1) == b"\xff"
    saved_ids = bytes(h.uc.mem_read(0x209E1B, 5))
    pointers = {p: bytes(h.uc.mem_read(p, 4)) for p in (0x209E40, 0x209E44, 0x20CC48)}
    assert saved_ids == b"\0\1\2\xff\4"
    assert all(struct.unpack("<I", raw)[0] == h.gate for raw in pointers.values())
    if not advertise_first:
        h.advertisement(0x72C4)
    h.advertisement(0x74F4)
    assert h.uc.mem_read(0x209E1B, 5) == saved_ids
    assert all(h.uc.mem_read(p, 4) == raw for p, raw in pointers.items())
    assert h.separate_id() == expected_id
    assert h.gap_calls[0] == h.gap_calls[1]
    assert h.gap_calls[0][:3] == (0x262, 12, AD)
    assert ad_elements(h.gap_calls[0][3]) == [bytes.fromhex("ff3412fee7") + h.mac[::-1]]
    assert h.uc.mem_read(AD + 12, 19) == b"\xc7" * 19
    h.selectors(3, 4)
    if expected_id != 255:
        assert h.through(h.gate, expected_id, 0xDEADBEEF) == 0
        assert not h.old_entries
    # A preserved service uses its ACTUAL stored callback after both paths.
    assert h.through(struct.unpack("<I", pointers[0x209E44])[0], 0, EVENT) == 0
    assert h.old_entries[-1] == (0, EVENT)
    assert not h.sends and not h.messages and not h.legacy_receives
