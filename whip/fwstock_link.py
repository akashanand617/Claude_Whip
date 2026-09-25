"""Validate an append-address component ELF, never construct/authorize OTA.

An exact stock image plus the captured descriptor fixes the proposed addresses.
This verifier qualifies ELF structure and fit only, not physical space ownership
or completeness of stock hooks. A valid result always remains non-flashable.
"""
from io import BytesIO
import hashlib

from whip.fwunified import STOCK_SHA256, STOCK_SIZE
from whip.fwplacement import assess_placement

APPEND = 0x847AD0
END = 0x84A000
DESCRIPTOR_CAPTURE_SHA256 = "ba6f56f927bae69ad8144673b878970ea0279a9e96ad89b986f0e76891e58dd7"


def validate_inputs(stock, descriptor_raw):
    import json
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA256 or len(stock) != STOCK_SIZE:
        raise ValueError("exact stock image required for append-address link")
    if hashlib.sha256(descriptor_raw).hexdigest() != DESCRIPTOR_CAPTURE_SHA256:
        raise ValueError("exact captured descriptor required")
    report = assess_placement(stock, json.loads(descriptor_raw))
    if (report["configured_app"]["end_exclusive"] != END or
            report["configured_capacity_margin_bytes"] != END - APPEND):
        raise ValueError("captured extent and append address disagree")
    return report


def inspect_elf(raw, stock, descriptor_raw):
    from elftools.elf.elffile import ELFFile

    validate_inputs(stock, descriptor_raw)
    elf = ELFFile(BytesIO(raw))
    if (elf.elfclass, elf.little_endian, elf["e_machine"], elf["e_type"]) != (32, True, "EM_ARM", "ET_EXEC"):
        raise ValueError("requires linked ARM32 little-endian executable ELF")
    spans, sections, allocated = [], [], []
    for s in elf.iter_sections():
        if s["sh_type"] in ("SHT_REL", "SHT_RELA") and s["sh_size"]:
            raise ValueError("unresolved relocations")
        if not s["sh_flags"] & 2 or not s["sh_size"]: continue
        start, size = s["sh_addr"], s["sh_size"]
        if s.name not in (".text", ".ARM.exidx") or s["sh_flags"] & 1 or s["sh_type"] == "SHT_NOBITS":
            raise ValueError("unexpected/writable allocated section")
        if not APPEND <= start < start + size <= END:
            raise ValueError("section outside configured stock append extent")
        expected = ("SHT_PROGBITS", 6) if s.name == ".text" else ("SHT_ARM_EXIDX", 130)
        alignment = s["sh_addralign"]
        if ((s["sh_type"], s["sh_flags"]) != expected or s["sh_offset"] + size > len(raw) or
                alignment < 4 or alignment & (alignment - 1) or
                start % alignment or s["sh_offset"] % alignment):
            raise ValueError("invalid allocated section type, flags or file extent")
        allocated.append(s)
        spans.append((start, start + size))
        sections.append({"name": s.name, "address": start, "bytes": size})
    spans.sort()
    if not spans or spans[0][0] != APPEND or any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise ValueError("missing, overlapping or shifted append sections")
    if sorted(s.name for s in allocated) != [".ARM.exidx", ".text"]:
        raise ValueError("requires unique text and unwind sections")
    text = next(s for s in allocated if s.name == ".text")
    unwind = next(s for s in allocated if s.name == ".ARM.exidx")
    text_index = next(i for i, s in enumerate(elf.iter_sections()) if s.name == ".text")
    expected_unwind = (APPEND + text["sh_size"] + 3) & ~3
    if (text["sh_addr"] != APPEND or unwind["sh_addr"] != expected_unwind or
            unwind["sh_addralign"] != 4 or unwind["sh_size"] % 8 or unwind["sh_link"] != text_index):
        raise ValueError("shifted text, unexpected gap or invalid unwind geometry")
    file_spans = sorted((s["sh_offset"], s["sh_offset"] + s["sh_size"]) for s in allocated)
    if any(a[1] > b[0] for a, b in zip(file_spans, file_spans[1:])):
        raise ValueError("overlapping allocated section file contents")
    loads = []
    for s in elf.iter_segments():
        if s["p_type"] != "PT_LOAD": continue
        start, size = s["p_vaddr"], s["p_memsz"]
        if (s["p_flags"] & 2 or s["p_filesz"] != size or s["p_paddr"] != start or
                not APPEND <= start < start + size <= END or s["p_offset"] + size > len(raw)):
            raise ValueError("writable, zero-fill, relocated or out-of-bound load segment")
        loads.append(s)
    if len(loads) != len(allocated):
        raise ValueError("requires exactly one load segment per allocated section")
    for section in allocated:
        matching = [s for s in loads if (s["p_vaddr"], s["p_memsz"]) ==
                    (section["sh_addr"], section["sh_size"])]
        if len(matching) != 1:
            raise ValueError("load segment contains unreviewed padding or ambiguous section mapping")
        segment = matching[0]
        if (section["sh_offset"] != segment["p_offset"] or segment["p_align"] != section["sh_addralign"] or
                segment["p_flags"] != (5 if section.name == ".text" else 4)):
            raise ValueError("section/load file mapping or execute permission mismatch")
    unwind_headers = [s for s in elf.iter_segments() if s["p_type"] == "PT_ARM_EXIDX"]
    if len(unwind_headers) != 1 or any(
            unwind_headers[0][field] != value for field, value in (
                ("p_vaddr", unwind["sh_addr"]), ("p_paddr", unwind["sh_addr"]),
                ("p_offset", unwind["sh_offset"]), ("p_filesz", unwind["sh_size"]),
                ("p_memsz", unwind["sh_size"]), ("p_flags", 4), ("p_align", 4))):
        raise ValueError("unwind program header differs from reviewed unwind section")
    symbols = elf.get_section_by_name(".symtab")
    if symbols is None: raise ValueError("symbols required for relocation/entry audit")
    funcs = {}
    for s in symbols.iter_symbols():
        if s.name and s["st_shndx"] == "SHN_UNDEF": raise ValueError("unresolved symbol: " + s.name)
        if s["st_info"]["type"] != "STT_FUNC" or not s["st_size"]: continue
        start, size = s["st_value"] & ~1, s["st_size"]
        if (not s["st_value"] & 1 or not text["sh_addr"] <= start < start + size <= text["sh_addr"] + text["sh_size"] or
                not isinstance(s["st_shndx"], int) or elf.get_section(s["st_shndx"]).name != ".text"):
            raise ValueError("function outside Thumb append extent")
        if s.name.startswith("proof_") or s.name == "ww_motion_valid":
            raise ValueError("test-support function in placement link")
        funcs[s.name] = s["st_value"]
    required = ("wd_init", "wd_receive", "wa_observe", "wh_job_begin", "wb_stock_stop_writes",
                "wg_stock_add", "wg_stock_notify20", "wf_request", "wf_complete", "wht_stop_scheduled",
                "wht_stop_reviewed",
                "wss_read_controls", "wrc_commit_hr", "wop_read", "wop_retire", "woi_samples_io",
                "__aeabi_uidiv", "__aeabi_memmove4")
    if any(name not in funcs for name in required) or elf["e_entry"] != funcs["wd_init"]:
        raise ValueError("missing required component or wrong entry")
    # Exact section/load coverage above makes this also the complete load extent;
    # subtraction counts the (at most three-byte) unwind-alignment gap too.
    extent = max(hi for _, hi in spans)
    return {"schema": "whip.stock-append-link.v1", "elf_sha256": hashlib.sha256(raw).hexdigest(),
            "stock_sha256": STOCK_SHA256, "append_address": APPEND, "end_exclusive": extent,
            "configured_end": END, "occupied_append_bytes": extent - APPEND,
            "configured_remaining_bytes": END - extent, "sections": sections, "functions": funcs,
            "stock_bytes_changed": 0, "static_ram_bytes": 0,
            "actual_address_link": True, "stock_hooks_attached": False,
            "ram_ownership_verified": False, "recovery_verified": False, "flashable": False,
            "warning": "component link only; remaining hardware/service/hooks/state not included"}


