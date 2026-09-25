"""Execute new captured support bytes OFFLINE; no physical timing/recovery claim.

This support-only capture did not include the nonzero create hook or comparator.
Their later separate capture is exercised in test_fwrom_hook_execution.py.
Tests of the ROM create default here are direct-entry counterfactuals, never a
substitute for that hook. Queue/tick/pool/interrupt fixtures remain synthetic.
"""
import hashlib
import json
import random
import struct

import pytest

from tests.test_fwrom_resume_execution import ResumeHarness, kernel_create_harness, SLOT, TIMER, BITMAP, ENTRIES
from tests.test_fwrom_support_archive import ARCHIVE, HASHES
from whip.fwrom_execution import ROMBoundaryError, ROMAssertion
from whip.fwrom_support import ROM_WINDOWS, STATE_WINDOWS


def install_support(h, *, state=True):
    raw = (ARCHIVE / "rom-support.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HASHES["rom-support.json"]
    saved = json.loads(raw)
    for name, address, size in ROM_WINDOWS + (STATE_WINDOWS if state else ()):
        w = saved["windows"][name]; data = bytes.fromhex(w["data_hex"])
        assert w["address"] == address and len(data) == size
        assert hashlib.sha256(data).hexdigest() == w["sha256"]
        if address < 0x200000:
            h.uc.mem_write(address, data)
            h.windows[address] = data
            h.readable.append((address, address + size))
        else:
            h.fixture(address, data)  # Archived idle values, not immutable current state.
    # Exclude unrelated floating-point routines beyond the division return.
    h.select(0x3F97A, 0x3FAD4)
    h.select(0x14238, 0x14248)  # Literal words are NEVER executable.
    return h


@pytest.mark.parametrize("numerator,denominator", [
    (0, 1), (1, 1), (1, 2), (17, 10), (1000, 100), (26, 10),
    (0xFF, 1), (0x100, 1), (0x10000, 3), (0xFFFFFFFF, 1),
    (0xFFFFFFFF, 2), (0xFFFFFFFF, 48), (0x80000000, 0x7FFFFFFF),
    (0x7FFFFFFF, 0x80000000), (0xFFFFFFFF, 0x80000000), (0xFFFFFFFF, 0xFFFFFFFF),
])
def test_actual_unsigned_division_matches_quotient_and_remainder_without_mocks(numerator, denominator):
    h = install_support(ResumeHarness(), state=False)
    assert h.call(0x3F97A, numerator, denominator) == numerator // denominator
    assert h.uc.reg_read(h.a.UC_ARM_REG_R1) == numerator % denominator
    assert not h.calls and not h.writes


def test_unsigned_division_random_and_power_of_two_boundaries_execute_real_code():
    h = install_support(ResumeHarness(), state=False)
    rng = random.Random(0x3F97A)
    pairs = [(rng.getrandbits(32), rng.randrange(1, 1 << 32)) for _ in range(1000)]
    pairs += [((1 << n) + delta, d) for n in range(1, 32) for delta in (-1, 0, 1)
              for d in (1, 3, 10, 48, 100, (1 << n))]
    for numerator, denominator in pairs:
        assert h.call(0x3F97A, numerator, denominator) == numerator // denominator
        assert h.uc.reg_read(h.a.UC_ARM_REG_R1) == numerator % denominator
    assert not h.calls and not h.writes


@pytest.mark.parametrize("numerator", [0, 17, 0xFFFFFFFF])
def test_captured_zero_divisor_returns_zero_and_original_numerator(numerator):
    h = install_support(ResumeHarness(), state=False)
    assert h.call(0x3F97A, numerator, 0) == 0
    assert h.uc.reg_read(h.a.UC_ARM_REG_R1) == numerator
    assert not h.calls and not h.writes


@pytest.mark.parametrize("ipsr", [0, 2, 3, 11, 15, 16, 31])
def test_captured_context_selector_distinguishes_thread_from_exception(ipsr):
    h = install_support(ResumeHarness(), state=False)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, ipsr)
    assert h.call(0x14238) == int(ipsr == 0)
    assert h.uc.reg_read(h.a.UC_ARM_REG_IPSR) == ipsr
    assert not h.calls and not h.writes


def test_support_only_scope_stops_at_missing_create_hook_instead_of_using_default():
    h = install_support(ResumeHarness())
    h.defaults()
    assert h.word(0x201644) == 0x205C01
    with pytest.raises(ROMBoundaryError, match="0x205c00"):
        h.call(0x13634, SLOT, 0x1234, 0x5678, 17, 1, 0x47101)
    assert not h.calls and not h.writes


