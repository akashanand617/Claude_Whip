"""Actual-address, OFF-RING final Health commit boundary.

This focused ELF is deliberately incomplete and rejected by the production
placement verifier. Settings revision ownership, scheduler rebinding, physical
STOP and maskable-interrupt arrival are explicitly SIMULATED. No ring access.
"""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from probe.unified_build import SOURCES
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import APPEND, END, inspect_elf, validate_inputs
from whip.fwthumb import RuntimeThumb, ThumbProofError

ROOT = Path(__file__).resolve().parents[1]
CORE = ("mode_controller", "sample_tap", "runtime", "health_adapter", "fresh_source",
        "adapter", "stock_schedule_settings", "compiler_runtime")
HELPER = "stock_health_commit"
FIELDS = (0x208AAC, 0x208AAD, 0x208C44, 0x208C46)
CONTROL_BYTES = bytes((5, 0x1F, 3, 1))
CONTROLS = int.from_bytes(CONTROL_BYTES, "little")
ABI_SOURCE = """
#include <stddef.h>
#include "stock_health_commit.h"
unsigned proof_wsc_adapter_size(void) { return sizeof(wa_adapter); }
unsigned proof_wsc_health_offset(void) { return offsetof(wa_adapter, health); }
unsigned proof_wsc_prepared_size(void) { return sizeof(wsc_prepared); }
unsigned proof_wsc_revision_offset(void) { return offsetof(wh_adapter, settings_revision); }
unsigned proof_wsc_jobs_offset(void) { return offsetof(wh_adapter, jobs); }
"""


@pytest.fixture(scope="module")
def commit_build(tmp_path_factory):
    compiler = shutil.which("clang")
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not compiler or not zig: pytest.skip("reviewed Clang/Zig required")
    zig = shutil.which(zig)
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    assert HELPER not in SOURCES  # not silently added to the nearly-full image
    output = tmp_path_factory.mktemp("stock-health-commit")
    units = tuple(dict.fromkeys((*SOURCES, *CORE, HELPER)))
    paths = [Path(__file__).relative_to(ROOT), "probe/unified_build.py", "whip/fwproof_guard.py",
             "whip/fwthumb.py", "whip/fwstock_link.py", "firmware/unified/stock_append.ld",
             *(f"firmware/unified/{n}.c" for n in units),
             *(f"firmware/unified/{n}.h" for n in units if n != "compiler_runtime")]
    snapshot = InputSnapshot({str(p): ROOT / p for p in paths})
    toolchain = InputSnapshot({"clang": Path(compiler), "zig": Path(zig)})
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding",
             "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fstack-usage",
             "-I", str(ROOT / "firmware/unified")]
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    linkflags = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus",
                 "-nostdlib", "-Wl,-T," + str(ROOT / "firmware/unified/stock_append.ld"),
                 "-Wl,--build-id=none", "-Wl,--no-undefined", "-Wl,-z,max-page-size=4"]
    objects = {}
    for name in units:
        obj = output / f"{name}.o"
        subprocess.run([compiler, *flags, "-c", str(ROOT / f"firmware/unified/{name}.c"),
                        "-o", str(obj)], check=True)
        objects[name] = obj
    abi = output / "abi.o"
    subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o", str(abi)],
                   input=ABI_SOURCE, text=True, check=True)
    elf = output / "focused-actual-address-NOT-INSTALLABLE.elf"
    command = [*linkflags, "-Wl,-e,wr_init", "-o", str(elf),
               *(str(objects[n]) for n in (*CORE, HELPER)), str(abi)]
    subprocess.run(command, env=env, check=True)
    # Recompile the NEW helper and ABI and relink; do not merely link twice.
    second = output / "repeat.o"
    subprocess.run([compiler, *flags, "-c", str(ROOT / f"firmware/unified/{HELPER}.c"),
                    "-o", str(second)], check=True)
    assert second.read_bytes() == objects[HELPER].read_bytes()
    second_abi = output / "repeat-abi.o"
    subprocess.run([compiler, *flags, "-x", "c", "-c", "-", "-o", str(second_abi)],
                   input=ABI_SOURCE, text=True, check=True)
    assert second_abi.read_bytes() == abi.read_bytes()
    repeated = output / "repeated.elf"
    subprocess.run([*linkflags, "-Wl,-e,wr_init", "-o", str(repeated),
                    *(str(objects[n]) for n in CORE), str(second), str(second_abi)], env=env, check=True)
    assert elf.read_bytes() == repeated.read_bytes()
    focused_baseline = output / "focused-baseline-NOT-INSTALLABLE.elf"
    subprocess.run([*linkflags, "-Wl,-e,wr_init", "-o", str(focused_baseline),
                    *(str(objects[n]) for n in CORE), str(abi)], env=env, check=True)
    baseline = output / "full-baseline-NOT-INSTALLABLE.elf"
    full = [str(objects[n]) for n in (*SOURCES, "compiler_runtime")]
    subprocess.run([*linkflags, "-Wl,-e,wd_init", "-o", str(baseline), *full], env=env, check=True)
    result = subprocess.run([*linkflags, "-Wl,-e,wd_init",
                             "-o", str(output / "full-with-helper-REFUSED.elf"),
                             *full, str(objects[HELPER])], env=env, capture_output=True, text=True)
    snapshot.verify(); toolchain.verify()
    return dict(elf=elf.read_bytes(), baseline=baseline.read_bytes(), refused=result,
                focused_baseline=focused_baseline.read_bytes(),
                object=objects[HELPER].read_bytes(), directory=output)


