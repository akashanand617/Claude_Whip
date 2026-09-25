"""Actual ARM FEE7 payload slices, OFF-RING; no installable image.

Execute original prologues/epilogues, builder, resubmission and GAP wrapper.
Skipped boot/name/configuration paths, source MAC and ROM are explicit fixtures.
Neither these slices nor whole-RAM write checks qualify physical advertising.
"""
from pathlib import Path
import struct

import pytest

from whip.fwcontinuity import BIAS, ProofError
from whip.fwtransport import StockTransportHarness
from whip.fwwechat_advertising import advertising_plan, advertising_report

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT / "firmware/rt02cr-stock-3.12.02.bin"
AD = 0x209E21
OTHER_AD = 0x208523


class AdvertisingHarness(StockTransportHarness):
    def __init__(self, stock, *, patched, mac, status, omitted=()):
        super().__init__(stock)
        self.mac, self.status = mac, status
        self.gap_calls, self.boundaries = [], []
        expected = bytearray(stock)
        if patched:
            for edit in advertising_plan(stock):
                if edit.file_offset in omitted:
                    continue
                self.uc.mem_write(BIAS + edit.file_offset, edit.after)
                expected[edit.file_offset:edit.file_offset + 2] = edit.after
        assert bytes(self.uc.mem_read(BIAS, len(stock))) == expected
        self.uc.mem_write(AD - 16, b"\xc7" * 63)
        self.uc.mem_write(OTHER_AD, bytes(range(31)))

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if offset == 0x72C8:
            # Preceding name/settings/MAC acquisition deliberately not executed.
            sp = uc.reg_read(self.a.UC_ARM_REG_SP)
            uc.mem_write(sp + 0x30, self.mac)
            self.boundaries.append("source-MAC and skipped boot prefix")
            uc.reg_write(self.a.UC_ARM_REG_PC, (BIAS + 0x7498) | 1)
            return
        if offset == 0x74F8:
            self.boundaries.append("skipped resubmission prefix")
            uc.reg_write(self.a.UC_ARM_REG_PC, (BIAS + 0x75FA) | 1)
            return
        if offset == 0x7606:
            self.boundaries.append("skipped resubmission suffix")
            uc.reg_write(self.a.UC_ARM_REG_PC, (BIAS + 0x7666) | 1)
            return
        if address == 0x4926:
            r0, r1, r2, r3 = [uc.reg_read(r) for r in self.registers]
            if (r0, r1, r3) != (0x3300, 0x262, AD) or r2 not in (12, 31):
                raise ProofError("unexpected GAP submission ABI")
            sp = uc.reg_read(self.a.UC_ARM_REG_SP)
            output, = self._stack(1)
            assert output == sp + 4
            self.gap_calls.append((r1, r2, r3, self._read_bytes(r3, r2)))
            uc.mem_write(output, bytes([self.status]))
            self._return(0xD00DFEED)  # real wrapper must read pointed byte
            return
        ranges = ((0x72C4, 0x72C8), (0x7498, 0x74F2), (0x74F4, 0x74F8),
                  (0x75FA, 0x7606), (0x7666, 0x766A), (0x15B30, 0x15B4C))
        if any(lo <= offset and offset + size <= hi for lo, hi in ranges):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)

    def checked_call(self, offset):
        before = bytes(self.uc.mem_read(0x200000, 0x30000))
        result = self.call(offset)
        after = bytes(self.uc.mem_read(0x200000, 0x30000))
        changed = {0x200000 + i for i, (a, b) in enumerate(zip(before, after)) if a != b}
        assert all(AD <= a < AD + 31 or self.STACK - 1024 <= a < self.STACK + 32
                   for a in changed)
        assert self.uc.mem_read(AD - 16, 16) == b"\xc7" * 16
        assert self.uc.mem_read(AD + 31, 16) == b"\xc7" * 16
        assert self.uc.mem_read(OTHER_AD, 31) == bytes(range(31))
        return result


def ad_elements(payload):
    """Parse only a fixture's submitted bytes, rejecting stale or cut elements."""
    elements = []
    offset = 0
    while offset < len(payload):
        length = payload[offset]
        if length == 0:
            assert not any(payload[offset:])
            break
        assert offset + length < len(payload), "invalid/truncated AD element"
        elements.append(payload[offset + 1:offset + length + 1])
        offset += length + 1
    return elements


@pytest.mark.parametrize("mac", [bytes(6), bytes.fromhex("30324133cc07"), b"\xff" * 6])
@pytest.mark.parametrize("status", [0, 1, 255])
def test_builder_and_resubmission_preserve_manufacturer_remove_only_service(mac, status):
    stock = STOCK.read_bytes()
    baseline = AdvertisingHarness(stock, patched=False, mac=mac, status=status)
    candidate = AdvertisingHarness(stock, patched=True, mac=mac, status=status)
    for h in (baseline, candidate):
        assert h.checked_call(0x72C4) == status
        h.checked_call(0x74F4)
        assert h.boundaries == ["source-MAC and skipped boot prefix",
                                "skipped resubmission prefix", "skipped resubmission suffix"]
        assert len(h.gap_calls) == 2
        assert h.gap_calls[0] == h.gap_calls[1]
        assert {0x74D4, 0x74EA, 0x7602, 0x15B48} <= h.executed
    original = baseline.gap_calls[0][3]
    packed = candidate.gap_calls[0][3]
    assert original[:4] == bytes.fromhex("0303e7fe")
    assert original[4:16] == packed == bytes.fromhex("0bff3412fee7") + mac[::-1]
    assert ad_elements(packed) == [bytes.fromhex("ff3412fee7") + mac[::-1]]
    assert candidate.uc.mem_read(AD + 12, 19) == b"\xc7" * 19
    assert original[16:] == b"\xc7" * 15


def test_plan_has_only_thirteen_size_neutral_instructions_and_no_writer():
    stock = STOCK.read_bytes()
    edits = advertising_plan(stock)
    assert len(edits) == len({e.file_offset for e in edits}) == 13
    assert all(e.file_offset % 2 == 0 and len(e.before) == len(e.after) == 2 for e in edits)
    report = advertising_report(stock)
    assert report["instruction_edit_bytes"] == 26
    assert report["added_flash_bytes"] == report["added_ram_bytes"] == 0
    assert not any(report[k] for k in ("stock_file_modified", "stock_hooks_attached", "flashable"))


@pytest.mark.parametrize("offset", [0x749C, 0x74E6, 0x75FE, 0x7774, 0x7778, 0x1000])
def test_mutated_stock_refused_including_untouched_code(offset):
    stock = bytearray(STOCK.read_bytes())
    stock[offset] ^= 1
    with pytest.raises(ValueError, match="exact pinned stock"):
        advertising_plan(stock)


@pytest.mark.parametrize("missing_length", [0x74E6, 0x75FE])
def test_partial_length_edit_exposes_dirty_tail_and_is_not_a_valid_submission(missing_length):
    h = AdvertisingHarness(STOCK.read_bytes(), patched=True, mac=b"abcdef", status=0,
                           omitted=(missing_length,))
    h.checked_call(0x72C4)
    h.checked_call(0x74F4)
    bad = h.gap_calls[0 if missing_length == 0x74E6 else 1]
    assert bad[1] == 31 and bad[3][12:] == b"\xc7" * 19
    with pytest.raises(AssertionError, match="invalid/truncated"):
        ad_elements(bad[3])
