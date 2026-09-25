"""Static RAM-ownership evidence for unified state; no allocation is approved."""
import struct as _struct
from pathlib import Path

import pytest

from whip import fwram

STOCK = Path(__file__).resolve().parents[1] / "firmware/rt02cr-stock-3.12.02.bin"
# Exact 16-byte window from capacity-20260923-idle-config (see test_fwcapacity).
RAM_CONFIG = bytes.fromhex("007c2000007000000074000070380000")


@pytest.fixture(scope="module")
def stock():
    return STOCK.read_bytes()


@pytest.fixture(scope="module")
def bulk(stock):
    return fwram.bulk_extents(stock)


def test_refuses_modified_stock(stock):
    changed = bytearray(stock)
    changed[fwram.PRE_MAIN_INSTALL] ^= 1
    with pytest.raises(ValueError, match="exact pinned"):
        fwram.overlay_entry_evidence(bytes(changed))


def test_exec_regions_match_layout_audit(stock):
    from whip import fwlayout
    ram = {r["kind"]: r for r in fwlayout.audit_layout(stock)["occupied_application_ram"]}
    (xlo, xhi, xb), (rlo, rhi, rb), (olo, ohi, ob) = fwram.EXEC_REGIONS
    assert (rlo + rb, rhi + rb) == (ram["permanent RAM code"]["start"],
                                    ram["permanent RAM code"]["end_exclusive"])
    assert (olo + ob, ohi + ob) == fwram.OVERLAY_RAM and ohi == len(stock)
    assert xb == fwram.BIAS and xhi == rlo
    assert all(b % 4 == 0 for _, _, b in fwram.EXEC_REGIONS)  # PC-literal math holds


def test_only_zero_length_descriptor_endpoints_point_into_gap(stock):
    refs = fwram.literal_references(stock, fwram.OVERLAY_RAM[1], fwram.APP_RAM[1])
    assert refs == [(0x21588, 0x20E7FC), (0x2158C, 0x20E7FC)]


def test_bl_and_stored_pointer_scan_reaches_overlay_only_from_pre_main(stock):
    """Candidate scan: immediate BLs plus stored pointers; indirect/ROM paths open."""
    e = fwram.overlay_entry_evidence(stock)
    assert e["scenario_signatures"] == [b"BootOnce", b"Scene_B\x00", b"Scene_C\x00"]
    assert e["loader_bl_sites"] == [fwram.OVERLAY_BOOT_LOAD_CALL]
    assert e["loader_pointer_literals"] == []
    assert e["query_bl_sites"] == e["query_pointer_literals"] == []
    assert e["overlay_bl_sites"] == [(fwram.OVERLAY_BOOT_EXEC_CALL, fwram.OVERLAY_RAM[0])]
    # Only the overlay table names the RAM copy; no code pointer (Thumb bit) does.
    assert {v for _, v in e["overlay_literals"]} == {fwram.OVERLAY_RAM[0]}
    assert all(0x21578 <= off < 0x21578 + 3 * 36 for off, _ in e["overlay_literals"])


def test_pointer_scan_finds_pre_main_only_in_app_pre_main_install(stock):
    e = fwram.overlay_entry_evidence(stock)
    assert fwram.PRE_MAIN_FILE < fwram.OVERLAY_BOOT_LOAD_CALL < fwram.OVERLAY_BOOT_EXEC_CALL
    assert e["pre_main_bl_sites"] == []
    assert e["pre_main_pointer_literals"] == [fwram.PRE_MAIN_POINTER_LITERAL]
    assert e["pre_main_installed_into"] == fwram.APP_PRE_MAIN_SLOT