class HealthCommitThumb(RuntimeThumb):
    CODE = 0x840000
    RETURN = CODE + 0xFF00
    CONTEXT_SIZE_SYMBOL = "proof_wsc_adapter_size"
    REVISION = RuntimeThumb.BATCH + 16  # independent SIMULATED owner, not ring RAM

    def __init__(self, elf):
        self.active = False
        self.trace, self.shared_reads, self.shared_writes, self.settings_reads = [], [], [], []
        self.interrupt_at = None
        self.pending_interrupt = False
        self.delivered_at = None
        self.change = None
        super().__init__(elf)
        self.health = self.CONTEXT + self.call("proof_wsc_health_offset")
        self.revision_offset = self.call("proof_wsc_revision_offset")
        self.jobs_offset = self.call("proof_wsc_jobs_offset")
        assert self.call("proof_wsc_prepared_size") == 16
        self.uc.mem_map(0x208000, 0x1000, self.u.UC_PROT_READ | self.u.UC_PROT_WRITE)
        self.uc.mem_write(0x208000, b"\xa5" * 0x1000)
        self.set_controls(CONTROL_BYTES)
        self.invoke("wa_init", 1, 1)  # SIMULATED closed inventory
        assert self.hcall("wh_job_begin", 0, self.OUTPUT)
        self.original = tuple(struct.unpack("<IIB3x", self.uc.mem_read(self.OUTPUT, 12)))
        self.invoke("wa_link", 1, 0, 1)
        # Begin/abort entry using real core code; no source profile or hardware.
        assert self.invoke("wr_request", 1, 1)
        assert self.hcall("wh_begin_quiesce", self.word(12))
        assert self.invoke("wa_cancelled", self.word(12), self.hword(4), 1, 1)
        assert self.invoke("wa_fenced", self.word(12), self.hword(4), 1)
        assert self.invoke("wa_optics_stopped", self.word(12), self.hword(4), 1, 1)
        # Above: SIMULATED drain/hub fence/physical STOP, not claimed by helper.
        assert self.invoke("wa_request", 0, 2)
        for action, simulated in ((4, 0x70), (5, 0x82)):
            assert self.word(4) == action
            self.raw_input(struct.pack("<6I", self.word(12), self.word(16), action, simulated, 0, 0))
            assert self.invoke("wa_physical_done", self.BATCH, 2)
        assert self.word(4) == 6
        assert self.invoke("wa_begin_resume", self.word(12), 17, 2)
        assert self.invoke("wa_resume_ready", self.word(12), self.hword(4), 17, 1, 1, 2)
        # Above: SIMULATED preservation/current-settings scheduler preparation.
        self.prepared = (self.word(12), self.hword(4), 17, CONTROLS)
        self.raw_input(struct.pack("<5I", *self.prepared, 17))
        self.initial = bytes(self.uc.mem_read(self.CONTEXT, self.context_size))

    def set_controls(self, values):
        for address, value in zip(FIELDS, values, strict=True):
            self.uc.mem_write(address, bytes([value]))

    def hcall(self, name, *args): return self.call(name, self.health, *args)

    def hword(self, offset): return struct.unpack("<I", self.uc.mem_read(self.health + offset, 4))[0]

    def _code(self, uc, address, size, opaque):
        if address == self.symbols.get("wsc_commit_health", 0) & ~1:
            self.active = True
        if self.active:
            index = len(self.trace)
            if index == self.interrupt_at: self.pending_interrupt = True
            masked = uc.reg_read(self.a.UC_ARM_REG_PRIMASK)
            if self.pending_interrupt and not masked:
                self.change(self)  # named maskable-writer schedule, not RTOS
                self.pending_interrupt = False
                self.delivered_at = index
            self.trace.append((address, masked))
            if address == self.RETURN: self.active = False
        super()._code(uc, address, size, opaque)

    def _read(self, uc, access, address, size, value, opaque):
        shared = (self.CONTEXT <= address < self.CONTEXT + self.context_size or
                  self.BATCH <= address < self.BATCH + self.batch_length)
        if self.active and shared:
            if not uc.reg_read(self.a.UC_ARM_REG_PRIMASK):
                raise ThumbProofError("shared commit read outside exclusion")
            self.shared_reads.append((len(self.trace) - 1, address, size))
        if address in FIELDS and size == 1:
            if not self.active or not uc.reg_read(self.a.UC_ARM_REG_PRIMASK):
                raise ThumbProofError("current controls read outside commit exclusion")
            self.settings_reads.append(address)
            return
        super()._read(uc, access, address, size, value, opaque)

    def _write(self, uc, access, address, size, value, opaque):
        if 0x208000 <= address < 0x209000:
            raise ThumbProofError("commit attempted stock state/settings write")
        if self.active and self.CONTEXT <= address < self.CONTEXT + self.context_size:
            if not uc.reg_read(self.a.UC_ARM_REG_PRIMASK):
                raise ThumbProofError("adapter commit write outside exclusion")
            self.shared_writes.append((len(self.trace) - 1, address, size))
        super()._write(uc, access, address, size, value, opaque)

    def commit(self, *, primask=0, ipsr=0, now=2, a=None, prepared=None, revision=None):
        self.trace.clear(); self.shared_reads.clear(); self.shared_writes.clear(); self.settings_reads.clear()
        self.uc.reg_write(self.a.UC_ARM_REG_PRIMASK, primask)
        self.uc.reg_write(self.a.UC_ARM_REG_IPSR, ipsr)
        self.stack_low = self.STACK
        result = self.call("wsc_commit_health", self.CONTEXT if a is None else a,
                           self.BATCH if prepared is None else prepared,
                           self.REVISION if revision is None else revision, now)
        assert self.uc.reg_read(self.a.UC_ARM_REG_PRIMASK) == primask
        assert self.uc.reg_read(self.a.UC_ARM_REG_IPSR) == ipsr
        assert len(self.trace) < 800  # instructions, NOT measured interrupt latency
        assert self.stack_low >= self.STACK - 224  # observed chain, not task headroom
        return result


