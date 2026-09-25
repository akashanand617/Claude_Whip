"""Pinned-stock RAM ownership evidence for unified state; never grants allocation.

Static analysis of the exact stock image only. It closes selected questions
about the application reservation above stock's last static object; ROM,
upper-stack, ROM-patch, retention and live heap behavior remain unexecuted.
"""
from __future__ import annotations

import struct

from whip import fwcapacity
from whip import fwlayout
from whip.fwlayout import BIAS, OVERLAY_LOADER_FILE, OVERLAY_QUERY_FILE, _pinned

APP_RAM = (0x207C00, 0x20EC00)          # observed appDataAddr / +appDataSize
LAST_STATIC_END = 0x20E734              # BSS end = boot-overlay RAM start
OVERLAY_RAM = (0x20E734, 0x20E7FC)
OVERLAY_BOOT_LOAD_CALL = 0x670
OVERLAY_BOOT_EXEC_CALL = 0x6A4
PRE_MAIN_FILE = 0x662                   # SDK pre_main: BootOnce load + overlay call
PRE_MAIN_POINTER_LITERAL = 0x7FC
PRE_MAIN_INSTALL = 0x6C6                # ldr r1,=app_pre_main; ldr r0,=pre_main; str
APP_PRE_MAIN_SLOT = 0x2011D0            # pinned ROM symbol file: app_pre_main
CACHE_RAM_START = 0x216000              # vendor guide: configurable cache region
ROM_MEMCLR = 0x3F918                    # __rt_memclr_w(dst, bytes)
ROM_MEMCPY = 0x3F848                    # memcpy(dst, src, bytes)
# Highest two statically addressed objects and every stock access to them.
TOP_OBJECTS = {0x20E708: 0x28, 0x20E730: 4}
TOP_BUFFER_READER = (0x17188, 0x171BC)  # 10-word read-only mean via 0x169a0

# Candidate unified RAM consumers, bytes (docs/UNIFIED_READINESS.md). Sizes are
# the current ARM witnesses, not proven complete integration needs.
STATE_BYTES = 796                       # dispatcher + output frame + timer fence
RECEIPT_BYTES = 288                     # ws_receipt, 32 raw frames
COMMIT_PREP_BYTES = 20                  # Health commit candidate, if allocated
OBSERVE_NESTED_STACK = 244              # observed wa_observe path, not a maximum
ARMV6M_EXCEPTION_FRAME = 32             # basic frame, no FPU on Cortex-M0+
ARMV6M_FRAME_ALIGN_PAD = 4              # possible 8-byte stack realignment


# File interval -> execution address. RAM code and the overlay execute at
# different addresses from XIP flash; a BL's target depends on where it runs.
EXEC_REGIONS = (
    (0x450, 0x20CC8, BIAS),                        # XIP application code
    (0x20CC8, 0x21578, 0x207C00 - 0x20CC8),        # permanent RAM code
    (0x21A58, 0x21B20, OVERLAY_RAM[0] - 0x21A58),  # BootOnce overlay
)


def exec_bias(off: int) -> int | None:
    return next((b for lo, hi, b in EXEC_REGIONS if lo <= off < hi), None)


def bl_target(data: bytes, off: int) -> int | None:
    """Absolute target of a Thumb-2 BL candidate at file offset, or None.

    Only immediate BL encodings inside the three executable intervals; data
    that happens to decode as BL yields extra candidates, never fewer."""
    bias = exec_bias(off)
    if bias is None or exec_bias(off + 2) != bias:
        return None
    h1, h2 = struct.unpack_from("<HH", data, off)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xD000) != 0xD000:
        return None
    s = (h1 >> 10) & 1
    imm = ((s << 24) | ((1 - (((h2 >> 13) & 1) ^ s)) << 23)
           | ((1 - (((h2 >> 11) & 1) ^ s)) << 22) | ((h1 & 0x3FF) << 12)
           | ((h2 & 0x7FF) << 1))
    if s:
        imm -= 1 << 25
    return (off + 4 + imm + bias) & 0xFFFFFFFF


def _halfwords(data: bytes, size: int):
    return range(0x450, len(data) - size + 1, 2)


def literal_references(data: bytes, lo: int, hi: int) -> list[tuple[int, int]]:
    """Every little-endian word at ANY byte offset, Thumb bit ignored, in [lo, hi).

    Finds stored constant pointers only; computed/indirect addresses are open."""
    _pinned(data)
    return [(off, w) for off in range(0x450, len(data) - 3)
            if lo <= ((w := struct.unpack_from("<I", data, off)[0]) & ~1) < hi]


