"""Bounded, conditional retirement records for an emulator, NEVER an image.

The scattered ELF is unowned research code. These records cover reviewed
entries, not arbitrary interior/ROM/retained roots. No stock file writer,
container constructor, BLE operation or production admission is provided.
"""
from dataclasses import dataclass
import hashlib
from io import BytesIO
import struct

from whip import fwraw_relocation_trial as layout
from whip.fwindicator import ENTRIES as INDICATORS, RETURN_ZERO, audit_indicators
from whip.fwoptical_io import _bl

BIAS = layout.BIAS
UART_SITE = 0x7B0A
UART_BEFORE = bytes.fromhex("fef78af8")
POLICY_SOURCE_SHA256 = "b144becce22476ef0ba553b52a1226325a5fd789434b1b5822416e329ce28e35"
# Independently verified post-checkpoint artifact, not geometry-only approval.
CANDIDATE_SHA256 = "9cad661e85edd74ebc9f425956aa1937da0dfa9f2f5344ddf20cf9d61109d432"
DENIED = frozenset((0xA1, 0xBF, 0xCE, 0xCD))
ENTRIES = (
    (0x1E4A, "raw_callback", "f0b589b0"),
    (0x2104, "raw_handler", "f0b589b0"),
    (0x48C6, "diagnostic_bf", "10b50446"),
    (0x4B02, "diagnostic_ce", "f0b58bb0"),
    (0x4C36, "diagnostic_cd", "1fb50021"),
    *INDICATORS,
)
# These include shared data, Health readers/tails, distinct startup/OTA code and
# the separate DFU callback. Raw-only 202a is inside the separately inspected
# raw-tail allowance; it is NOT a shared Health epilogue or a new stub site.
PRESERVED = (
    (0x1E42, 0x1E4A), (0x1F40, 0x1F70), (0x2348, 0x23A4),
    (0x3CA8, 0x3CAC), (0x3DE8, 0x3E48), (0x48E8, 0x4910),
    (0x4924, 0x4940), (0x4ADE, 0x4B02), (0x4CBC, 0x4CE0),
    (0x5C22, 0x5C32), (0x79B6, 0x7A0C), (0x80F8, 0x80FC),
    (0xC7D2, 0xC7D6), (0xCC32, 0xCCEE), (0xCD60, 0xCF3C),
    (0xEE50, 0xEF44), (0x1D9D8, 0x1DB14), (0x21A58, 0x21B20),
)


@dataclass(frozen=True)
class EmulatorEdit:
    file_offset: int
    before: bytes
    after: bytes
    purpose: str


@dataclass(frozen=True)
class RetirementPlan:
    stock_sha256: str
    elf_sha256: str
    policy_source_sha256: str
    policy_object_sha256: str
    policy_cases: int
    policy_digest: str
    edits: tuple[EmulatorEdit, ...]
    # These are deliberately not permission knobs accepted by the planner.
    flashable: bool = False
    reference_closure_verified: bool = False
    cold_boot_retention_verified: bool = False
    physical_shutdown_verified: bool = False
    health_continuity_verified: bool = False
    approved_reclaimed_bytes: int = 0