def test_focused_elf_is_not_a_production_image_and_full_addition_stays_refused(commit_build):
    stock = (ROOT / "firmware/rt02cr-stock-3.12.02.bin").read_bytes()
    descriptor = (ROOT / "firmware/research/2026-09-23/bank0-descriptor/configuration.json").read_bytes()
    validate_inputs(stock, descriptor)
    with pytest.raises(ValueError, match="test-support function|missing required"):
        inspect_elf(commit_build["elf"], stock, descriptor)
    baseline = inspect_elf(commit_build["baseline"], stock, descriptor)
    assert not baseline["flashable"] and baseline["stock_bytes_changed"] == 0
    for s in ELFFile(BytesIO(commit_build["elf"])).iter_sections():
        if s["sh_flags"] & 2 and s["sh_size"]:
            assert s.name in (".text", ".ARM.exidx") and not s["sh_flags"] & 1
            assert APPEND <= s["sh_addr"] < s["sh_addr"] + s["sh_size"] <= END
    result = commit_build["refused"]
    assert result.returncode != 0
    assert "configured APP bound exceeded" in result.stderr or "will not fit in region" in result.stderr


@pytest.mark.parametrize("primask", [0, 1])
def test_actual_commit_opens_both_software_gates_and_invalidates_original_job(commit_build, primask):
    h = HealthCommitThumb(commit_build["elf"])
    assert (h.word(0), h.hword(0)) == (3, 4)
    assert not h.hcall("wh_result_allowed", *h.original, 1)
    before = bytes(h.uc.mem_read(0x208000, 0x1000))
    record = bytes(h.uc.mem_read(h.BATCH, 20))
    assert h.commit(primask=primask)
    assert (h.word(0), h.word(4), h.hword(0)) == (0, 0, 0)
    assert h.settings_reads == list(FIELDS)
    assert bytes(h.uc.mem_read(0x208000, 0x1000)) == before
    assert bytes(h.uc.mem_read(h.BATCH, 20)) == record
    assert not h.hcall("wh_result_allowed", *h.original, 1)
    assert not h.hcall("wh_run_begin", *h.original)
    assert h.hcall("wh_job_begin", 0, h.OUTPUT)
    new = tuple(struct.unpack("<IIB3x", h.uc.mem_read(h.OUTPUT, 12)))
    assert new[0] == h.prepared[1] and new[1] > h.original[1]
    assert h.hcall("wh_result_allowed", *new, 1)
    assert not h.commit()  # consumes this preparation once


