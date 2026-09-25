"""Compiled coordinator plus original stock instructions; OFF-RING only.

The complete prototype deliberately uses the artificial proof address space.
Its actual-address addition is also attempted and must report real capacity
failure, never call the proof ELF installable. Cancellation, hub/IRQ fences,
physical STOP, hold/release, source times and scheduler preparation stay named
fixtures; the new C, not Python, performs STOP/retirement/resume orchestration.
"""
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from elftools.elf.elffile import ELFFile

from probe.unified_build import SOURCES, SUPPORT_SOURCES, UNLINKED_CANDIDATES
from tests.test_stock_switch import SwitchThumb, HEALTH_MODE, ENTERING, GESTURE, RETURNING, FAULT
from tests.test_stock_switch import QUIESCE, HOLD, START, STOP, RELEASE, RESUME, SCRATCH
from tests.test_stock_optical_work import HEALTH, BUFFER, STATUS
from tests.test_fwstock_link import STOCK, DESCRIPTOR
from whip.fwproof_guard import InputSnapshot
from whip.fwstock_link import inspect_elf

ROOT = Path(__file__).resolve().parents[1]
OWNER, STOP_RECEIPT, REVISION, PREPARED = 0x226000, 0x226100, 0x226200, 0x226300
ABI_SOURCE = """
#include "stock_coordinator.h"
unsigned proof_wc_owner_size(void) { return sizeof(wc_owner); }
unsigned proof_wc_stop_size(void) { return sizeof(wc_stop_receipt); }
unsigned proof_wc_resume_size(void) { return sizeof(wc_resume_receipt); }
"""