def _elf(raw):
    from elftools.elf.elffile import ELFFile
    return ELFFile(BytesIO(raw))


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _policy_witness(stock, raw, helper):
    """Execute exact helper + original gate; dispatch is a named boundary.

    This is a finite policy/ABI witness, not concurrency, pointer lifetime or
    whole-program verification. The caller must already inspect ELF geometry.
    Every packet read/write and every instruction is bounded independently.
    """
    import unicorn as u
    from unicorn import arm_const as a

    uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
    uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
    uc.mem_map(0x820000, 0x30000, u.UC_PROT_READ | u.UC_PROT_EXEC)
    uc.mem_map(0x200000, 0x30000, u.UC_PROT_READ | u.UC_PROT_WRITE)
    uc.mem_write(BIAS, stock)
    readable = []
    for segment in _elf(raw).iter_segments():
        if segment["p_type"] == "PT_LOAD":
            uc.mem_write(segment["p_vaddr"], segment.data())
            readable.append((segment["p_vaddr"], segment["p_vaddr"] + segment["p_memsz"]))
    entry, count = helper["address"], helper["bytes"]
    lo = entry & ~1
    mode, packet, stack, stop = 0x208C44, 0x220020, 0x22F000, 0x84FFF0
    state = {}

    def code(machine, address, size, _):
        if address == stop:
            state["returned"] = True
            machine.emu_stop()
        elif address == BIAS + 0x5882:
            state["dispatch"].append((machine.reg_read(a.UC_ARM_REG_R0),
                                      machine.reg_read(a.UC_ARM_REG_R1)))
            machine.reg_write(a.UC_ARM_REG_PC, machine.reg_read(a.UC_ARM_REG_LR))
        elif not (lo <= address < address + size <= lo + count or
                  BIAS + 0x5C22 <= address < address + size <= BIAS + 0x5C32):
            raise ValueError(f"legacy policy escaped reviewed code: {address:#x}")

    def read(machine, access, address, size, value, _):
        if address == packet and size == 1:
            state["packet_reads"] += 1
            return
        if ((address, size) in ((mode, 1), (BIAS + 0x601C, 4)) or
                stack - 128 <= address < address + size <= stack or
                any(start <= address < address + size <= end for start, end in readable)):
            return
        raise ValueError(f"legacy policy escaped reviewed data: {address:#x}/{size}")

    def write(machine, access, address, size, value, _):
        if not stack - 128 <= address < address + size <= stack:
            raise ValueError("legacy policy wrote outside bounded stack")

    uc.hook_add(u.UC_HOOK_CODE, code)
    uc.hook_add(u.UC_HOOK_MEM_READ, read)
    uc.hook_add(u.UC_HOOK_MEM_WRITE, write)
    saved = [getattr(a, f"UC_ARM_REG_R{i}") for i in range(4, 12)]
    vectors = [(opcode, 16, packet, m, m & 1)
               for m in (0, 1, 2, 255) for opcode in range(256)]
    # Non-readable pointers make early full-width length/mode/null rejection
    # observable. Neither their accessibility nor their lifetime is invented.
    vectors += [(0xA1, length, pointer, m, mask)
                for length in (0, 1, 15, 17, 0x10010, 0xFFFFFFFF)
                for pointer in (0, 0xDEAD0000) for m in (0, 1) for mask in (0, 1)]
    vectors += [(0xA1, 16, 0, m, mask) for m in (0, 1) for mask in (0, 1)]
    vectors += [(0xA1, 16, 0xDEAD0000, 1, mask) for mask in (0, 1)]
    digest = hashlib.sha256()
    for opcode, length, pointer, m, mask in vectors:
        state = {"returned": False, "dispatch": [], "packet_reads": 0}
        uc.mem_write(packet, bytes([opcode]))
        uc.mem_write(mode, bytes([m]))
        uc.reg_write(a.UC_ARM_REG_R0, pointer)
        uc.reg_write(a.UC_ARM_REG_R1, length)
        uc.reg_write(a.UC_ARM_REG_SP, stack)
        uc.reg_write(a.UC_ARM_REG_LR, stop | 1)
        uc.reg_write(a.UC_ARM_REG_PRIMASK, mask)
        for i, register in enumerate(saved):
            uc.reg_write(register, 0xA5500000 + i)
        try:
            uc.emu_start(entry, 0xFFFFFFFF, count=256)
        except u.UcError as exc:
            raise ValueError("legacy policy invalid/unmapped instruction") from exc
        expected = [(pointer, length)] if pointer and m != 1 and length == 16 and opcode not in DENIED else []
        if state["dispatch"] != expected:
            raise ValueError(f"legacy policy mismatch for opcode {opcode:#x}: A1/BF/CE/CD must be denied")
        if (not state["returned"] or uc.reg_read(a.UC_ARM_REG_SP) != stack or
                uc.reg_read(a.UC_ARM_REG_PRIMASK) != mask or
                [uc.reg_read(r) for r in saved] != [0xA5500000 + i for i in range(8)] or
                state["packet_reads"] != int(bool(pointer and m != 1 and length == 16))):
            raise ValueError("legacy policy return/ABI/early-read witness failed")
        digest.update(struct.pack("<7I", opcode, length, pointer, m, mask,
                                  len(state["dispatch"]), state["packet_reads"]))
    return len(vectors), digest.hexdigest()