@pytest.mark.parametrize("field", range(4))
@pytest.mark.parametrize("primask", [0, 1])
def test_changed_controls_without_revision_faults_attempt_without_inventing_revision(commit_build, field, primask):
    h = HealthCommitThumb(commit_build["elf"])
    changed = bytearray(CONTROL_BYTES); changed[field] ^= 0x80
    h.set_controls(changed)
    assert not h.commit(primask=primask)
    assert (h.word(0), h.hword(0)) == (4, 5)
    assert h.hword(h.revision_offset) == 17
    assert bytes(h.uc.mem_read(h.REVISION, 4)) == struct.pack("<I", 17)
    h.set_controls(CONTROL_BYTES)
    assert not h.commit()  # visible contract break cannot be undone by ABA
    assert not h.hcall("wh_result_allowed", *h.original, 1)


@pytest.mark.parametrize("current", [0, 16, 18, 0xFFFFFFFF])
def test_changed_revision_invalidates_ready_without_start_or_relabel(commit_build, current):
    h = HealthCommitThumb(commit_build["elf"])
    h.uc.mem_write(h.REVISION, struct.pack("<I", current))
    assert not h.commit()
    assert (h.word(0), h.word(4), h.hword(0)) == (3, 6, 3)
    assert h.hword(h.revision_offset) == current
    assert h.hword(12) == h.prepared[0] and h.hword(4) == h.prepared[1]
    assert not h.settings_reads
    assert not h.hcall("wh_result_allowed", *h.original, 1)
    # This helper does not approve decreasing/wrapped revisions; producer must
    # prevent them. Any unequal observation invalidates the old preparation.


def test_changed_current_settings_require_new_preparation_even_after_revision_invalidates_ready(commit_build):
    h = HealthCommitThumb(commit_build["elf"])
    changed = bytes((60, 2, 3, 1))
    h.uc.mem_write(h.REVISION, struct.pack("<I", 18))
    h.set_controls(changed)
    assert not h.commit()
    assert not h.commit() and (h.word(0), h.hword(0)) == (3, 3)
    # SIMULATED new scheduler preparation, never a real timer-create receipt.
    assert h.invoke("wa_resume_ready", h.prepared[0], h.prepared[1], 18, 1, 1, 2)
    assert not h.commit()  # original preparation cannot relabel its revision
    h.raw_input(struct.pack("<5I", h.prepared[0], h.prepared[1], 18,
                            int.from_bytes(changed, "little"), 18))
    assert h.commit() and (h.word(0), h.hword(0)) == (0, 0)
    assert not h.hcall("wh_result_allowed", *h.original, 1)