@pytest.mark.parametrize("period", [1, 8, 9, 10, 17, 32, 1000, 0xFFFFFFF6])
def test_rom_create_default_direct_entry_converts_with_real_helper_and_observed_config(period):
    h, _, _ = kernel_create_harness()
    install_support(h)
    h.fixture(SLOT, bytes(4), writable=True)
    # Intentionally bypass the hook missing from THIS harness. NOT the live wrapper.
    assert h.call(0x13F9E, SLOT, 0x1234, 0x5678, period, 1, 0x47101) == 1
    assert h.word(SLOT) == TIMER
    assert h.word(TIMER + 0x18) == (period + 9) // 10
    assert h.word(TIMER + 0x1C) == 0x5678 and h.word(TIMER + 0x20) == 0x47101
    assert not any(c.address in (0x3F97A, 0x14238, 0x108E0) for c in h.calls)
    assert h.word(0x201644) == 0x205C01  # Never silently overwrite the observed hook.


@pytest.mark.parametrize("period", [0xFFFFFFF7, 0xFFFFFFFF])
def test_direct_create_default_wrap_assertion_is_no_longer_conditional_on_divide_mock(period):
    h, _, _ = kernel_create_harness()
    install_support(h)
    h.fixture(SLOT, bytes(4), writable=True)
    with pytest.raises(ROMAssertion): h.call(0x13F9E, SLOT, 0x1234, 0x5678, period, 1, 0x47101)
    assert h.word(SLOT) == 0 and h.word(BITMAP) == 1
    assert not any(c.address == 0x3F97A for c in h.calls)


@pytest.mark.parametrize("which", ["start", "restart"])
@pytest.mark.parametrize("ipsr", [0, 16])
@pytest.mark.parametrize("result", [0, 1, 2, 0xFFFFFFFF])
def test_start_restart_use_captured_literals_helper_context_and_observed_zero_hooks(which, ipsr, result):
    h = install_support(ResumeHarness()); h.defaults()
    h.fixture(SLOT, struct.pack("<I", TIMER), writable=True)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, ipsr)
    h.mock(0xFCFC, "unread thread tick source", lambda c, r: c.return_value(123))
    h.mock(0xFD02, "unread interrupt tick source", lambda c, r: c.return_value(456))
    commands = []

    def command(cpu, regs):
        sp = cpu.uc.reg_read(cpu.a.UC_ARM_REG_SP)
        assert cpu.word(sp) == 0
        assert regs[3] == (sp + 4 if ipsr else 0)
        if ipsr: assert cpu.word(regs[3]) == 0  # No synthetic wake => no MMIO admitted.
        commands.append(regs[:3]); cpu.return_value(result)

    h.mock(0x108E0, "unread queue behavior for isolated wrapper", command)
    assert h.call(ENTRIES[which][0], SLOT, 17) == int(result == 1)
    code = (6 if ipsr else 1) if which == "start" else (9 if ipsr else 4)
    value = (456 if ipsr else 123) if which == "start" else 2
    assert commands == [(TIMER, code, value)] and not h.writes
    assert not h.synthetic_literals
    assert not any(c.address in (0x3F97A, 0x14238) for c in h.calls)


@pytest.mark.parametrize("magic,expected", [(0, 0), (0x5A5A12A5, 1), (0x5A5A12A4, 0)])
def test_ota_table_header_magic_check_uses_actual_pool_without_recovery_claim(magic, expected):
    h = install_support(ResumeHarness(), state=False)
    h.select(0x8A82, 0x8AE2); h.select(0x4C7A, 0x4C90)
    header = bytearray(52); header[0] = 12
    struct.pack_into("<H", header, 4, 0x2790)
    struct.pack_into("<I", header, 0x30, magic)
    h.fixture(0x300000, header)
    h.fixture(0x200050, b"\xa5" * 32, writable=True)
    assert h.call(0x8A82, 0x300000, 0x2790) == expected
    assert h.writes == ([] if expected else [(0x200060, 1, 0x12)])
    assert not h.calls  # Selected header-fields check, NOT image checksum/copy/boot.


def test_support_only_header_scope_stops_at_missing_comparator_not_fabricated_success():
    h = install_support(ResumeHarness(), state=False)
    h.select(0x8A82, 0x8AE2)
    header = bytearray(52); header[0] = 12
    struct.pack_into("<H", header, 4, 0x2793)
    header[12:28] = bytes.fromhex("f94c6b7e11c5eb118282f74a0c0cef5b")
    h.fixture(0x300000, header)
    with pytest.raises(ROMBoundaryError, match="0x8e24"):
        h.call(0x8A82, 0x300000, 0x2793)
    assert h.uc.reg_read(h.a.UC_ARM_REG_R0) == 0x30000C
    assert h.uc.reg_read(h.a.UC_ARM_REG_R2) == 16
    expected_at = h.uc.reg_read(h.a.UC_ARM_REG_R1)
    assert bytes(h.uc.mem_read(expected_at, 16)) == header[12:28]
    assert not h.calls and not h.writes


def test_capture_does_not_authorize_execution_of_literal_or_unrelated_helper_tail():
    h = install_support(ResumeHarness(), state=False)
    for address in (0x14248, 0x8420, 0x8CBC, 0x3FAD4):
        with pytest.raises(ROMBoundaryError, match="unreviewed or uncaptured"):
            h.call(address)
