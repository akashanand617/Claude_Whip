"""Stock-only ownership facts and selected actual-Thumb overlay proof."""
import struct
from pathlib import Path

import pytest

from whip import fwlayout

STOCK = Path(__file__).resolve().parents[1] / "firmware/rt02cr-stock-3.12.02.bin"


@pytest.fixture
def stock():
    return STOCK.read_bytes()


def test_tail_is_startup_overlay_not_free_bytes(stock):
    audit = fwlayout.audit_layout(stock)
    first, second, third = audit["overlays"]
    assert (first["code_file"], first["code_size"], first["code_ram"],
            first["code_ram_end_exclusive"]) == (0x21A58, 200, 0x20E734, 0x20E7FC)
    assert first["code_file"] + first["code_size"] == len(stock)
    assert first["data_size"] == first["bss_size"] == 0
    assert second["code_size"] == third["code_size"] == 0
    assert audit["safe_static_allocation"] is audit["safe_flash_allocation"] is None
    assert audit["allocator"]["allocation_and_failure_isolation_proven"] is False


def test_exact_occupied_intervals_are_contiguous(stock):
    ranges = fwlayout.audit_layout(stock)["occupied_application_ram"]
    assert all(a["end_exclusive"] == b["start"] for a, b in zip(ranges, ranges[1:]))
    assert ranges[0]["start"] == 0x207C00
    assert ranges[-1]["end_exclusive"] == 0x20E7FC


@pytest.mark.parametrize("offset", [0, 0x6EE, 0xA34, 0x21578, 0x21A58, 0x21B1F])
def test_never_map_modified_stock(stock, offset):
    changed = bytearray(stock)
    changed[offset] ^= 1
    with pytest.raises(ValueError, match="exact pinned"):
        fwlayout.audit_layout(bytes(changed))
    with pytest.raises(ValueError, match="exact pinned"):
        fwlayout.StockOverlayHarness(bytes(changed))


def test_boot_loads_zero_before_calling_its_ram_entry(stock):
    def branch_target(blob, pc):
        a, b = struct.unpack("<HH", blob)
        assert a & 0xF800 == 0xF000 and b & 0xD000 == 0xD000
        s = (a >> 10) & 1
        i1, i2 = 1 ^ ((b >> 13) & 1) ^ s, 1 ^ ((b >> 11) & 1) ^ s
        immediate = (s << 24) | (i1 << 23) | (i2 << 22) | ((a & 1023) << 12) | ((b & 2047) << 1)
        return (pc + 4 + immediate - ((1 << 25) if s else 0)) & 0xFFFFFFFF

    assert stock[0x66E:0x670] == b"\x00\x20"  # movs r0,#0
    assert branch_target(stock[0x670:0x674], fwlayout.BIAS + 0x670) == fwlayout.BIAS + 0xA34
    assert branch_target(stock[0x6A4:0x6A8], fwlayout.BIAS + 0x6A4) == 0x20E734
    # Branches decode correctly at execution address, not flash load address.
    for off, target in ((0x21A62, 0x2A8), (0x21A6E, 0x2A8), (0x21A86, 0x34D0),
                        (0x21ABE, 0x5E6A), (0x21AD6, 0x5E6A), (0x21AE4, 0x5AA8)):
        assert branch_target(stock[off:off + 4], 0x20E734 + off - 0x21A58) == target


@pytest.fixture
def harness(stock):
    pytest.importorskip("unicorn")
    return fwlayout.StockOverlayHarness(stock)


def test_actual_loader_copies_exact_tail_and_no_neighbors(harness, stock):
    uc = harness.uc
    uc.mem_write(0x20E724, b"\xA5" * 232)
    assert harness.call(fwlayout.OVERLAY_QUERY_FILE) == 3
    assert harness.call(fwlayout.OVERLAY_LOADER_FILE, 0) == 1
    assert bytes(uc.mem_read(0x20E734, 200)) == stock[0x21A58:]
    assert bytes(uc.mem_read(0x20E724, 16)) == bytes(uc.mem_read(0x20E7FC, 16)) == b"\xA5" * 16
    assert bytes(uc.mem_read(fwlayout.OVERLAY_STAMP_RAM, 8)) == stock[0x20838:0x20840]
    assert harness.call(fwlayout.OVERLAY_QUERY_FILE) == 0