@pytest.mark.parametrize("field,value", [(0, 0), (0, 1), (0, 6), (1, 0), (1, 2), (1, 4), (2, 16), (2, 18)])
def test_stale_preparation_never_mutates_newer_state_or_reads_settings(commit_build, field, value):
    h = HealthCommitThumb(commit_build["elf"])
    h.uc.mem_write(h.BATCH + 4 * field, struct.pack("<I", value))
    assert not h.commit() and not h.shared_writes and not h.settings_reads
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == h.initial


@pytest.mark.parametrize("pointer", ["a", "prepared", "revision"])
@pytest.mark.parametrize("value", [0, 1, 3])
def test_null_or_misaligned_arguments_refused_before_shared_access(commit_build, pointer, value):
    h = HealthCommitThumb(commit_build["elf"])
    assert not h.commit(**{pointer: value})
    assert not h.shared_reads and not h.shared_writes and not h.settings_reads
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == h.initial


@pytest.mark.parametrize("ipsr", [2, 3, 11, 15, 16, 31])
@pytest.mark.parametrize("primask", [0, 1])
def test_exception_context_is_refused_before_state_or_stock_access(commit_build, ipsr, primask):
    h = HealthCommitThumb(commit_build["elf"])
    assert not h.commit(ipsr=ipsr, primask=primask)
    assert not h.shared_reads and not h.shared_writes and not h.settings_reads
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == h.initial


@pytest.mark.parametrize("field,value", [(0, 0), (0, 1), (0, 2), (0, 3), (0, 5),
                                        (24, 0), (28, 1), (164, 0), (165, 0), (166, 0)])
def test_missing_ready_inventory_or_quiet_evidence_cannot_be_forged_by_guard(commit_build, field, value):
    h = HealthCommitThumb(commit_build["elf"])
    h.uc.mem_write(h.health + field, bytes([value]) if field >= 164 else struct.pack("<I", value))
    assert not h.commit()
    assert h.word(0) != 0
    assert not h.invoke("wa_health_allowed", 0)


def test_unavailable_boot_inventory_is_not_reinterpreted_as_permission_to_disable_stock_health(commit_build):
    h = HealthCommitThumb(commit_build["elf"])
    h.invoke("wa_init", 0, 0)
    before = bytes(h.uc.mem_read(h.CONTEXT, h.context_size))
    assert h.invoke("wa_health_passthrough")
    assert not h.commit() and not h.shared_writes and not h.settings_reads
    assert bytes(h.uc.mem_read(h.CONTEXT, h.context_size)) == before
    assert h.invoke("wa_health_passthrough")


def test_expired_resume_cannot_be_committed_by_valid_current_settings(commit_build):
    h = HealthCommitThumb(commit_build["elf"])
    assert not h.commit(now=3002)
    assert h.word(0) == 4 and h.hword(0) == 4  # READY closed; runtime timeout fault
    assert not h.invoke("wa_health_allowed", 0)


def test_aba_with_real_revision_change_is_rejected_but_unobserved_broken_writer_is_not_claimed_detectable(commit_build):
    h = HealthCommitThumb(commit_build["elf"])
    h.uc.mem_write(h.REVISION, struct.pack("<I", 18))
    h.set_controls(bytes((60, 0, 0, 0)))
    h.uc.mem_write(h.REVISION, struct.pack("<I", 19))
    h.set_controls(CONTROL_BYTES)
    assert not h.commit() and h.hword(0) == 3
    # No counter is created or inferred from controls. Unobservable ABA with a
    # lying/unchanged revision is outside the required writer contract.
    broken = HealthCommitThumb(commit_build["elf"])
    broken.set_controls(bytes((60, 0, 0, 0))); broken.set_controls(CONTROL_BYTES)
    assert broken.commit()  # explicit limitation, NEVER revision-owner proof