def bl_sites(data: bytes, lo: int, hi: int) -> list[tuple[int, int]]:
    _pinned(data)
    return [(off, t) for off in _halfwords(data, 4)
            if (t := bl_target(data, off)) is not None and lo <= t < hi]


def overlay_entry_evidence(data: bytes) -> dict:
    """Who can load or execute the boot overlay's RAM copy after boot."""
    loader = OVERLAY_LOADER_FILE + BIAS
    query = OVERLAY_QUERY_FILE + BIAS
    pre_main = PRE_MAIN_FILE + BIAS
    install = data[PRE_MAIN_INSTALL:PRE_MAIN_INSTALL + 6]
    return {
        "scenario_signatures": [data[o.stamp_flash - BIAS:o.stamp_flash - BIAS + 8]
                                for o in fwlayout.overlays(data)],
        "pre_main_bl_sites": [o for o, _ in bl_sites(data, pre_main, pre_main + 1)],
        "pre_main_pointer_literals": [o for o, _ in literal_references(data, pre_main, pre_main + 2)],
        "pre_main_installed_into": (struct.unpack_from("<I", data, 0x800)[0]
                                    if install == bytes.fromhex("4e494c480860") else None),
        "loader_bl_sites": [o for o, _ in bl_sites(data, loader, loader + 1)],
        "loader_pointer_literals": [o for o, _ in literal_references(data, loader, loader + 2)],
        "query_bl_sites": [o for o, _ in bl_sites(data, query, query + 1)],
        "query_pointer_literals": [o for o, _ in literal_references(data, query, query + 2)],
        "overlay_bl_sites": bl_sites(data, *OVERLAY_RAM),
        "overlay_literals": literal_references(data, *OVERLAY_RAM),
    }


def _capstone():
    """Disassembly-only dependency; the read-plan decoders never need it."""
    import capstone
    from capstone import arm
    return capstone, arm


def _constant_args(data: bytes, md, off: int, want: tuple[int, int]):
    """Straight-line constant propagation into a BL; None if not closed."""
    _, arm = _capstone()
    for back in range(40, 0, -2):
        regs, reached = {}, False
        for ins in md.disasm(data[off - back:off + 4], off - back):
            if ins.address == off:
                reached = True
                break
            m, ops = ins.mnemonic, ins.operands
            if m in ("movs", "mov") and len(ops) == 2 and ops[1].type == arm.ARM_OP_IMM:
                regs[ops[0].reg] = ops[1].imm
            elif m in ("movs", "mov") and len(ops) == 2 and ops[1].type == arm.ARM_OP_REG:
                if ops[1].reg in regs:
                    regs[ops[0].reg] = regs[ops[1].reg]
                else:
                    regs.pop(ops[0].reg, None)
            elif (m == "ldr" and ops[1].type == arm.ARM_OP_MEM
                  and ops[1].mem.base == arm.ARM_REG_PC):
                src = ((ins.address + 4) & ~3) + ops[1].mem.disp
                regs[ops[0].reg] = struct.unpack_from("<I", data, src)[0]
            elif (m in ("adds", "add") and len(ops) == 2
                  and ops[1].type == arm.ARM_OP_IMM and ops[0].reg in regs):
                regs[ops[0].reg] += ops[1].imm
            elif (m in ("adds", "add") and len(ops) == 3
                  and ops[2].type == arm.ARM_OP_IMM and ops[1].reg in regs):
                regs[ops[0].reg] = regs[ops[1].reg] + ops[2].imm
            elif (m == "lsls" and len(ops) == 3 and ops[2].type == arm.ARM_OP_IMM
                  and ops[1].reg in regs):
                regs[ops[0].reg] = (regs[ops[1].reg] << ops[2].imm) & 0xFFFFFFFF
            elif m.startswith("b") or m in ("pop", "push"):
                regs = {}
            else:
                for r in ins.regs_access()[1]:
                    regs.pop(r, None)
        if not reached:
            continue
        dst, length = (regs.get(arm.ARM_REG_R0 + i) for i in want)
        if dst is not None and length is not None:
            return dst, length
    return None