def test_top_static_objects_end_at_overlay_start(stock, bulk):
    clears = {(dst, n) for _, _, dst, n in bulk["app_ram_resolved"] if dst >= 0x20E700}
    assert clears == {(0x20E708, 0x28)}
    assert bulk["max_app_ram_end"] == 0x20E730
    buffer = fwram.base_offsets(stock, 0x20E708, window=24)
    assert buffer["offsets"] == list(range(0, 0x28, 4))
    # Two 40-byte clears, a callee-saved base across a divide helper, and the
    # pointer handed through 0x169a0 to the read-only 10-word mean at 0x17188.
    assert buffer["escapes"] == [0x1494E, 0x14A0A, 0x14B4A, 0x14BDC]
    assert fwram.top_buffer_reader_stores(stock) == []
    assert fwram.base_offsets(stock, 0x20E730) == {"offsets": [0], "escapes": []}
    assert 0x20E708 + 0x28 == 0x20E730 and 0x20E730 + 4 == fwram.LAST_STATIC_END


def test_bulk_survey_reports_unresolved_sites_rather_than_closing(bulk):
    assert bulk["calls"] == 194
    assert len(bulk["resolved"]) == 34
    assert len(bulk["unresolved_sites"]) == 160


def test_captured_config_tiles_to_cache_boundary_but_heap_base_unproven():
    t = fwram.ram_tiling(RAM_CONFIG)
    assert t["app_end_exclusive"] == fwram.APP_RAM[1]
    assert t["tiles_to_cache_boundary"] is True
    assert t["heap_start_proven"] is False
    assert t["allocation_approved"] is False


@pytest.mark.parametrize("region, objects, fits, margin", [
    ("aligned_gap", [("state", 796), ("commit", 20)], True, 204),
    ("aligned_gap", [("state", 796), ("receipt", 288)], False, -64),
    ("post_boot_overlay_and_gap", [("state", 796), ("receipt", 288)], True, 136),
    ("post_boot_overlay_and_gap", [("state", 796), ("commit", 20), ("receipt", 288)], True, 112),
])
def test_layout_arithmetic(region, objects, fits, margin):
    plan = fwram.plan_layout(objects, region)
    assert (plan["fits"], plan["margin"], plan["approved"]) == (fits, margin, False)
    spans = [(o["start"], o["end_exclusive"]) for o in plan["objects"]]
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert all(start % 8 == 0 for start, _ in spans)


@pytest.mark.parametrize("objects, align", [([("x", 0)], 8), ([("x", 4)], 2)])
def test_layout_refuses_invalid_requests(objects, align):
    with pytest.raises(ValueError):
        fwram.plan_layout(objects, "aligned_gap", align)


def test_nothing_is_approved(stock):
    audit = fwram.audit_ram_ownership(stock, RAM_CONFIG)
    assert audit["allocation_approved"] is False
    assert audit["regions"]["approved_for_use"] is False
    assert audit["unresolved"]
    assert fwram.receipt_on_stack_bytes() == 568


# --- Unexecuted read-plan decoders: synthetic fixtures, not device evidence ---
def _heap_window(free, low, total, start=(0, 0, 0, 0), tail=(0,) * 5):
    return _struct.pack("<15I", *free, *low, *total, *start, *tail)


def test_read_plan_is_unauthorized_and_never_stores_raw_gap():
    plan = fwram.read_plan()
    assert plan["authorized"] is plan["executed"] is False
    gap = [w for w in plan["windows"] if w["address"] == fwram.GAP_WINDOW_V2[0]][0]
    assert "only" in gap["store"] and gap["bytes"] == 0x20EC00 - 0x20E7DC
    assert "pointer following" in plan["never"]


def test_heap_window_reports_peak_only_when_counters_consistent():
    ok = fwram.decode_heap_window(_heap_window((20000, 5000), (12000, 4000), (29000, 14000)))
    assert ok["counters_consistent"] and ok["data_heap_peak_used"] == 17000
    assert ok["data_total_within_config"] is True
    bad = fwram.decode_heap_window(_heap_window((1000, 5000), (12000, 4000), (29000, 14000)))
    assert bad["counters_consistent"] is False and bad["data_heap_peak_used"] is None
    with pytest.raises(ValueError):
        fwram.decode_heap_window(b"\0" * 59)