@pytest.fixture(scope="module")
def coordinator_build(tmp_path_factory):
    clang = shutil.which("clang")
    zig = os.environ.get("WHIP_ZIG") or shutil.which("zig")
    if not clang or not zig:
        pytest.skip("reviewed Clang/Zig required")
    zig = shutil.which(zig)
    assert subprocess.check_output([zig, "version"], text=True).strip() == "0.15.2"
    output = tmp_path_factory.mktemp("stock-coordinator")
    units = (*SOURCES, *UNLINKED_CANDIDATES)
    files = [ROOT / f"firmware/unified/{n}.{ext}" for n in units for ext in ("c", "h")]
    files += [ROOT / p for p in (*SUPPORT_SOURCES, "firmware/unified/compiler_runtime.c",
              "tests/native/arm_proof.ld", "firmware/unified/stock_append.ld",
              "tests/test_stock_switch.py", "tests/test_stock_optical_io.py",
              "tests/test_stock_optical_work.py", "whip/fwstock_link.py",
              "whip/fwproof_guard.py", "probe/unified_build.py")]
    files.append(Path(__file__))
    source = InputSnapshot({str(p.relative_to(ROOT)): p for p in files})
    toolchain = InputSnapshot({"clang": Path(clang), "zig": Path(zig)})
    flags = ["--target=armv6m-none-eabi", "-mcpu=cortex-m0plus", "-mthumb", "-ffreestanding",
             "-fno-builtin", "-Oz", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fstack-usage",
             "-I", str(ROOT / "firmware/unified")]
    objects = []
    for file in [ROOT / f"firmware/unified/{n}.c" for n in units] + [ROOT / p for p in SUPPORT_SOURCES]:
        obj = output / (file.stem + ".o")
        subprocess.run([clang, *flags, "-c", str(file), "-o", str(obj)], check=True)
        objects.append(obj)
    abi = output / "coordinator-abi.o"
    subprocess.run([clang, *flags, "-x", "c", "-c", "-", "-o", str(abi)],
                   input=ABI_SOURCE, text=True, check=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(output / "cache"),
               ZIG_LOCAL_CACHE_DIR=str(output / "local"))
    link = [zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_m0plus", "-nostdlib",
            "-Wl,--build-id=none", "-Wl,--no-undefined", "-Wl,-z,max-page-size=4"]
    target = output / "coordinator-ARTIFICIAL-NOT-INSTALLABLE.elf"
    invocation = [*link, "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
                  "-Wl,-e,wr_init", "-o", str(target), *map(str, objects), str(abi)]
    subprocess.run(invocation, env=env, check=True)
    repeat = output / "coordinator-repeat.o"
    subprocess.run([clang, *flags, "-c", str(ROOT / "firmware/unified/stock_coordinator.c"),
                    "-o", str(repeat)], check=True)
    assert repeat.read_bytes() == (output / "stock_coordinator.o").read_bytes()
    second = output / "coordinator-repeat.elf"
    again = [str(repeat) if p.stem == "stock_coordinator" else str(p) for p in objects]
    subprocess.run([*link, "-Wl,-T," + str(ROOT / "tests/native/arm_proof.ld"),
                    "-Wl,-e,wr_init", "-o", str(second), *again, str(abi)], env=env, check=True)
    assert target.read_bytes() == second.read_bytes()
    # Attempt ALL real components/candidates without ABI/proof objects. No
    # discarded exports or enlarged region to manufacture a successful fit.
    runtime = output / "compiler_runtime.o"
    subprocess.run([clang, *flags, "-c", str(ROOT / "firmware/unified/compiler_runtime.c"),
                    "-o", str(runtime)], check=True)
    actual = output / "coordinator-full-REFUSED.elf"
    result = subprocess.run([*link, "-Wl,-T," + str(ROOT / "firmware/unified/stock_append.ld"),
                             "-Wl,-e,wd_init", "-o", str(actual),
                             *(str(output / (n + ".o")) for n in units), str(runtime)],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0 and not actual.exists()
    assert "will not fit in region" in result.stderr or "configured APP bound exceeded" in result.stderr
    source.verify(); toolchain.verify()
    return {"elf": target.read_bytes(), "directory": output, "refused": result}


class CoordinatorThumb(SwitchThumb):
    def __init__(self, raw, *, inventory=True):
        self._retire_return = None
        self.retirements = 0
        super().__init__(raw, (408, 60, 288, 31, 223, 24), inventory=inventory, actual=False)
        self.owner_size = self.function("proof_wc_owner_size")
        self.stop_size = self.function("proof_wc_stop_size")
        self.resume_size = self.function("proof_wc_resume_size")
        assert (self.owner_size, self.stop_size, self.resume_size) == (28, 28, 20)
        self.uc.mem_write(OWNER - 8, b"\xa5" * (self.owner_size + 16))
        self.uc.mem_write(STOP_RECEIPT - 8, b"\xa5" * (self.stop_size + 16))
        self.uc.mem_write(REVISION, struct.pack("<I", 17))
        self.function("wc_init", OWNER, self.base)

    def _code(self, uc, address, size, opaque):
        if self._retire_return == address:
            self.active = None
            self._retire_return = None
        if address == (self.functions.get("wop_retire", 0) & ~1):
            assert self.active is None
            self.active = "retire"
            self._retire_return = uc.reg_read(self.a.UC_ARM_REG_LR) & ~1
            self.retirements += 1
        super()._code(uc, address, size, opaque)

    def pump(self, now=1, *, revision=REVISION, buffer=BUFFER, status=STATUS, output=STOP_RECEIPT):
        result = self.function("wc_pump", OWNER, revision, buffer, status, now, output)
        for p, size in ((OWNER, self.owner_size), (STOP_RECEIPT, self.stop_size)):
            assert self.uc.mem_read(p - 8, 8) == b"\xa5" * 8
            assert self.uc.mem_read(p + size, 8) == b"\xa5" * 8
        return result

    def stopped(self, now=1, verified=True, *, receipt=STOP_RECEIPT, buffer=BUFFER, status=STATUS):
        return self.function("wc_optics_stopped", OWNER, receipt, int(verified), buffer, status, now)

    def physical(self, proof, now):
        self.uc.mem_write(SCRATCH, struct.pack("<6I", self.token, self.session,
                                              self.mode(4), proof, 1, 2))
        return self.function("wc_physical_done", OWNER, SCRATCH, now)

    def quiet_with_fixtures(self, now):
        pause = self.token
        assert self.adapter("wa_cancelled", pause, self.word(4),
                            self.fixture("actual producer drain", 1), now)
        assert self.adapter("wa_fenced", pause, self.word(4), now)
        self.fixture("IRQ/hub/RUN/publication fence", True)
        self.pump(now)
        assert self.transfers[-2:] == [b"\x7b\xa5", b"\x7b\0"]
        assert self.mode(4) == QUIESCE
        assert self.stopped(now, self.fixture("physical optics STOP", True))
        assert self.mode(4) == HOLD and self.token != pause
        assert self.uc.mem_read(BUFFER + 0xA8, 128) == bytes(128)
        assert self.uc.mem_read(STATUS + 24, 4) == bytes(4)

    def prepare_resume(self, now=2, *, revision=17, controls=None, preserved=True, rebound=True):
        controls = self.controls() if controls is None else controls
        body = struct.pack("<4I2B2x", self.token, self.word(4), revision, controls,
                           int(preserved), int(rebound))
        self.uc.mem_write(PREPARED, body)
        self.fixture("fresh current-settings scheduler preparation", (preserved, rebound))
        return self.function("wc_resume_prepared", OWNER, PREPARED, REVISION, now)


def test_full_candidate_has_honest_budget_and_no_production_admission(coordinator_build):
    with pytest.raises(ValueError):
        inspect_elf(coordinator_build["elf"], STOCK, DESCRIPTOR)
    e = ELFFile(BytesIO(coordinator_build["elf"]))
    names = {s.name for s in e.get_section_by_name(".symtab").iter_symbols()}
    assert {"wc_pump", "wc_optics_stopped", "wc_resume_prepared", "wsc_commit_health",
            "wgd_database", "wht_stop_reviewed", "wf_request", "wlg_receive"} <= names
    assert all(not s["sh_flags"] & 1 for s in e.iter_sections() if s["sh_flags"] & 2 and s["sh_size"])
    assert coordinator_build["refused"].returncode != 0


def test_compiled_coordinator_runs_health_gesture_health_with_original_stock_paths(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"])
    initial = h.controls()
    assert h.read() == 0 and h.commit(h.original)
    h.command(3, 1, 1); h.enter(requested=True)
    assert h.mode(4) == START and not h.adapter("wa_health_allowed", 0)
    assert h.controls() == initial
    assert h.observe((1, 2, 8005)) == 2 and h.mode() == GESTURE
    h.reply(3, 1, 1)
    assert h.submit_motion(1)[3]
    h.command(2, 2, 2); h.to_resume()
    h.uc.mem_write(REVISION, struct.pack("<I", 18))  # simulated serialized writer
    h.set_controls((60, 4, 3, 1))
    h.pump(2)
    assert not h.adapter("wa_health_allowed", 0)
    assert h.prepare_resume(revision=18) and h.mode() == HEALTH_MODE
    h.reply(2, 2, 2)
    assert h.adapter("wa_health_allowed", 0)
    assert not h.commit(h.original)
    new = h.new_job(); h.configure_samples()
    h.fixture("fresh optical acquisition setup", True)
    assert h.read(ticket=new) == 0 and h.commit(new)
    assert h.controls() == int.from_bytes(bytes((60, 4, 3, 1)), "little")
    assert not h.allocations and not h.timer_calls


def test_pump_never_invents_cancellation_fence_or_physical_stop(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    h.pump(); assert not h.transfers
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    h.pump(); assert not h.transfers
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump(); assert len(h.transfers) == 2
    snapshot = bytes(h.uc.mem_read(STOP_RECEIPT, h.stop_size))
    for _ in range(3):
        h.pump()
    assert len(h.transfers) == 2 and h.mode(4) == QUIESCE
    assert bytes(h.uc.mem_read(STOP_RECEIPT, h.stop_size)) == snapshot
    assert not h.physical(0x0F, 1) and not h.adapter("wa_health_allowed", 0)


@pytest.mark.parametrize("failure", ["take", "reset", "stop", "give"])
def test_real_stop_failure_never_becomes_a_receipt_or_automatic_retry(coordinator_build, failure):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    if failure == "take": h.take_results[0] = False
    elif failure == "give": h.release_results[0] = False
    else: h.transfer_results.extend((1, 0) if failure == "reset" else (0, 1))
    h.pump()
    transfers = len(h.transfers)
    assert h.mode() == RETURNING and h.mode(4) == STOP
    assert not h.stopped() and not h.adapter("wa_health_allowed", 0)
    h.pump(); assert len(h.transfers) == transfers


@pytest.mark.parametrize("stage", [0, 1, 2, 3])
def test_partial_entry_resume_requires_new_proof_and_retires_before_health(coordinator_build, stage):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    original = h.token, h.word(4)
    if stage >= 1: assert h.adapter("wa_cancelled", *original, 1, 1)
    if stage >= 2: assert h.adapter("wa_fenced", *original, 1)
    if stage >= 3:
        h.pump()
        h.uc.mem_write(PREPARED, bytes(h.uc.mem_read(STOP_RECEIPT, h.stop_size)))
    h.to_resume()
    h.pump(2)
    assert h.mode(4) == RESUME and h.word(0) == 3
    assert len(h.transfers) == (2 if stage >= 3 else 0)
    if stage >= 3:
        assert not h.stopped(2, receipt=PREPARED)
    assert not h.prepare_resume()
    assert not h.adapter("wa_cancelled", *original, 1, 2)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 2)
    assert h.adapter("wa_fenced", h.token, h.word(4), 2)
    h.pump(2)
    assert h.transfers == [b"\x7b\xa5", b"\x7b\0"] * (2 if stage >= 3 else 1)
    assert h.stopped(2)
    assert h.word(0) == 3 and not h.adapter("wa_health_allowed", 0)
    assert h.prepare_resume() and h.adapter("wa_health_allowed", 0)


@pytest.mark.parametrize("field", [0, 1, 2])
def test_stale_stop_identity_cannot_consume_or_relabel_pending_operation(coordinator_build, field):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    receipt = bytes(h.uc.mem_read(STOP_RECEIPT, h.stop_size))
    before = bytes(h.uc.mem_read(OWNER, h.owner_size)), bytes(h.uc.mem_read(h.base, 764))
    altered = bytearray(receipt)
    struct.pack_into("<I", altered, field * 4, 0xFFFFFFFF)
    h.uc.mem_write(STOP_RECEIPT, bytes(altered))
    assert not h.stopped()
    assert before == (bytes(h.uc.mem_read(OWNER, h.owner_size)), bytes(h.uc.mem_read(h.base, 764)))
    h.uc.mem_write(STOP_RECEIPT, receipt)
    assert h.stopped()
    before = bytes(h.uc.mem_read(h.base, 764))
    assert not h.stopped() and bytes(h.uc.mem_read(h.base, 764)) == before


@pytest.mark.parametrize("trigger", ["disconnect", "charging", "timeout"])
def test_late_physical_stop_never_advances_an_abandoned_attempt(coordinator_build, trigger):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    if trigger == "disconnect": assert h.adapter("wd_close", 7, 2)
    elif trigger == "charging": assert h.adapter("wd_charging", 7, 1, 2)
    assert not h.stopped(3001 if trigger == "timeout" else 2)
    assert h.mode() == RETURNING and h.mode(4) == STOP
    assert not h.physical(0x0F, 2) and not h.adapter("wa_health_allowed", 0)


def test_diagnostic_write_fields_are_not_the_physical_stop_authority(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    h.uc.mem_write(STOP_RECEIPT + 12, b"\xff" * 16)
    # Actual writes succeeded internally. The copied report is diagnostic only.
    assert h.stopped()
    failed = CoordinatorThumb(coordinator_build["elf"])
    assert failed.adapter("wa_request", 1, 1)
    assert failed.adapter("wa_cancelled", failed.token, failed.word(4), 1, 1)
    assert failed.adapter("wa_fenced", failed.token, failed.word(4), 1)
    failed.transfer_results.extend((1, 0))
    failed.pump()
    failed.uc.mem_write(STOP_RECEIPT + 12, struct.pack("<4I", 1, 0, 0, 1))
    assert not failed.stopped() and not failed.adapter("wa_health_allowed", 0)


@pytest.mark.parametrize("failure", ["physical", "retirement"])
def test_stop_or_retirement_failure_keeps_hold_closed(coordinator_build, failure):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    if failure == "retirement":
        h.uc.mem_write(0x2085A8, struct.pack("<I", STATUS + 4))
    assert not h.stopped(verified=failure != "physical")
    assert h.mode() == RETURNING and h.mode(4) == STOP
    assert not h.physical(0x0F, 1) and not h.adapter("wa_health_allowed", 0)


@pytest.mark.parametrize("which", ["buffer", "status"])
def test_captured_object_substitution_does_not_consume_physical_receipt(coordinator_build, which):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    before = bytes(h.uc.mem_read(OWNER, h.owner_size)), bytes(h.uc.mem_read(h.base, 764))
    assert not h.stopped(**{which: (BUFFER if which == "buffer" else STATUS) + 4})
    assert before == (bytes(h.uc.mem_read(OWNER, h.owner_size)), bytes(h.uc.mem_read(h.base, 764)))
    assert h.stopped()


@pytest.mark.parametrize("missing", ["preserved", "rebound"])
def test_resume_cannot_manufacture_preservation_or_fresh_scheduler_setup(coordinator_build, missing):
    h = CoordinatorThumb(coordinator_build["elf"]); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.to_resume(); h.pump(2)
    transfers = len(h.transfers)
    assert not h.prepare_resume(**{missing: False})
    assert h.mode() == FAULT and not h.adapter("wa_health_allowed", 0)
    assert len(h.transfers) == transfers  # quiet carry never restarts or re-stops


def test_current_revision_change_and_aba_never_reuse_old_preparation(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"]); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.to_resume(); h.pump(2)
    saved = h.controls()
    h.uc.mem_write(REVISION, struct.pack("<I", 18))
    h.set_controls((10, 1, 3, 1))
    h.uc.mem_write(REVISION, struct.pack("<I", 19))
    h.set_controls((5, 0x1F, 3, 1))
    assert h.controls() == saved
    assert not h.prepare_resume(revision=17)
    assert h.mode() == RETURNING and not h.adapter("wa_health_allowed", 0)
    assert h.prepare_resume(revision=19)
    assert h.mode() == HEALTH_MODE and not h.commit(h.original)


def test_visible_controls_change_without_revision_faults_not_false_health(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"]); h.enter()
    assert h.observe((1, 2, 8005)) == 2
    h.to_resume(); h.pump(2)
    saved = h.controls()
    h.set_controls((10, 1, 3, 1))
    assert not h.prepare_resume(controls=saved)
    assert h.mode() == FAULT and not h.adapter("wa_health_allowed", 0)


@pytest.mark.parametrize("mask,exception", [(1, 0), (0, 15), (1, 15)])
def test_coordinator_rejects_masked_or_exception_entry_before_shared_mutation(coordinator_build, mask, exception):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    before = bytes(h.uc.mem_read(OWNER, h.owner_size)), bytes(h.uc.mem_read(h.base, 764))
    h.uc.reg_write(h.a.UC_ARM_REG_PRIMASK, mask)
    h.uc.reg_write(h.a.UC_ARM_REG_IPSR, exception)
    assert h.pump() == 6
    assert not h.stopped()
    assert not h.physical(0x0F, 1)
    assert not h.prepare_resume()
    h.function("wc_init", OWNER, h.base)
    assert before == (bytes(h.uc.mem_read(OWNER, h.owner_size)), bytes(h.uc.mem_read(h.base, 764)))
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == mask
    assert h.uc.reg_read(h.a.UC_ARM_REG_IPSR) == exception
    assert not h.transfers and not h.receives


def test_unknown_inventory_keeps_default_stock_health_and_never_touches_bus(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"], inventory=False)
    assert h.pump() == 0
    assert h.adapter("wa_health_passthrough") and h.adapter("wa_health_allowed", 0)
    assert not h.adapter("wa_request", 1, 1)
    assert not h.transfers and not h.receives


def test_unexpected_returned_interrupt_mask_faults_and_is_not_silently_cleared(coordinator_build):
    class ReturnedMask(CoordinatorThumb):
        def _code(self, uc, address, size, opaque):
            super()._code(uc, address, size, opaque)
            if address == 0x1341C:  # explicit misbehaving mutex-give fixture
                uc.reg_write(self.a.UC_ARM_REG_PRIMASK, 1)
    h = ReturnedMask(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    assert h.pump() == 7
    assert h.uc.reg_read(h.a.UC_ARM_REG_PRIMASK) == 1
    assert h.word(0) == 5 and h.mode() == RETURNING and h.mode(4) == STOP
    assert h.transfers == [b"\x7b\xa5", b"\x7b\0"]
    assert not h.stopped()


def test_integrated_retirement_mask_mutant_is_detected(coordinator_build):
    h = CoordinatorThumb(coordinator_build["elf"])
    assert h.adapter("wa_request", 1, 1)
    assert h.adapter("wa_cancelled", h.token, h.word(4), 1, 1)
    assert h.adapter("wa_fenced", h.token, h.word(4), 1)
    h.pump()
    start = h.functions["enter"] & ~1
    end = next(hi for lo, hi in h.spans if lo == start)
    body = bytes(h.uc.mem_read(start, end - start))
    assert body.count(b"\x72\xb6") == 1
    h.uc.mem_write(start + body.index(b"\x72\xb6"), b"\x00\xbf")
    with pytest.raises(AssertionError):
        h.stopped()