def bulk_extents(data: bytes) -> dict:
    """Constant-destination/length ROM clear/copy calls. Unresolved stays listed."""
    _pinned(data)
    capstone, arm = _capstone()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.detail = True
    resolved, unresolved = [], []
    for off in _halfwords(data, 4):
        target = bl_target(data, off)
        if target not in (ROM_MEMCLR, ROM_MEMCPY):
            continue
        args = _constant_args(data, md, off, (0, 1) if target == ROM_MEMCLR else (0, 2))
        (resolved.append((off, target, *args)) if args else unresolved.append(off))
    app = [r for r in resolved if APP_RAM[0] <= r[2] < APP_RAM[1]]
    return {"calls": len(resolved) + len(unresolved), "resolved": resolved,
            "unresolved_sites": unresolved, "app_ram_resolved": app,
            "max_app_ram_end": max(dst + n for _, _, dst, n in app)}


def base_offsets(data: bytes, value: int, window: int = 12) -> dict:
    """Offsets addressed through each PC-literal load of value, until the
    register is overwritten. Escapes (the base passed on or moved) are listed."""
    _pinned(data)
    capstone, arm = _capstone()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    md.detail = True
    offsets, escapes = set(), []
    for off in _halfwords(data, 2):
        h = struct.unpack_from("<H", data, off)[0]
        if (h & 0xF800) != 0x4800:
            continue
        src = ((off + 4) & ~3) + (h & 0xFF) * 4
        if src + 4 > len(data) or struct.unpack_from("<I", data, src)[0] != value:
            continue
        base = arm.ARM_REG_R0 + ((h >> 8) & 7)
        for ins in list(md.disasm(data[off + 2:off + 2 + 2 * window], off + 2))[:window]:
            mems = [o.mem for o in ins.operands if o.type == arm.ARM_OP_MEM]
            if mems and mems[0].base == base:
                offsets.add(mems[0].disp)
            elif base in ins.regs_access()[0] or ins.mnemonic.startswith("b"):
                escapes.append(ins.address)
            if base in ins.regs_access()[1] or ins.mnemonic.startswith(("b", "pop")):
                break
    return {"offsets": sorted(offsets), "escapes": escapes}


def top_buffer_reader_stores(data: bytes) -> list[str]:
    """Non-stack stores in the function reading the 0x20e708 buffer."""
    _pinned(data)
    capstone, arm = _capstone()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    lo, hi = TOP_BUFFER_READER
    return [f"{i.address:#x}: {i.mnemonic} {i.op_str}"
            for i in md.disasm(data[lo:hi], lo)
            if i.mnemonic.startswith(("str", "stm")) and "sp" not in i.op_str]


def ram_tiling(ram_config: bytes) -> dict:
    """Captured app/heap words tile exactly to the documented cache boundary."""
    cfg = fwcapacity.parse_ram_config(ram_config)
    heap_start = cfg["app_end_exclusive"]
    return {**cfg, "heap_start_if_after_app": heap_start,
            "heap_end_if_after_app": heap_start + cfg["data_heap_bytes"],
            "tiles_to_cache_boundary":
                heap_start + cfg["data_heap_bytes"] == CACHE_RAM_START,
            "heap_start_proven": False}


# RTL8762E Memory User Guide (Realtek, marked confidential; not stored here)
# section 3.1, Figure 3-1/Table 3-1: Data RAM [0x200000, 0x216000) in FIXED
# order. Only the first three sizes are fixed; upperstack/APP/heap adjust.
VENDOR_DATA_RAM = (0x200000, 0x216000)
VENDOR_FIXED_PARTS = (("rom_data", 12800), ("main_stack", 1536), ("patch_ram", 15360))
CAPTURED_PATCH_RAM = (0x203800, 0x203800 + 0x3510)   # declared, rom-create-hook capture
STOCK_STARTUP_SP = 0x203800                          # stock entry at file 0x48c


def documented_layout(ram_config: bytes) -> dict:
    """Vendor fixed-order layout, sized by the captured app/heap words, and
    its agreement with independent observations. Documentation, not a ring
    measurement of any owner."""
    cfg = fwcapacity.parse_ram_config(ram_config)
    parts, cursor = [], VENDOR_DATA_RAM[0]
    for name, size in VENDOR_FIXED_PARTS:
        parts.append((name, cursor, cursor + size))
        cursor += size
    parts.append(("upperstack", cursor, cfg["app_address"]))
    parts.append(("app_ram", cfg["app_address"], cfg["app_end_exclusive"]))
    heap = (cfg["app_end_exclusive"], cfg["app_end_exclusive"] + cfg["data_heap_bytes"])
    parts.append(("data_heap", *heap))
    span = {name: (lo, hi) for name, lo, hi in parts}
    patch = span["patch_ram"]
    return {"parts": parts,
            "upperstack_bytes": cfg["app_address"] - cursor,
            "main_stack_top_matches_startup_sp": span["main_stack"][1] == STOCK_STARTUP_SP,
            "captured_patch_inside_patch_ram": patch[0] <= CAPTURED_PATCH_RAM[0] and CAPTURED_PATCH_RAM[1] <= patch[1],
            "heap_ends_at_data_ram_end": heap[1] == VENDOR_DATA_RAM[1],
            "candidate_inside_app_ram": span["app_ram"][0] <= 0x20E738 and APP_RAM[1] <= span["app_ram"][1],
            "owners_measured": False}


