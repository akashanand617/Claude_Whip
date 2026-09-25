"""Fixed RAM-ownership diagnostic reads on the installed V2 image. No flash.

User-authorized 2026-09-24 ("ring connect, as long as we aren't flashing").
The whole existing prerequisite chain runs first: V2 fingerprint, CD path code,
idle flag, exact prior config and bank0 descriptor, and the ROM identifier.
Only then do four fixed windows open. The gap window is reduced to per-block
hashes before anything is stored or logged. No pointer following, sensor or
flash command, write API, retry or reconnect. CD01 bookkeeping effects remain.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import struct

from whip import fwcapacity, fwcapacity_read as cr, fwram, fwrom_read as rr

SCHEMA = "whip.ram-ownership.capture.v1"
PRE_MAIN_SLOT_WINDOW = (fwram.APP_PRE_MAIN_SLOT, 4)
EXPECTED_PRE_MAIN = 0x826613            # installed by 25 Hz, V2 and stock at file 0x6c6
WINDOWS = {"pre_main_slot": PRE_MAIN_SLOT_WINDOW, "heap": fwram.HEAP_WINDOW,
           "heap_base": fwram.HEAP_BASE_WINDOW, "gap": fwram.GAP_WINDOW_V2}
GAP_INTERVAL_S = 60.0
PREREQUISITE_TRANSACTIONS = 91 + 2 * len(cr.chunks(*rr.UUID_WINDOW))
PLAN_TRANSACTIONS = 2 * sum(len(cr.chunks(*w)) for w in WINDOWS.values())
POSTCHECK_TRANSACTIONS = sum(len(cr.chunks(*w)) for w in cr.CONFIG_WINDOWS) + 1
EXPECTED_TRANSACTIONS = PREREQUISITE_TRANSACTIONS + PLAN_TRANSACTIONS + POSTCHECK_TRANSACTIONS


def _in(window, address):
    return window[0] <= address < window[0] + window[1]


def _redact(emit, windows=(fwram.GAP_WINDOW_V2,)):
    """Reply packets in hash-only windows are logged as hash + zero flag, never as bytes."""
    def wrapped(item):
        if item.get("kind") == "reply" and any(_in(w, item["address"]) for w in windows):
            raw = bytes.fromhex(item["packet"])
            item = {**item, "packet": None, "packet_sha256": hashlib.sha256(raw).hexdigest(),
                    "payload_all_zero": not any(raw[1:1 + item["length"]]), "redacted": True}
        emit(item)
    return wrapped


class RAMOwnershipReader(cr.DescriptorReader):
    """One-use plan; every RAM window is closed until its phase is entered."""
    windows = WINDOWS
    hash_only = (fwram.GAP_WINDOW_V2,)

    def __init__(self, client, emit, **kwargs):
        super().__init__(client, _redact(emit, self.hash_only), **kwargs)
        self._phase = None
        self._started = False
        self.closed = False

    def _allowed_reads(self):
        if self.closed:
            return frozenset()
        allowed = super()._allowed_reads()
        if self._phase == "identifier":
            allowed |= frozenset(cr.chunks(*rr.UUID_WINDOW))
        elif self._phase in self.windows:
            allowed |= frozenset(cr.chunks(*self.windows[self._phase]))
        return allowed

    async def phase_window(self, phase):
        self._phase = phase
        try:
            return await self.window(*self.windows[phase])
        finally:
            self._phase = None


def _raw(address, data):
    return {"address": address, "data_hex": data.hex(), "sha256": hashlib.sha256(data).hexdigest()}


async def _prerequisites(reader, base, candidate, symbols, session_id):
    """Unchanged reviewed chain, then the ROM identifier twice."""
    rr.validate_references(base, candidate, symbols)
    config = await cr.collect_bank0_descriptor(reader, base, candidate, session_id)
    descriptor = next(w for w in config["windows"] if w["address"] == cr.BANK0_DESCRIPTOR_WINDOW[0])
    if hashlib.sha256(bytes.fromhex(descriptor["data_hex"])).hexdigest() != rr.DESCRIPTOR_SHA256:
        raise RuntimeError("bank0 differs from reviewed descriptor; no RAM read")
    reader._phase = "identifier"
    for _ in range(2):
        if await reader.window(*rr.UUID_WINDOW) != rr.ROM_UUID:
            raise RuntimeError("ROM identifier differs; ROM-data symbols do not apply")
    reader._phase = None
    return config


async def _postcheck(reader):
    for address, length in cr.CONFIG_WINDOWS:
        expected = (cr.EXPECTED_RAM_CONFIG if address == fwcapacity.RAM_CONFIG_ADDRESS
                    else cr.EXPECTED_FLASH_CONFIG)
        if await reader.window(address, length) != expected:
            raise RuntimeError("configuration changed during RAM diagnostic")
    if await reader.read(*cr.IDLE_WINDOW) != b"\0":
        raise RuntimeError("raw mode changed during RAM diagnostic")


async def collect(reader: RAMOwnershipReader, base: bytes, candidate: bytes, symbols: bytes,
                  session_id: str, *, interval_s: float = GAP_INTERVAL_S, sleep=asyncio.sleep):
    if not isinstance(reader, RAMOwnershipReader):
        raise ValueError("separate RAM ownership reader required")
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)

        first = {name: await reader.phase_window(name) for name in WINDOWS}
        slot = struct.unpack("<I", first["pre_main_slot"])[0]
        first_gap = fwram.gap_digest(first.pop("gap"))
        await sleep(interval_s)
        second = {name: await reader.phase_window(name) for name in reversed(tuple(WINDOWS))}
        second_gap = fwram.gap_digest(second.pop("gap"))

        await _postcheck(reader)

        result = {
            "schema": SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
            "prerequisite_capture": config, "symbols_sha256": rr.SYMBOLS_SHA256,
            "pre_main_slot": [_raw(PRE_MAIN_SLOT_WINDOW[0], first["pre_main_slot"]),
                              _raw(PRE_MAIN_SLOT_WINDOW[0], second["pre_main_slot"])],
            "pre_main_slot_matches_image": slot == EXPECTED_PRE_MAIN
                                           and first["pre_main_slot"] == second["pre_main_slot"],
            "heap_window": [_raw(fwram.HEAP_WINDOW[0], first["heap"]),
                            _raw(fwram.HEAP_WINDOW[0], second["heap"])],
            "heap_decoded": [fwram.decode_heap_window(first["heap"]),
                             fwram.decode_heap_window(second["heap"])],
            "heap_base_window": [_raw(fwram.HEAP_BASE_WINDOW[0], first["heap_base"]),
                                 _raw(fwram.HEAP_BASE_WINDOW[0], second["heap_base"])],
            "heap_base_signature": [fwram.heap_base_signature(first["heap_base"]),
                                    fwram.heap_base_signature(second["heap_base"])],
            "gap": {"address": fwram.GAP_WINDOW_V2[0], "bytes": fwram.GAP_WINDOW_V2[1],
                    "interval_s": interval_s, "first": first_gap, "second": second_gap,
                    "comparison": fwram.compare_gap_digests(first_gap, second_gap),
                    "raw_stored": False},
            "pointer_following": False, "flash_authorized": False,
            "allocation_approved": False, "image": "installed V2; stock map differs",
        }
        reader.emit({"kind": "ram_ownership", "gap_writer_proven": result["gap"]["comparison"]["writer_proven"],
                     "pre_main_slot_matches_image": result["pre_main_slot_matches_image"],
                     "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- Follow-up plan: retention/no-writer across disconnect + ROM vectors -----
# The prior capture's gap digests are the baseline; between sessions the ring
# sat disconnected and idle. ROM 0x0..0x40 is the Cortex-M vector table: it is
# recorded raw and NEVER followed in this session (reset-handler code needs a
# separately fixed window chosen offline).
FOLLOWUP_SCHEMA = "whip.ram-ownership-followup.capture.v1"
PRIOR_CAPTURE_SHA256 = "bb16aaecd2c2ae30cb110521b3f754c4bb44b2065dbb00cf27ca86ecaca65473"
ROM_VECTOR_WINDOW = (0x0, 64)
FOLLOWUP_WINDOWS = {"rom_vectors": ROM_VECTOR_WINDOW, "heap": fwram.HEAP_WINDOW,
                    "gap": fwram.GAP_WINDOW_V2}
FOLLOWUP_TRANSACTIONS = (PREREQUISITE_TRANSACTIONS
                         + 2 * sum(len(cr.chunks(*w)) for w in FOLLOWUP_WINDOWS.values())
                         + POSTCHECK_TRANSACTIONS)


class RAMFollowupReader(RAMOwnershipReader):
    windows = FOLLOWUP_WINDOWS


def decode_vectors(raw: bytes) -> dict:
    """Recorded, not followed: initial SP and the first 15 exception vectors."""
    if len(raw) != ROM_VECTOR_WINDOW[1]:
        raise ValueError("vector window must be exactly 64 bytes")
    words = struct.unpack("<16I", raw)
    return {"initial_sp": words[0], "reset": words[1], "nmi": words[2], "hardfault": words[3],
            "svcall": words[11], "pendsv": words[14], "systick": words[15],
            "reset_in_rom": words[1] & 1 == 1 and (words[1] & ~1) < 0x44000,
            "followed": False}


async def collect_followup(reader: RAMFollowupReader, base: bytes, candidate: bytes, symbols: bytes,
                           session_id: str, prior_capture: bytes):
    if not isinstance(reader, RAMFollowupReader):
        raise ValueError("separate follow-up reader required")
    if hashlib.sha256(prior_capture).hexdigest() != PRIOR_CAPTURE_SHA256:
        raise ValueError("unreviewed prior RAM capture")
    prior = json.loads(prior_capture)
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        reads = [{name: await reader.phase_window(name) for name in FOLLOWUP_WINDOWS} for _ in range(2)]
        gaps = [fwram.gap_digest(r.pop("gap")) for r in reads]
        await _postcheck(reader)
        baseline = prior["gap"]["second"]
        result = {
            "schema": FOLLOWUP_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
            "prerequisite_capture": config, "prior_capture_sha256": PRIOR_CAPTURE_SHA256,
            "rom_vectors": [_raw(ROM_VECTOR_WINDOW[0], r["rom_vectors"]) for r in reads],
            "rom_vectors_decoded": decode_vectors(reads[0]["rom_vectors"]),
            "rom_vectors_repeated_equal": reads[0]["rom_vectors"] == reads[1]["rom_vectors"],
            "heap_window": [_raw(fwram.HEAP_WINDOW[0], r["heap"]) for r in reads],
            "heap_decoded": [fwram.decode_heap_window(r["heap"]) for r in reads],
            "gap": {"address": fwram.GAP_WINDOW_V2[0], "bytes": fwram.GAP_WINDOW_V2[1],
                    "reads": gaps, "raw_stored": False,
                    "within_session": fwram.compare_gap_digests(gaps[0], gaps[1]),
                    "versus_prior_session": fwram.compare_gap_digests(baseline, gaps[0])},
            "pointer_following": False, "flash_authorized": False,
            "allocation_approved": False, "image": "installed V2; stock map differs",
        }
        reader.emit({"kind": "ram_ownership_followup",
                     "gap_changed_since_prior": result["gap"]["versus_prior_session"]["writer_proven"],
                     "rom_vectors_repeated_equal": result["rom_vectors_repeated_equal"],
                     "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- Resume-pointer plan: ROM-data function pointers, recorded, never followed ---
RESUME_SCHEMA = "whip.ram-ownership-resume-pointers.capture.v1"
BOOT_HOOK_WINDOW = (0x2000F0, 16)       # [0x2000f0] first-boot hook, [0x2000f8] resume
PRE_BOOT_HOOK_WINDOW = (0x20014C, 4)    # called early on first boot (0x4fa2)
RESUME_WINDOWS = {"boot_hooks": BOOT_HOOK_WINDOW, "pre_boot_hook": PRE_BOOT_HOOK_WINDOW}
RESUME_TRANSACTIONS = (PREREQUISITE_TRANSACTIONS
                       + 2 * sum(len(cr.chunks(*w)) for w in RESUME_WINDOWS.values())
                       + POSTCHECK_TRANSACTIONS)


class RAMResumeReader(RAMOwnershipReader):
    windows = RESUME_WINDOWS


def decode_resume_pointers(boot_hooks: bytes, pre_boot: bytes) -> dict:
    if len(boot_hooks) != 16 or len(pre_boot) != 4:
        raise ValueError("resume pointer windows have fixed sizes")
    w = struct.unpack("<4I", boot_hooks)
    return {"first_boot_hook_0x2000f0": w[0], "word_0x2000f4": w[1],
            "resume_pointer_0x2000f8": w[2], "word_0x2000fc": w[3],
            "pre_boot_hook_0x20014c": struct.unpack("<I", pre_boot)[0], "followed": False}


async def collect_resume_pointers(reader: RAMResumeReader, base: bytes, candidate: bytes,
                                  symbols: bytes, session_id: str):
    if not isinstance(reader, RAMResumeReader):
        raise ValueError("separate resume-pointer reader required")
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        reads = [{name: await reader.phase_window(name) for name in RESUME_WINDOWS} for _ in range(2)]
        await _postcheck(reader)
        result = {
            "schema": RESUME_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
            "prerequisite_capture": config,
            "windows": {name: [_raw(RESUME_WINDOWS[name][0], r[name]) for r in reads]
                        for name in RESUME_WINDOWS},
            "repeated_equal": reads[0] == reads[1],
            "decoded": decode_resume_pointers(reads[0]["boot_hooks"], reads[0]["pre_boot_hook"]),
            "pointer_following": False, "target_execution": False, "flash_authorized": False,
        }
        reader.emit({"kind": "resume_pointers", "repeated_equal": result["repeated_equal"],
                     "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- Resume-code plan: fixed ROM window chosen OFFLINE from the archived pointer ---
RESUME_CODE_SCHEMA = "whip.ram-ownership-resume-code.capture.v1"
RESUME_POINTER_ARCHIVE_SHA256 = "7f5190fd069874aa4869d629f36a060f4eb05799a7937074ff3154d6f5db8a02"
RESUME_POINTER_WINDOW = (0x2000F8, 4)
EXPECTED_RESUME_POINTER = 0xD22D
RESUME_CODE_WINDOW = (0xD200, 512)     # power_manager_resume_all 0xd210 and target 0xd22c
RESUME_CODE_WINDOWS = {"resume_pointer": RESUME_POINTER_WINDOW, "resume_code": RESUME_CODE_WINDOW}
RESUME_CODE_TRANSACTIONS = (PREREQUISITE_TRANSACTIONS
                            + 2 * sum(len(cr.chunks(*w)) for w in RESUME_CODE_WINDOWS.values())
                            + POSTCHECK_TRANSACTIONS)


class RAMResumeCodeReader(RAMOwnershipReader):
    windows = RESUME_CODE_WINDOWS


async def collect_resume_code(reader: RAMResumeCodeReader, base: bytes, candidate: bytes,
                              symbols: bytes, session_id: str, pointer_archive: bytes):
    if not isinstance(reader, RAMResumeCodeReader):
        raise ValueError("separate resume-code reader required")
    if hashlib.sha256(pointer_archive).hexdigest() != RESUME_POINTER_ARCHIVE_SHA256:
        raise ValueError("unreviewed resume-pointer archive")
    if json.loads(pointer_archive)["decoded"]["resume_pointer_0x2000f8"] != EXPECTED_RESUME_POINTER:
        raise ValueError("archive does not name the reviewed resume target")
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        for _ in range(2):
            if struct.unpack("<I", await reader.phase_window("resume_pointer"))[0] != EXPECTED_RESUME_POINTER:
                raise RuntimeError("resume pointer changed; no ROM code read")
        first = await reader.phase_window("resume_code")
        second = await reader.phase_window("resume_code")
        if first != second:
            raise RuntimeError("ROM code differs across repeated reads")
        await _postcheck(reader)
        result = {
            "schema": RESUME_CODE_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
            "prerequisite_capture": config, "pointer_archive_sha256": RESUME_POINTER_ARCHIVE_SHA256,
            "resume_pointer": EXPECTED_RESUME_POINTER, "resume_code": _raw(RESUME_CODE_WINDOW[0], first),
            "repeated_equal": True, "pointer_following": False, "target_execution": False,
            "flash_authorized": False,
        }
        reader.emit({"kind": "resume_code", "bytes": len(first), "repeated_equal": True,
                     "pointer_following": False, "target_execution": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- Stack plan stage 1: MSP paint watermark (hash-only) + task handle list ---
STACKS_SCHEMA = "whip.ram-ownership-stacks.capture.v1"
CURRENT_TCB_WINDOW = (0x201340, 4)      # ROM symbol pxCurrentTCB
TASK_HANDLES_WINDOW = (0x201374, 256)   # ROM symbol pTaskHandleList .. uxTimerCreateCount
MSP_PAINT_WINDOW = (0x203200, 0x180)    # painted 0xa5a5a5a5 by ROM reset 0x4f12..0x4f24
MSP_TOP = 0x203800
PAINT_WORD = 0xA5A5A5A5
STACKS_WINDOWS = {"current_tcb": CURRENT_TCB_WINDOW, "task_handles": TASK_HANDLES_WINDOW,
                  "msp_paint": MSP_PAINT_WINDOW}
STACKS_TRANSACTIONS = (PREREQUISITE_TRANSACTIONS
                       + 2 * sum(len(cr.chunks(*w)) for w in STACKS_WINDOWS.values())
                       + POSTCHECK_TRANSACTIONS)


class RAMStacksReader(RAMOwnershipReader):
    windows = STACKS_WINDOWS
    hash_only = (MSP_PAINT_WINDOW,)


def paint_profile(raw: bytes) -> dict:
    """Which painted words survive; raw stack contents are not returned."""
    if len(raw) != MSP_PAINT_WINDOW[1]:
        raise ValueError("MSP paint window size mismatch")
    words = struct.unpack(f"<{len(raw) // 4}I", raw)
    intact = [w == PAINT_WORD for w in words]
    untouched = next((i for i, ok in enumerate(intact) if not ok), len(intact))
    lowest_touched = MSP_PAINT_WINDOW[0] + 4 * untouched
    return {"intact": intact, "intact_words": sum(intact),
            "untouched_bottom_bytes": 4 * untouched,
            "max_depth_bound_bytes": MSP_TOP - lowest_touched,
            "all_paint_intact": all(intact),
            "block_sha256": [hashlib.sha256(raw[i:i + 16]).hexdigest() for i in range(0, len(raw), 16)]}


async def collect_stacks(reader: RAMStacksReader, base: bytes, candidate: bytes, symbols: bytes,
                         session_id: str):
    if not isinstance(reader, RAMStacksReader):
        raise ValueError("separate stacks reader required")
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        reads = [{name: await reader.phase_window(name) for name in STACKS_WINDOWS} for _ in range(2)]
        paints = [paint_profile(r.pop("msp_paint")) for r in reads]
        await _postcheck(reader)
        handles = struct.unpack("<64I", reads[0]["task_handles"])
        result = {
            "schema": STACKS_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
            "prerequisite_capture": config,
            "current_tcb": [_raw(CURRENT_TCB_WINDOW[0], r["current_tcb"]) for r in reads],
            "task_handles": [_raw(TASK_HANDLES_WINDOW[0], r["task_handles"]) for r in reads],
            "task_handles_repeated_equal": reads[0]["task_handles"] == reads[1]["task_handles"],
            "nonzero_handles": [h for h in handles if h],
            "msp_paint": paints, "msp_raw_stored": False,
            "pointer_following": False, "flash_authorized": False,
        }
        reader.emit({"kind": "stacks", "msp_all_paint_intact": paints[1]["all_paint_intact"],
                     "handles": len(result["nonzero_handles"]), "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- Stack plan stage 2: handle table + TCB headers, addresses chosen OFFLINE ---
TCB_SCHEMA = "whip.ram-ownership-tcbs.capture.v1"
STACKS_ARCHIVE_SHA256 = "9cc0038e7bd1233898acfad16f613ec7d20a5c14a37794716b4249c6b4b9ed9f"
HANDLE_TABLE_WINDOW = (0x2117A0, 128)   # value of ROM pTaskHandleList, read 2026-09-25
TCB_CANDIDATES = (0x212CB0, 0x213768, 0x214730, 0x2152F0, 0x215758, 0x215BC0)  # list items - 4
TCB_HEADER_BYTES = 72
TCB_WINDOWS = {"handle_table": HANDLE_TABLE_WINDOW,
               **{f"tcb_{a:06x}": (a, TCB_HEADER_BYTES) for a in TCB_CANDIDATES}}
TCB_TRANSACTIONS = (PREREQUISITE_TRANSACTIONS
                    + 2 * sum(len(cr.chunks(*w)) for w in TCB_WINDOWS.values())
                    + POSTCHECK_TRANSACTIONS)


class RAMTCBReader(RAMOwnershipReader):
    windows = TCB_WINDOWS
    hash_only = ()


def tcb_candidates_from_lists(stacks_archive: bytes) -> list[int]:
    """Re-derive the offline candidate set from the archived kernel lists."""
    if hashlib.sha256(stacks_archive).hexdigest() != STACKS_ARCHIVE_SHA256:
        raise ValueError("unreviewed stacks archive")
    found = set()
    for read in json.loads(stacks_archive)["task_handles"]:
        w = struct.unpack("<64I", bytes.fromhex(read["data_hex"]))
        for i in range(60):
            a = TASK_HANDLES_WINDOW[0] + 4 * i
            count, _, marker, first, last = w[i:i + 5]
            if marker == 0xFFFFFFFF and count and 0 < count < 16 and first != a + 8:
                found.update((first - 4, last - 4))
    return sorted(found)


async def collect_tcbs(reader: RAMTCBReader, base: bytes, candidate: bytes, symbols: bytes,
                       session_id: str, stacks_archive: bytes):
    if not isinstance(reader, RAMTCBReader):
        raise ValueError("separate TCB reader required")
    if tuple(tcb_candidates_from_lists(stacks_archive)) != TCB_CANDIDATES:
        raise ValueError("TCB candidates differ from reviewed offline derivation")
    if json.loads(stacks_archive)["task_handles"][0]["data_hex"][:8] != struct.pack("<I", HANDLE_TABLE_WINDOW[0]).hex():
        raise ValueError("handle-table pointer differs from archive")
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        reads = [{name: await reader.phase_window(name) for name in TCB_WINDOWS} for _ in range(2)]
        await _postcheck(reader)
        result = {
            "schema": TCB_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
            "prerequisite_capture": config, "stacks_archive_sha256": STACKS_ARCHIVE_SHA256,
            "windows": {n: [_raw(TCB_WINDOWS[n][0], r[n]) for r in reads] for n in TCB_WINDOWS},
            "repeated_equal": {n: reads[0][n] == reads[1][n] for n in TCB_WINDOWS},
            "pointer_following": False, "flash_authorized": False,
        }
        reader.emit({"kind": "tcbs", "windows": len(TCB_WINDOWS), "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- Stack plan stage 3: stack-bottom paint watermarks, windows chosen OFFLINE ---
WATERMARK_SCHEMA = "whip.ram-ownership-stack-watermarks.capture.v1"
TCB_ARCHIVE_SHA256 = "45f5f16b8f13da5f3f3e3907a0abe2bcb4b61604eb8001f8e24f438c8439557e"
# name -> (pxStack, bytes read from the stack BASE upward); derived and rechecked
# from the TCB archive by stack_windows_from_tcbs(). Raw stack bytes are hash-only.
STACK_READS = {"app": 1024, "Tmr Svc": 1024, "hub": 1024, "qc_app": 1024,
               "IDLE": 256, "UpperStac": 512}


def tcb_table(tcb_archive: bytes) -> dict:
    if hashlib.sha256(tcb_archive).hexdigest() != TCB_ARCHIVE_SHA256:
        raise ValueError("unreviewed TCB archive")
    out = {}
    for name, reads in json.loads(tcb_archive)["windows"].items():
        if not name.startswith("tcb_"):
            continue
        raw = bytes.fromhex(reads[0]["data_hex"])
        tcb = reads[0]["address"]
        top, stack = struct.unpack_from("<I", raw, 0)[0], struct.unpack_from("<I", raw, 48)[0]
        task = raw[52:68].split(b"\0")[0].decode("ascii")
        size = tcb - 8 - stack                       # heap header between stack and TCB
        if not (stack < top < tcb and 0 < size <= 0x1000 and size % 8 == 0):
            raise ValueError(f"implausible TCB layout for {task}")
        out[task] = {"tcb": tcb, "pxStack": stack, "stack_bytes": size,
                     "priority": struct.unpack_from("<I", raw, 44)[0]}
    return out


def stack_windows_from_tcbs(tcb_archive: bytes) -> dict:
    table = tcb_table(tcb_archive)
    windows = {}
    for task, length in STACK_READS.items():
        t = table[task]
        if length > t["stack_bytes"]:
            raise ValueError("read window exceeds the task stack")
        windows[f"stack_{task.replace(' ', '_')}"] = (t["pxStack"], length)
    return windows


class RAMWatermarkReader(RAMOwnershipReader):
    def __init__(self, client, emit, windows, **kwargs):
        self.windows = dict(windows)
        self.hash_only = tuple(windows.values())
        super().__init__(client, emit, **kwargs)


def watermark_transactions(windows) -> int:
    return (PREREQUISITE_TRANSACTIONS + sum(len(cr.chunks(*w)) for w in windows.values())
            + POSTCHECK_TRANSACTIONS)


def stack_profile(raw: bytes, stack_bytes: int) -> dict:
    words = struct.unpack(f"<{len(raw) // 4}I", raw)
    untouched = next((i for i, w in enumerate(words) if w != PAINT_WORD), len(words))
    return {"read_bytes": len(raw), "stack_bytes": stack_bytes,
            "untouched_bottom_bytes": 4 * untouched,
            "whole_read_painted": untouched == len(words),
            "painted_words": sum(w == PAINT_WORD for w in words),
            "headroom_lower_bound_bytes": 4 * untouched,
            "block_sha256": [hashlib.sha256(raw[i:i + 16]).hexdigest() for i in range(0, len(raw), 16)]}


async def collect_watermarks(reader: RAMWatermarkReader, base: bytes, candidate: bytes, symbols: bytes,
                             session_id: str, tcb_archive: bytes):
    windows = stack_windows_from_tcbs(tcb_archive)
    if not isinstance(reader, RAMWatermarkReader) or reader.windows != windows:
        raise ValueError("watermark reader must use the offline-derived windows")
    if reader._started or reader.closed:
        raise RuntimeError("RAM diagnostic session already used; no retry")
    reader._started = True
    table = tcb_table(tcb_archive)
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        profiles = {}
        for name in windows:
            task = next(t for t in STACK_READS if f"stack_{t.replace(' ', '_')}" == name)
            profiles[task] = stack_profile(await reader.phase_window(name), table[task]["stack_bytes"])
        await _postcheck(reader)
        result = {"schema": WATERMARK_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                  "prerequisite_capture": config, "tcb_archive_sha256": TCB_ARCHIVE_SHA256,
                  "tasks": table, "profiles": profiles, "raw_stored": False,
                  "pointer_following": False, "flash_authorized": False}
        reader.emit({"kind": "stack_watermarks", "tasks": len(profiles), "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True


# --- GATT registration resources: Upper Stack identity + config (read-only) ---
# Windows chosen offline from the pinned public SDK mirror's Upper Stack image
# (data_0x801000.bin, payload at 0x80e400) and the ring's bank0 descriptor
# (Upper Stack 0x80e000, 0x18000). Code bytes are compared, never executed.
GATT_SCHEMA = "whip.gatt-resources.capture.v1"
GATT_WINDOWS = {
    "upperstack_header": (0x80E000, 96),     # ic/flags/image id/length/ROM UUID/addresses
    "upperstack_hash_field": (0x80E174, 32), # same offset as the app header's payload SHA-256
    "upper_otp_config": (0x2002E4, 60),      # OTP "upper" block used by gatt_init/pool allocator
    "server_init_code": (0x828E5C, 100),     # mirror server_init + literal pool
    "service_pool_alloc_code": (0x818EF8, 104),  # mirror fixed-pool slot allocator + literals
    "server_state": (0x207974, 16),          # mirror: [+2] service count, [+8] server table
    "gatt_pool_state": (0x207810, 16),       # mirror: [+4] lower-GATT service-record pool
}
GATT_TRANSACTIONS = (PREREQUISITE_TRANSACTIONS
                     + 2 * sum(len(cr.chunks(*w)) for w in GATT_WINDOWS.values())
                     + POSTCHECK_TRANSACTIONS)


class GATTResourcesReader(RAMOwnershipReader):
    windows = GATT_WINDOWS
    hash_only = ()


async def collect_gatt(reader: GATTResourcesReader, base: bytes, candidate: bytes, symbols: bytes,
                       session_id: str):
    if not isinstance(reader, GATTResourcesReader):
        raise ValueError("separate GATT resources reader required")
    if reader._started or reader.closed:
        raise RuntimeError("diagnostic session already used; no retry")
    reader._started = True
    try:
        config = await _prerequisites(reader, base, candidate, symbols, session_id)
        reads = [{name: await reader.phase_window(name) for name in GATT_WINDOWS} for _ in range(2)]
        await _postcheck(reader)
        result = {"schema": GATT_SCHEMA, "evidence_kind": "device_capture", "session_id": session_id,
                  "prerequisite_capture": config,
                  "windows": {n: [_raw(GATT_WINDOWS[n][0], r[n]) for r in reads] for n in GATT_WINDOWS},
                  "repeated_equal": {n: reads[0][n] == reads[1][n] for n in GATT_WINDOWS},
                  "pointer_following": False, "target_execution": False, "flash_authorized": False}
        reader.emit({"kind": "gatt_resources", "windows": len(GATT_WINDOWS), "pointer_following": False})
        return result
    except BaseException:
        reader.poisoned = True
        raise
    finally:
        reader._phase = None
        reader._descriptor_phase = False
        reader.closed = True