def test_loaded_identity_avoids_duplicate_copy(harness):
    harness.call(fwlayout.OVERLAY_LOADER_FILE, 0)
    harness.operations.clear()
    harness.executed.clear()
    assert harness.call(fwlayout.OVERLAY_LOADER_FILE, 0) == 1
    assert len(harness.operations) == 1
    assert harness.operations[0][0] == "compare"
    assert 0xA5A not in harness.executed


@pytest.mark.parametrize("index", [1, 2])
def test_zero_size_overlay_changes_identity_but_keeps_old_bytes(harness, stock, index):
    harness.call(fwlayout.OVERLAY_LOADER_FILE, 0)
    harness.operations.clear()
    assert harness.call(fwlayout.OVERLAY_LOADER_FILE, index) == 1
    assert bytes(harness.uc.mem_read(0x20E734, 200)) == stock[0x21A58:]
    assert all(op[-1] == 0 for op in harness.operations if op[0] == "copy" and op[1] != fwlayout.OVERLAY_STAMP_RAM)
    assert harness.call(fwlayout.OVERLAY_QUERY_FILE) == index


@pytest.mark.parametrize("index", [3, 255, 0xFFFFFFFF])
def test_invalid_overlay_index_has_no_memory_operations(harness, index):
    assert harness.call(fwlayout.OVERLAY_LOADER_FILE, index) == 0
    assert harness.operations == []


def test_changed_descriptor_cannot_expand_mock_copy(harness):
    harness.uc.mem_write(fwlayout.OVERLAY_TABLE_RAM + 24, struct.pack("<I", 204))
    with pytest.raises(fwlayout.LayoutProofError, match="unexpected overlay memcpy"):
        harness.call(fwlayout.OVERLAY_LOADER_FILE, 0)


def test_execution_is_bounded_to_loader_and_query(harness):
    with pytest.raises(fwlayout.LayoutProofError, match="reviewed loader"):
        harness.call(0x662)
    with pytest.raises(fwlayout.LayoutProofError, match="budget exhausted"):
        harness.call(fwlayout.OVERLAY_LOADER_FILE, budget=1)


def test_actual_setup_supplies_all_three_layout_arguments(harness):
    harness.call(0x6D4)
    assert harness.layout_arguments == (0x7000, 0x7400, 0)


@pytest.mark.parametrize("wrapper,args,kind,size", [(0x12948, (460, 0), "alloc", 460),
                                                   (0x12958, (1, 600), "zalloc", 600)])
@pytest.mark.parametrize("result", [0, 0x20F008])
def test_actual_stock_allocator_wrappers_preserve_null_or_pointer(harness, wrapper, args, kind, size, result):
    harness.allocator_result = result
    assert harness.call(wrapper, args[0], second=args[1]) == result
    assert len(harness.operations) == 1
    assert harness.operations[0][:3] == (kind, 0, size)


@pytest.mark.parametrize("vtor", [0, 0x200000])
def test_loaded_vector_initializer_does_not_write_past_vector_table(harness, stock, vtor):
    harness.call(fwlayout.OVERLAY_LOADER_FILE, 0)
    harness.uc.mem_write(0x200000, struct.pack("<I", 0x47E7) * 58)
    harness.uc.mem_write(0xE000ED08, struct.pack("<I", vtor))
    harness.uc.mem_write(0x20E7FC, b"\xA5" * 1028)
    harness.call(0x20E734 - fwlayout.BIAS)
    assert harness.vector_writes
    assert all(0x200008 <= addr <= 0x2000E4 for addr, _ in harness.vector_writes)
    assert bytes(harness.uc.mem_read(0x20E7FC, 1028)) == b"\xA5" * 1028
    expected = struct.unpack("<58I", stock[0x20BE0:0x20CC8])
    for address, value in harness.vector_writes:
        assert value == expected[(address - 0x200000) // 4]
    assert any(op[0] == "vector_init_mock" for op in harness.operations) == (vtor == 0)