from whip.fwthumb import RuntimeThumb


class StockAppendThumb(RuntimeThumb):
    """Execute real-address linked code with synthetic, NOT allocated ring RAM.

    Default observer permits only the new component functions, not arbitrary
    stock/ROM execution. ABI tests may override specific named boundaries.
    Reuses strict AAPCS/canary/read/write checks from the artificial test runner.
    """
    CODE = 0x840000
    RETURN = CODE + 0xFF00
    CONTEXT_MAX_BYTES = 1024

    def __init__(self, raw, stock, descriptor_raw):
        import unicorn as u
        from unicorn import arm_const as a
        from elftools.elf.elffile import ELFFile

        self.report = inspect_elf(raw, stock, descriptor_raw)
        self.u, self.a = u, a
        elf = ELFFile(BytesIO(raw))
        self.symbols, self.executable = {}, []
        for s in elf.get_section_by_name(".symtab").iter_symbols():
            if s["st_info"]["type"] == "STT_FUNC" and s["st_size"]:
                self.symbols[s.name] = s["st_value"]
                self.executable.append((s["st_value"] & ~1, (s["st_value"] & ~1) + s["st_size"]))
        self.uc = u.Uc(u.UC_ARCH_ARM, u.UC_MODE_THUMB | u.UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(a.UC_CPU_ARM_CORTEX_M0)
        self.uc.mem_map(self.CODE, 0x10000, u.UC_PROT_READ | u.UC_PROT_EXEC)
        self.uc.mem_map(self.RAM, 0x10000, u.UC_PROT_READ | u.UC_PROT_WRITE)
        self.loaded_spans = []
        for s in elf.iter_segments():
            if s["p_type"] == "PT_LOAD" and s["p_memsz"]:
                self.uc.mem_write(s["p_vaddr"], s.data())
                self.loaded_spans.append((s["p_vaddr"], s["p_vaddr"] + s["p_memsz"]))
        self.context_size = self.CONTEXT_MAX_BYTES  # Fixture bound, NOT ring allocation.
        self.batch_length = self.instruction_count = 0
        self.returned = False
        self.stack_low = self.STACK
        self.uc.mem_write(self.CONTEXT - 16, b"\xA5" * (self.context_size + 32))
        self.uc.hook_add(u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(u.UC_HOOK_MEM_WRITE, self._write)
        self.uc.hook_add(u.UC_HOOK_MEM_READ, self._read)