def candidate_regions() -> dict:
    """Two candidate static regions; neither approved."""
    return {
        "aligned_gap": {"start": 0x20E800, "end_exclusive": APP_RAM[1],
                        "bytes": APP_RAM[1] - 0x20E800,
                        "requires": ["no ROM/patch/upper-stack owner in the app reservation",
                                     "heap begins at appDataAddr + appDataSize",
                                     "explicit per-boot initialization",
                                     "retention equal to adjacent stock BSS"]},
        "post_boot_overlay_and_gap": {"start": 0x20E738, "end_exclusive": APP_RAM[1],
                                      "bytes": APP_RAM[1] - 0x20E738,
                                      "requires": ["everything required by aligned_gap",
                                                   "unified initialization strictly after boot call 0x6a4",
                                                   "no post-boot overlay reload or execution path, "
                                                   "including ROM and DLPS exit"]},
        "approved_for_use": False,
    }


def plan_layout(objects: list[tuple[str, int]], region: str, align: int = 8) -> dict:
    """Pack named objects into one candidate region; refuses rather than truncates."""
    if align not in (4, 8) or any(size <= 0 for _, size in objects):
        raise ValueError("invalid layout request")
    r = candidate_regions()[region]
    cursor, placed = r["start"], []
    for name, size in objects:
        cursor = (cursor + align - 1) & ~(align - 1)
        placed.append({"name": name, "start": cursor, "end_exclusive": cursor + size})
        cursor += size
    return {"region": region, "objects": placed, "used_end": cursor,
            "fits": cursor <= r["end_exclusive"],
            "margin": r["end_exclusive"] - cursor, "approved": False}


def receipt_on_stack_bytes() -> int:
    """Receipt + observed nested path + one PSP exception frame (tasks on PSP).

    Nested interrupts run on MSP under the standard ARMv6-M FreeRTOS port; that
    port choice in the ring ROM is NOT verified here. Outer callers excluded.
    """
    return (RECEIPT_BYTES + OBSERVE_NESTED_STACK
            + ARMV6M_EXCEPTION_FRAME + ARMV6M_FRAME_ALIGN_PAD)


def audit_ram_ownership(data: bytes, ram_config: bytes) -> dict:
    _pinned(data)
    overlay = overlay_entry_evidence(data)
    bulk = bulk_extents(data)
    return {
        "last_static_end": LAST_STATIC_END,
        "gap_literals": literal_references(data, OVERLAY_RAM[1], APP_RAM[1]),
        "overlay": overlay,
        "bulk": {k: bulk[k] for k in ("calls", "max_app_ram_end")}
                | {"resolved": len(bulk["resolved"]),
                   "unresolved": len(bulk["unresolved_sites"])},
        "top_buffer_reader_stores": top_buffer_reader_stores(data),
        "tiling": ram_tiling(ram_config),
        "regions": candidate_regions(),
        "allocation_approved": False,
        "unresolved": ["ROM, ROM-patch and upper-stack RAM writers",
                       "live heap base and peak use",
                       "DLPS/power-down retention of the region",
                       "dynamic-index writes from lower stock objects",
                       "task stack headroom and PSP/MSP port choice"],
    }


# --- Future bounded read plan: NOT authorized or executed -------------------
# ROM-data heap bookkeeping names from the pinned SDK symbol file. Each symbol
# is 8 bytes apart, read as two u32 words (assumed data-ON, buffer-ON heaps).
HEAP_WINDOW = (0x2014D8, 60)            # through app_cb_wdg_reset (exclusive)
HEAP_NAMED = {"free": 0x2014D8, "minimum_ever_free": 0x2014E0,
              "total": 0x2014E8, "start_list": 0x2014F0}
HEAP_BASE_WINDOW = (0x20EC00, 8)        # first presumed block header only; no gap bytes
GAP_WINDOW_V2 = (0x20E7DC, 0x20EC00 - 0x20E7DC)  # V2 overlay end .. reservation end
GAP_BLOCK = 16