def test_maskable_writer_at_every_instruction_linearizes_before_or_after_commit(commit_build):
    baseline = HealthCommitThumb(commit_build["elf"]); assert baseline.commit()
    outcomes = set()
    for index in range(len(baseline.trace)):
        h = HealthCommitThumb(commit_build["elf"])
        def writer(runner):
            runner.uc.mem_write(runner.REVISION, struct.pack("<I", 18))
            runner.set_controls(bytes((60, 0, 3, 1)))
        h.interrupt_at, h.change = index, writer
        accepted = h.commit()
        outcomes.add(accepted)
        assert h.delivered_at is not None and not h.pending_interrupt
        if accepted:
            assert all(i < h.delivered_at for i, *_ in h.shared_reads + h.shared_writes)
            assert (h.word(0), h.hword(0)) == (0, 0)
        else:
            assert (h.word(0), h.hword(0)) == (3, 3)
        assert bytes(h.uc.mem_read(h.REVISION, 4)) == struct.pack("<I", 18)
    assert outcomes == {0, 1}


def test_preexisting_mask_stays_set_and_does_not_deliver_pending_writer(commit_build):
    h = HealthCommitThumb(commit_build["elf"])
    h.interrupt_at = 0
    h.change = lambda _: pytest.fail("masked interrupt delivered")
    assert h.commit(primask=1)
    assert h.pending_interrupt and h.delivered_at is None


def test_measured_pure_call_chain_and_size_are_not_a_whole_image_fit(commit_build):
    h = HealthCommitThumb(commit_build["elf"]); assert h.commit()
    executed = {name for name, value in h.symbols.items() if (value & ~1) in {pc for pc, _ in h.trace}}
    assert {"wsc_commit_health", "wss_read_controls", "wa_commit_health", "wh_commit_health"} <= executed
    assert not any(name in executed for name in ("wa_resume_ready", "wh_stopped", "wh_job_begin",
                                                  "wh_run_begin", "wa_physical_done"))
    elf = ELFFile(BytesIO(commit_build["object"]))
    sections = {s.name: (s["sh_size"], s["sh_addralign"]) for s in elf.iter_sections()
                if s["sh_flags"] & 2 and s["sh_size"]}
    assert set(sections) == {".text", ".ARM.exidx"}
    def extent(raw):
        return max(s["sh_addr"] + s["sh_size"] for s in ELFFile(BytesIO(raw)).iter_sections()
                   if s["sh_flags"] & 2 and s["sh_size"]) - APPEND
    report = dict(object_allocated_size_alignment=sections,
                  helper_local_stack=(commit_build["directory"] / "stock_health_commit.su").read_text().strip(),
                  observed_nested_stack=h.STACK - h.stack_low,
                  success_instructions=len(h.trace), masked_instructions=sum(masked for _, masked in h.trace),
                  focused_extent=extent(commit_build["elf"]),
                  focused_extent_added=extent(commit_build["elf"]) - extent(commit_build["focused_baseline"]),
                  full_baseline_extent=extent(commit_build["baseline"]),
                  full_plus_helper_refusal=commit_build["refused"].stderr.strip())
    print(json.dumps(report, indent=2))


@pytest.mark.parametrize("mutation", ["mask", "restore"])
def test_emulator_only_mask_mutants_are_caught(commit_build, mutation):
    h = HealthCommitThumb(commit_build["elf"])
    start = h.symbols["wsc_commit_health"] & ~1
    end = next(hi for lo, hi in h.executable if lo == start)
    if mutation == "mask":
        body = bytes(h.uc.mem_read(start, end - start))
        assert body.count(b"\x72\xb6") == 1
        h.uc.mem_write(start + body.index(b"\x72\xb6"), b"\x00\xbf")
        with pytest.raises(ThumbProofError, match="outside exclusion"): h.commit()
    else:
        baseline = HealthCommitThumb(commit_build["elf"]); assert baseline.commit()
        sites = [pc for (pc, masked), (_, following) in zip(baseline.trace, baseline.trace[1:])
                 if masked == 1 and following == 0]
        assert len(sites) == 1
        h.uc.mem_write(sites[0], b"\x00\xbf\x00\xbf")
        with pytest.raises(AssertionError): h.commit()