def retirement_plan(stock, candidate_elf, descriptor, *, policy_source):
    """Return only fixed old/new records after geometry + live ARM witnesses.

    Conditional global indicator-pattern retirement is part of this research
    policy, not approval to remove Health-mode functionality to fit an image.
    Application is only for a fresh emulator with no already-running frames.
    """
    if not all(isinstance(value, bytes) for value in (stock, candidate_elf, descriptor, policy_source)):
        raise ValueError("immutable input bytes required")
    if CANDIDATE_SHA256 is None or _sha(candidate_elf) != CANDIDATE_SHA256:
        raise ValueError("exact reviewed conditional ELF required")
    report = layout.inspect_trial(candidate_elf, stock, descriptor)
    audit_indicators(stock)
    if _sha(policy_source) != POLICY_SOURCE_SHA256:
        raise ValueError("reviewed A1/BF/CE/CD policy source changed")
    manifest, objects = layout.pinned_inputs()
    if manifest["inputs_sha256"].get("firmware/unified/stock_legacy_gate.c") != _sha(policy_source):
        raise ValueError("inspected checkpoint does not contain the reviewed A1 policy source")
    object_path = objects["stock_legacy_gate"]
    object_bytes = object_path.read_bytes()
    if _sha(object_bytes) != manifest["artifacts_sha256"][str(object_path.relative_to(layout.CHECKPOINT))]:
        raise ValueError("pinned legacy policy object changed")
    policy_object = _elf(object_bytes)
    # This helper has no text relocations: exact input .text must survive the
    # link byte-for-byte. EXIDX relocations do not alter its executable bytes.
    text_index = next(i for i, s in enumerate(policy_object.iter_sections()) if s.name == ".text")
    if any(s["sh_type"] in ("SHT_REL", "SHT_RELA") and s["sh_size"] and s["sh_info"] == text_index
           for s in policy_object.iter_sections()):
        raise ValueError("unreviewed policy text relocation")
    linked_policy = _elf(candidate_elf).get_section_by_name(".trial_stock_legacy_gate")
    if linked_policy is None or linked_policy.data() != policy_object.get_section_by_name(".text").data():
        raise ValueError("linked legacy policy differs from source-pinned object")
    if report["elf_sha256"] != _sha(candidate_elf):
        raise ValueError("inspected ELF identity changed")
    helpers = [f for f in report["functions"] if f["name"] == "wlg_receive"]
    if len(helpers) != 1:
        raise ValueError("exactly one inspected legacy helper required")
    helper = helpers[0]
    edits = []
    for offset, purpose, encoded in ENTRIES:
        before = bytes.fromhex(encoded)
        if stock[offset:offset + 4] != before:
            raise ValueError("reviewed entry old bytes changed")
        # Each reviewed entry consists of exactly two complete 16-bit
        # instructions. Refuse a wide-instruction prefix; do not decode data.
        if any(int.from_bytes(before[i:i + 2], "little") >> 11 >= 0x1D for i in (0, 2)):
            raise ValueError("entry would straddle a wide instruction")
        edits.append(EmulatorEdit(offset, before, RETURN_ZERO, purpose))
    if stock[UART_SITE:UART_SITE + 4] != UART_BEFORE:
        raise ValueError("reviewed UART BL old bytes changed")
    edits.append(EmulatorEdit(UART_SITE, UART_BEFORE,
                              _bl(BIAS + UART_SITE, helper["address"]), "uart_early_retirement"))
    edits.sort(key=lambda edit: edit.file_offset)
    for previous, following in zip(edits, edits[1:]):
        if previous.file_offset + len(previous.after) > following.file_offset:
            raise ValueError("overlapping retirement records")
    spans = [(s["address"] - BIAS, s["address"] - BIAS + s["bytes"])
             for s in report["sections"] if s["address"] < layout.APPEND]
    for edit in edits:
        lo, hi = edit.file_offset, edit.file_offset + len(edit.after)
        if any(lo < end and start < hi for start, end in (*PRESERVED, *spans)):
            raise ValueError("retirement record overlaps retained data/code or relocated ELF")
    if any(lo < end and start < hi for lo, hi in spans for start, end in PRESERVED):
        raise ValueError("conditional ELF overlaps retained data/code")
    cases, digest = _policy_witness(stock, candidate_elf, helper)
    return RetirementPlan(_sha(stock), _sha(candidate_elf), _sha(policy_source), _sha(object_bytes),
                          cases, digest, tuple(edits))
