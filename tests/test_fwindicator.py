"""Entry-only retirement experiment in emulator memory, never an OTA artifact.

These tests do not clear producer inventory, physical STOP, retention or code
reclamation gates. Normal Health is tested with existing optical mocks, not
with the V2 image and not by treating absence of an LED request as shutdown.
"""
from pathlib import Path
import struct

import pytest

pytest.importorskip("unicorn", reason="requires requirements-firmware-proof.txt")
from whip.fwcontinuity import BIAS, ProofError  # noqa: E402
from whip.fwhealth_lifecycle import OPTICAL_ENABLE  # noqa: E402
from whip.fwindicator import (  # noqa: E402
    BEGIN, END, ENTRIES, RETURN_ZERO, audit_indicators, branch_candidate,
)
from whip.fwstock_binding import StockBindingHarness, MOCK_TIMER  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STOCK = (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()


class IndicatorExperiment(StockBindingHarness):
    """Strictly emulator-only: original image must pass the parent identity gate.

    Retired bodies deliberately fault if reached. They are NOT erased/reused;
    this catches exercised bypasses but cannot rule out unexercised references.
    """

    def __init__(self, retired):
        self.retired = retired
        self.notifications = []
        self.adjacent_requests = []
        super().__init__(STOCK)
        if retired:
            for offset, _, _ in ENTRIES:
                self.uc.mem_write(BIAS + offset, RETURN_ZERO)

    def _code(self, uc, address, size, opaque):
        offset = address - BIAS
        if BEGIN <= offset < END:
            if self.retired and not any(o <= offset < o + 4 for o, _, _ in ENTRIES):
                raise ProofError("execution bypassed a retired indicator entry")
            self.executed.add(offset)
            return
        if offset == 0x7E30:
            pointer = uc.reg_read(self.registers[0])
            self._ram_span(pointer, 16)
            self.notifications.append(bytes(uc.mem_read(pointer, 16)))
            self._return()  # notification packaging only, not BLE delivery
            return
        if offset in (0x148FE, 0x14902):
            # Adjacent actuator request is deliberately preserved, not silently
            # removed along with an LED request. Its hardware is outside scope.
            args = tuple(uc.reg_read(r) for r in self.registers[:3])
            self.adjacent_requests.append((offset, *args))
            self._return()
            return
        if any(lo <= offset < hi for lo, hi in (
            (0x3DFC, 0x3E04), (0x3FE8, 0x4002),  # no-op hooks; checksum
            (0x47B4, 0x47D6), (0x47F4, 0x480C),  # unchanged command acknowledgment
            (0x580E, 0x5882),                    # UART51, including stack argument
            (0xF92E, 0xF934),                    # optical busy predicate
            (0x17D3A, 0x17D56),                  # signed division wrapper
        )):
            self.executed.add(offset)
            return
        super()._code(uc, address, size, opaque)


def test_reference_scan_is_pinned_bounded_and_not_reclamation_approval():
    report = audit_indicators(STOCK)
    assert [(b["file"], b["kind"], b["target_file"])
            for b in report["external_branch_candidates"]] == [
        (0x1344, "bl", 0x3C18), (0x1650, "bl", 0x3C18),
        (0x167A, "bl", 0x3DC0), (0x3468, "bl", 0x3D36),
        (0x35D8, "bl", 0x3D36), (0x35E4, "bl", 0x3D36),
        (0x35F2, "bl", 0x3D36), (0x47FE, "bl", 0x3C18),
        (0x583A, "bl", 0x3C18), (0x5856, "bl", 0x3CD2),
        (0x5B04, "bl", 0x3C18), (0xD780, "bl", 0x3D36),
        (0xF828, "bl", 0x3CAC),
    ]
    assert report["pointer_candidates"] == [
        {"file": 0x3DF0, "target_file": 0x3AC5},
        {"file": 0x3DF8, "target_file": 0x3B7B},
    ]
    assert report["scan_regions"][-2:] == [
        {"file_start": 0x20CC8, "file_end": 0x21578, "runtime_start": 0x207C00},
        {"file_start": 0x21A58, "file_end": len(STOCK), "runtime_start": 0x20E734},
    ]
    assert report["body_bytes_after_retaining_entries"] == 764
    assert report["approved_reclaimed_bytes"] == 0
    for key in ("reference_closure_verified", "cold_boot_retention_verified",
                "physical_shutdown_verified", "flashable"):
        assert report[key] is False


@pytest.mark.parametrize("path", ["rt02cr-25hz.bin", "rt02cr-25hz-optical-off-v2-experimental.bin"])
def test_indicator_analysis_rejects_nonstock_images(path):
    with pytest.raises(ValueError, match="pinned stock"):
        audit_indicators((ROOT / "firmware" / path).read_bytes())


@pytest.mark.parametrize("offset", [0, BEGIN, END, 0x3DF0, 0x21A58, len(STOCK) - 1])
def test_indicator_analysis_rejects_any_witness_or_unrelated_drift(offset):
    altered = bytearray(STOCK)
    altered[offset] ^= 1
    with pytest.raises(ValueError, match="pinned stock"):
        audit_indicators(bytes(altered))


@pytest.mark.parametrize("encoded,expected", [
    ("00e0", ("b", 0x1004)), ("fee7", ("b", 0x1000)),
    ("00d0", ("bcc", 0x1004)), ("fed1", ("bcc", 0x1000)),
    ("00f000f8", ("bl", 0x1004)), ("fff7feff", ("bl", 0x1000)),
    ("00df", None), ("00de", None), ("7047", None), ("00f0", None),
])
def test_small_branch_decoder_uses_execution_address_and_signed_displacement(encoded, expected):
    assert branch_candidate(bytes.fromhex(encoded), 0, 0x1000) == expected


@pytest.mark.parametrize("offset,name,before", ENTRIES, ids=[e[1] for e in ENTRIES])
@pytest.mark.parametrize("value", [0, 1, 4, 8, 0xFF, 0xFFFFFFFF])
def test_retired_entries_return_without_stack_ram_or_hardware_side_effects(offset, name, before, value):
    h = IndicatorExperiment(True)
    saved_registers = [getattr(h.a, f"UC_ARM_REG_R{i}") for i in range(4, 12)]
    for i, r in enumerate(saved_registers):
        h.uc.reg_write(r, 0xA5000000 + i)
    # Deliberately dirty state: retirement does not fabricate a shutdown or
    # clear stale handles. This is not a live hotpatch/cancellation operation.
    h.uc.mem_write(0x209D0C, bytes([0xA5]) * 32)
    ram = bytes(h.uc.mem_read(0x200000, 0x30000))
    assert h.call(offset, value, value, value, value) == 0
    assert bytes(h.uc.mem_read(0x200000, 0x30000)) == ram
    assert [h.uc.reg_read(r) for r in saved_registers] == [0xA5000000 + i for i in range(8)]
    assert [h.uc.reg_read(r) for r in h.registers[1:]] == [value] * 3
    assert h.executed == {offset, offset + 2}
    assert not h.timer_calls and not h.indicator_requests and not h.transfers
    assert not h.stk_writes and not h.optical_starts


def test_only_the_forty_entry_bytes_are_replaced_in_fixture_memory():
    h = IndicatorExperiment(True)
    actual = bytes(h.uc.mem_read(BIAS, len(STOCK)))
    entries = {o for o, _, _ in ENTRIES}
    for i, (old, new) in enumerate(zip(STOCK, actual)):
        if not any(o <= i < o + 4 for o in entries):
            assert old == new
    for offset, _, _ in ENTRIES:
        assert actual[offset:offset + 4] == RETURN_ZERO
    assert actual[END:] == STOCK[END:]  # literal pool, neighbors, DFU, boot overlay
    for offset in (0x3DFC, 0x3DFE, 0x3E00, 0x3E02):
        assert h.call(offset, 0x35) == 0x35  # original bx-lr ABI, NOT zero-return stub


@pytest.mark.parametrize("offset,name,before", ENTRIES, ids=[e[1] for e in ENTRIES])
def test_bypassing_entry_into_unretired_body_is_not_silently_accepted(offset, name, before):
    h = IndicatorExperiment(True)
    with pytest.raises(ProofError, match="bypassed"):
        h.call(offset + 4)


@pytest.mark.parametrize("retired", [False, True])
def test_queued_old_brightness_callback_cannot_request_leds_after_entry_retirement(retired):
    h = IndicatorExperiment(retired)
    h.uc.mem_write(0x209D10, struct.pack("<II", MOCK_TIMER, MOCK_TIMER))
    h.uc.mem_write(0x209D18, struct.pack("<I", 4))
    h.uc.mem_write(0x209D1C, b"\x01")
    h.call(0x3CAC)
    h.call(0x3AC4)
    assert bool(h.indicator_requests) is (not retired)
    if retired:
        # Still NOT evidence that pre-existing optics/timers physically stopped.
        assert bytes(h.uc.mem_read(0x209D1C, 1)) == b"\x01"
        assert h.call(0x3DC0) == 0
        assert not h.timer_calls and not h.transfers


@pytest.mark.parametrize("mask", [0x10, 0x80, 0x20, 0x40, 0x100, 0x200, 0x1000])
@pytest.mark.parametrize("probe_ok", [True, False])
def test_normal_health_start_and_probe_failure_match_unmodified_stock(mask, probe_ok):
    traces = []
    for retired in (False, True):
        h = IndicatorExperiment(retired)
        h.probe_ok = probe_ok
        result = h.call(OPTICAL_ENABLE, mask)
        traces.append((result, h.ownership(), h.optical_state(), h.optical_starts,
                       h.transfers, bytes(h.uc.mem_read(0x2084B0, 0x6284))))
        assert not h.indicator_requests
        assert 0xF828 in h.executed and 0x3CAC in h.executed
        assert bool(h.optical_starts) is probe_ok
    assert traces[0] == traces[1]  # includes initialized data and entire stock BSS


@pytest.mark.parametrize("existing,requested", [
    (0x10, 0x10), (0x10, 0x80), (0x80, 0x10), (0x80, 0x200),
    (0x40, 0x80), (0x1000, 0x20),
])
def test_existing_health_ownership_is_not_cleared_by_indicator_retirement(existing, requested):
    traces = []
    for retired in (False, True):
        h = IndicatorExperiment(retired)
        h.set_ownership(existing)
        result = h.call(OPTICAL_ENABLE, requested)
        traces.append((result, h.ownership(), h.optical_state(), h.optical_starts,
                       h.transfers, bytes(h.uc.mem_read(0x2084B0, 0x6284))))
        assert not h.indicator_requests and not h.timer_calls
    assert traces[0] == traces[1]


@pytest.mark.parametrize("retired", [False, True])
def test_real_command_ack_is_preserved_when_indicator_request_is_retired(retired):
    h = IndicatorExperiment(retired)
    h.call(0x47F4)
    assert h.notifications == [b"\x10" + bytes(14) + b"\x10"]
    assert bool(h.indicator_requests) is (not retired)
    assert bool(h.timer_calls) is (not retired)


@pytest.mark.parametrize("subcommand", [1, 8, 9])
def test_uart51_ack_and_neighbor_operation_survive_retirement(subcommand):
    traces = []
    for retired in (False, True):
        h = IndicatorExperiment(retired)
        packet = bytes([0x51, subcommand, 20, 1, 1, 2, 3]) + bytes(9)
        pointer = 0x221000
        h.uc.mem_write(pointer, packet)
        h.call(0x580E, pointer)
        traces.append((h.notifications, h.adjacent_requests))
        assert h.notifications == [b"\x51" + bytes(14) + b"\x51"]
        assert bool(h.adjacent_requests) is (subcommand in (1, 9))
        if retired:
            assert not h.timer_calls and not h.indicator_requests
    assert traces[0] == traces[1]