@pytest.mark.parametrize("nxt, size, expected", [
    (0, 0x80000000 | 0x40, True),
    (0, 0x40, False),                  # free block: inconclusive
    (0x20F000, 0x80000040, False),     # nonzero next
    (0, 0x80000000 | 0x7408, False),   # larger than configured heap
    (0, 0x80000000 | 0x44, False),     # not 8-byte granular
])
def test_heap_base_signature_is_conservative(nxt, size, expected):
    sig = fwram.heap_base_signature(_struct.pack("<II", nxt, size))
    assert sig["allocated_header_shape"] is expected
    assert sig["verdict"].startswith("consistent") is expected


def test_gap_comparison_proves_writers_never_absence():
    n = fwram.GAP_WINDOW_V2[1]
    first = fwram.gap_digest(bytes(n))
    same = fwram.compare_gap_digests(first, fwram.gap_digest(bytes(n)))
    assert same == {"changed_block_offsets": [], "writer_proven": False,
                    "unused_proven": False, "zero_blocks": len(first)}
    touched = bytearray(n); touched[0x100] = 1
    diff = fwram.compare_gap_digests(first, fwram.gap_digest(bytes(touched)))
    assert diff["changed_block_offsets"] == [0x100] and diff["writer_proven"]
    assert all(set(b) == {"offset", "sha256", "all_zero"} for b in first)


def test_vendor_layout_tiles_onto_independent_observations(stock):
    from whip import fwlayout
    doc = fwram.documented_layout(RAM_CONFIG)
    span = {name: (lo, hi) for name, lo, hi in doc["parts"]}
    assert fwram.STOCK_STARTUP_SP == fwlayout.audit_layout(stock)["startup_stack_top"]
    assert doc["main_stack_top_matches_startup_sp"]
    assert doc["captured_patch_inside_patch_ram"]
    assert doc["heap_ends_at_data_ram_end"]
    assert doc["candidate_inside_app_ram"]
    assert doc["upperstack_bytes"] == 2048              # the guide's default "2 KB*"
    assert span["data_heap"][0] == fwram.APP_RAM[1] == 0x20EC00
    assert all(a[2] == b[1] for a, b in zip(doc["parts"], doc["parts"][1:]))
    assert doc["owners_measured"] is False


# --- ROM reset branch from the captured 2026-09-23 ROM window (no execution) ---
ROM_ARCHIVE = STOCK.parents[0] / "research/2026-09-23/rom-integration/rom-integration.json"


def test_rom_reset_handler_branches_to_resume_before_boot_chain():
    rom = fwram.rom_window(ROM_ARCHIVE.read_bytes())
    e = fwram.reset_branch_evidence(rom)
    assert e["reads_aon_reason_word_0"] and e["tests_bit1_then_resume_branch"]
    assert e["resume_jumps_via_saved_pointer"]
    assert e["first_boot_loads_patch_image_then_hook"]
    # The app_pre_main caller is NOT in this window, and the resume target is unread.
    assert e["app_hook_literals_in_window"] == []
    assert e["resume_target_read"] is False and e["app_pre_main_caller_located"] is False


def test_rom_window_refuses_other_archives():
    with pytest.raises(ValueError):
        fwram.rom_window(b"{}")


RESUME_CODE_ARCHIVE = STOCK.parents[0] / "research/2026-09-24/ram-ownership-resume-code/resume-code.json"


def test_dlps_resume_target_returns_to_idle_task_without_app_hooks():
    e = fwram.resume_routine_evidence(RESUME_CODE_ARCHIVE.read_bytes())
    assert e["shape"] == ["push", "movs", "adds", "bl", "ldr", "subs", "ldr", "blx", "bl", "pop"]
    assert e["calls"] == ["#0xd0b8", "r1", "#0x135b8"]
    assert e["ends_in_return_idle_task"] is True
    assert e["app_hook_literals_in_window"] == []
    assert e["exhaustive"] is False and len(e["unread_callees"]) == 3