def decode_heap_window(raw: bytes) -> dict:
    """Named heap counters; the unnamed tail is returned raw for review."""
    if len(raw) != HEAP_WINDOW[1]:
        raise ValueError("heap window must be exactly 60 bytes")
    base = HEAP_WINDOW[0]
    word = lambda a, i=0: struct.unpack_from("<I", raw, a - base + 4 * i)[0]
    free, low, total = ([word(HEAP_NAMED[k], i) for i in (0, 1)]
                        for k in ("free", "minimum_ever_free", "total"))
    sane = all(lo <= fr <= tot for lo, fr, tot in zip(low, free, total))
    return {"free": free, "minimum_ever_free": low, "total": total,
            "start_list_words": [word(HEAP_NAMED["start_list"], i) for i in range(4)],
            "unnamed_tail_words": [word(0x201500, i) for i in range(5)],
            "counters_consistent": sane,
            "data_heap_peak_used": total[0] - low[0] if sane else None,
            "data_total_within_config": sane and total[0] <= 0x7400}


def heap_base_signature(raw: bytes) -> dict:
    """FreeRTOS-style allocated header at 0x20ec00: next NULL, size with top bit.

    The Realtek os_mem header format is an ASSUMPTION; a mismatch is
    inconclusive, not evidence of a lower heap base."""
    if len(raw) != HEAP_BASE_WINDOW[1]:
        raise ValueError("heap base window must be exactly 8 bytes")
    nxt, size = struct.unpack_from("<II", raw)
    block = size & 0x7FFFFFFF
    allocated = bool(size & 0x80000000) and nxt == 0 and 0 < block <= 0x7400 and block % 8 == 0
    return {"header_next": nxt, "header_size_word": size,
            "allocated_header_shape": allocated,
            "verdict": "consistent with heap base 0x20ec00" if allocated else "inconclusive"}


def gap_digest(raw: bytes) -> list[dict]:
    """Host-side reduction: per-block hash and zero flag; raw bytes discarded."""
    import hashlib
    if len(raw) != GAP_WINDOW_V2[1]:
        raise ValueError("gap window length mismatch")
    return [{"offset": i, "sha256": hashlib.sha256(raw[i:i + GAP_BLOCK]).hexdigest(),
             "all_zero": not any(raw[i:i + GAP_BLOCK])}
            for i in range(0, len(raw), GAP_BLOCK)]


def compare_gap_digests(first: list[dict], second: list[dict]) -> dict:
    """A change proves a writer; no change is only absence of evidence."""
    if [b["offset"] for b in first] != [b["offset"] for b in second]:
        raise ValueError("digest layouts differ")
    changed = [a["offset"] for a, b in zip(first, second) if a["sha256"] != b["sha256"]]
    return {"changed_block_offsets": changed,
            "writer_proven": bool(changed),
            "unused_proven": False,
            "zero_blocks": sum(b["all_zero"] for b in second)}


def read_plan() -> dict:
    return {"authorized": False, "executed": False, "image": "installed V2 (map differs from stock)",
            "windows": [{"address": HEAP_WINDOW[0], "bytes": HEAP_WINDOW[1], "reads": 2, "store": "raw"},
                        {"address": HEAP_BASE_WINDOW[0], "bytes": HEAP_BASE_WINDOW[1], "reads": 2, "store": "raw"},
                        {"address": GAP_WINDOW_V2[0], "bytes": GAP_WINDOW_V2[1], "reads": 2,
                         "store": "per-16-byte SHA-256 + zero flag only", "min_interval_s": 60}],
            "never": ["pointer following", "OTP/key fields", "MMIO/FIFO", "writes", "sensor/flash commands",
                      "automatic retry"],
            "cannot_establish": ["pre_main single execution per reset", "DLPS retention",
                                 "stock-Health heap peak (V2 has optics off)"]}


# --- ROM reset branch, from previously captured ROM bytes (no execution) ----
ROM_INTEGRATION_SHA256 = "d02cc3582a789d933e1be09fa1bbec05ade7a193508418149f145dc12df3b05b"
ROM_WINDOW = (0x4A78, 2348)             # captured 2026-09-23, read twice equal
ROM_RESET_HANDLER = 0x4EFE              # vector 1 = 0x4eff, observed 2026-09-24
ROM_RESUME_BRANCH = 0x4EE6              # taken when AON reason bit 1 is set
ROM_RESUME_POINTER = 0x2000F8           # [0x2000f4 + 4]; runtime value unread
ROM_FIRST_BOOT = 0x4E36


def rom_window(archive: bytes) -> bytes:
    import hashlib
    import json
    if hashlib.sha256(archive).hexdigest() != ROM_INTEGRATION_SHA256:
        raise ValueError("unreviewed ROM integration archive")
    found = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("address") == ROM_WINDOW[0] and "data_hex" in o:
                found.append(bytes.fromhex(o["data_hex"]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(archive))
    if not found or any(len(f) != ROM_WINDOW[1] or f != found[0] for f in found):
        raise ValueError("captured ROM window missing or inconsistent")
    return found[0]


def reset_branch_evidence(rom: bytes) -> dict:
    """Decode the reset handler's first decision from captured bytes only."""
    capstone, arm = _capstone()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    base = ROM_WINDOW[0]

    def ins(lo, hi):
        return [(i.address, i.mnemonic, i.op_str) for i in md.disasm(rom[lo - base:hi - base], lo)]

    def literal(at):
        return struct.unpack_from("<I", rom, at - base)[0]
    handler = ins(ROM_RESET_HANDLER, ROM_RESET_HANDLER + 0x18)
    resume = ins(ROM_RESUME_BRANCH, ROM_RESET_HANDLER)
    first = ins(ROM_FIRST_BOOT, ROM_RESUME_BRANCH)
    return {
        "reads_aon_reason_word_0": handler[1][1:] == ("movs", "r0, #0") and handler[2][2] == "#0x32f60",
        "tests_bit1_then_resume_branch": [h[1:] for h in handler[5:8]] ==
            [("lsls", "r0, r0, #0x1e"), ("lsrs", "r0, r0, #0x1f"), ("bl", f"#{ROM_RESUME_BRANCH:#x}")],
        "resume_jumps_via_saved_pointer": [r[1] for r in resume] ==
            ["push", "cmp", "beq", "bl", "bl", "cpsid", "ldr", "ldr", "blx", "pop"]
            and literal(0x4F58) == ROM_RESUME_POINTER - 4 and resume[7][2] == "r0, [r0, #4]",
        "first_boot_loads_patch_image_then_hook": any(i[2] == "#0x4b60" for i in first)
            and literal(0x4F3C) == 0x2792 and literal(0x4F68) == 0x2000F0,
        "app_hook_literals_in_window": [v for v in (APP_PRE_MAIN_SLOT, 0x2011D8)
                                        if struct.pack("<I", v) in rom],
        "resume_target_read": False,
        "app_pre_main_caller_located": False,
    }


RESUME_CODE_ARCHIVE_SHA256 = "fbff5caa62754c03b7d7bdda0f0da11378baddca43e3337bbdf6651690d26851"
RESUME_CODE_WINDOW = (0xD200, 512)
ROM_RESUME_TARGET = 0xD22C              # runtime [0x2000f8] = 0xd22d, read 2026-09-25
ROM_RETURN_IDLE_TASK = 0x135B8          # symbol os_task_dlps_return_idle_task (0x135b9)


def resume_routine_evidence(archive: bytes) -> dict:
    """Structure of the DLPS resume target from its captured bytes only."""
    import hashlib
    import json
    if hashlib.sha256(archive).hexdigest() != RESUME_CODE_ARCHIVE_SHA256:
        raise ValueError("unreviewed resume-code archive")
    code = bytes.fromhex(json.loads(archive)["resume_code"]["data_hex"])
    if len(code) != RESUME_CODE_WINDOW[1]:
        raise ValueError("resume-code window size mismatch")
    capstone, _ = _capstone()
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    lo = ROM_RESUME_TARGET - RESUME_CODE_WINDOW[0]
    body = [(i.mnemonic, i.op_str) for i in md.disasm(code[lo:lo + 0x18], ROM_RESUME_TARGET)]
    return {
        "shape": [m for m, _ in body],
        "calls": [op for m, op in body if m in ("bl", "blx")],
        "ends_in_return_idle_task": ("bl", f"#{ROM_RETURN_IDLE_TASK:#x}") in body
                                    and body[-1] == ("pop", "{r4, pc}"),
        "app_hook_literals_in_window": [v for v in (APP_PRE_MAIN_SLOT, 0x2011D8)
                                        if struct.pack("<I", v) in code],
        "unread_callees": ["0xd0b8", "indirect callback [[0xd478]-0x10+8]", "os_task_dlps_return_idle_task"],
        "exhaustive": False,
    }
