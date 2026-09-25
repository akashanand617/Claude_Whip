"""Actual whole-candidate refusal and integrity mutants; never a ring test."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from probe import owner_wait_budget as budget
from whip.fwproof_guard import ProofIntegrityError


def zig():
    result = os.environ.get("WHIP_ZIG")
    assert result, "explicit reviewed Zig required; no skips"
    return result


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    output = tmp_path_factory.mktemp("owner-wait") / "full25"
    return output, budget.build(output, zig())


def test_real_full25_refuses_without_fabricated_physical_bindings_or_larger_regions(built):
    output, report = built
    assert report["object_count"] == 25
    assert report["unresolved_strong_symbols"] == sorted(budget.MISSING)
    assert not report["link_succeeded"] and report["identical_second_refusal"]
    assert not report["map_is_successful_fit_evidence"]
    assert not any(report[k] for k in budget.GATES)
    assert report["stock_bytes_written"] == 0
    assert report["mailbox_storage_bytes"] == 56 and report["event_scratch_bytes"] == 32
    assert report["control_owner_bytes"] == 880
    assert report["real_control_composition_implemented"]
    assert report["owner_includes_dispatch_coordinator_and_stop_record"]
    assert report["hypothetical_stock_text_bytes"] == 1894
    assert report["configured_append_bytes"] == 9520
    assert report["new_text_bytes"]["stock_supervisor_wait"] == 72
    assert report["new_text_bytes"]["control_mailbox"] > 0
    assert "configured_remaining_bytes" not in report
    assert not list(output.glob("*.elf")) and not list(output.glob("*.bin"))
    _, pins, _ = budget.prior_inputs()
    objects = {n: p.read_bytes() for n, p in pins.items()} | {
        n: (output / f"{n}.o").read_bytes() for n in budget.NEW}
    functions, constants, sizes, unwind = budget.trial._inventory(objects)
    assert report["function_count"] == sum(functions.values())
    assert report["constant_count"] == sum(constants.values())
    assert report["input_unwind_bytes"] == unwind
    rodata = sum(s["sh_size"] for raw in objects.values()
                 for s in budget.trial._elf(raw).iter_sections() if s.name == ".rodata")
    moved = sum(sizes[n] for n in budget.trial.PLACEMENTS)
    lower_bound = sum(sizes.values()) + rodata - moved
    assert report["append_input_lower_bound_bytes"] == lower_bound == 10610
    assert report["append_lower_bound_over_bytes"] == max(0, lower_bound - 9520) == 1090
    assert (output / "UNOWNED-unchanged-conditional.ld").read_text() == budget.trial.linker_script(sizes)
    for name, digest in report["inputs_sha256"].items():
        assert budget.trial._sha((budget.ROOT / name).read_bytes()) == digest
    for name, digest in report["artifacts_sha256"].items():
        assert budget.trial._sha((output / name).read_bytes()) == digest
    for i in range(1, 4):
        log = json.loads((output / f"link-{i}.json").read_text())
        assert log["exit"] != 0
        assert all("undefined symbol: " + name in log["stderr"] for name in budget.MISSING)
        assert "undefined symbol: wuw_supervise" not in log["stderr"]
        assert any("--no-undefined" in item for item in log["command"])
        assert not any("--defsym" in item or "--unresolved-symbols" in item for item in log["command"])
        assert sum(item.endswith(".o") for item in log["command"]) == 25
    assert (output / "failed-link-NOT-FIT.map").stat().st_size > 0
    assert json.loads((output / "budget-report.json").read_text()) == report


@pytest.mark.parametrize("changed", ["report", "object", "source"])
def test_discovery_pins_fail_before_output(tmp_path, monkeypatch, changed):
    previous = tmp_path / "previous"
    previous.mkdir()
    original = json.loads((budget.PREVIOUS / "budget-report.json").read_text())
    report = deepcopy(original)
    obj = (budget.PREVIOUS / "discovery.o").read_bytes()
    if changed == "source":
        report["inputs_sha256"]["firmware/unified/discovery.h"] = "0" * 64
    report_path = previous / "budget-report.json"
    report_path.write_text(json.dumps(report))
    (previous / "discovery.o").write_bytes(obj + (b"corrupt" if changed == "object" else b""))
    monkeypatch.setattr(budget, "PREVIOUS", previous)
    if changed != "report":
        monkeypatch.setattr(budget, "PREVIOUS_SHA", budget.trial._sha(report_path.read_bytes()))
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="reviewed discovery budget changed|pinned discovery object changed|pinned discovery source changed"):
        budget.build(output, zig())
    assert not output.exists()


@pytest.mark.parametrize("changed", ["source", "tool"])
def test_original_source_and_tool_pins_fail_before_output(tmp_path, monkeypatch, changed):
    manifest, pins, report = budget.prior_inputs()
    manifest = deepcopy(manifest)
    if changed == "source":
        manifest["inputs_sha256"]["firmware/unified/wire.h"] = "0" * 64
    else:
        manifest["tool_executables_sha256"]["clang"] = "0" * 64
    monkeypatch.setattr(budget, "prior_inputs", lambda: (manifest, pins, report))
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="pinned source changed|reviewed tool executable changed"):
        budget.build(output, zig())
    assert not output.exists()


def test_later_compile_cannot_rebaseline_earlier_mailbox(tmp_path, monkeypatch):
    original = subprocess.run
    compiled = []

    def corrupt(command, *args, **kwargs):
        result = original(command, *args, **kwargs)
        if "-c" in command:
            compiled.append(Path(command[command.index("-o") + 1]))
            if len(compiled) == 2:
                compiled[0].write_bytes(compiled[0].read_bytes() + b"changed")
        return result

    monkeypatch.setattr(budget.subprocess, "run", corrupt)
    output = tmp_path / "changed"
    with pytest.raises(ProofIntegrityError, match="control_mailbox.o"):
        budget.build(output, zig())
    assert len(compiled) == 2 and not (output / "budget-report.json").exists()


@pytest.mark.parametrize("relative", ["wire.h", "mode_controller.c", "control_mailbox.h"])
def test_missing_required_source_never_falls_out_of_guard(tmp_path, monkeypatch, relative):
    original = Path.exists
    missing = budget.ROOT / "firmware/unified" / relative
    monkeypatch.setattr(Path, "exists", lambda p: False if p == missing else original(p))
    output = tmp_path / "missing-source"
    with pytest.raises(ValueError, match="required source missing"):
        budget.build(output, zig())
    assert not output.exists()


@pytest.mark.parametrize("binding", ["static", "global", "weak"])
def test_only_external_definitions_can_resolve_an_external_reference(tmp_path, binding):
    manifest, _, _ = budget.prior_inputs()
    prefix = {"static": "static ", "global": "", "weak": "__attribute__((weak)) "}[binding]
    sources = {"caller": "extern void named(void); void caller(void) { named(); }",
               "definition": prefix + "void named(void) {} void (*retain(void))(void) { return named; }"}
    objects = {}
    for name, source in sources.items():
        obj = tmp_path / (name + ".o")
        subprocess.run(["/usr/bin/clang", *manifest["flags"], "-x", "c", "-c", "-", "-o", str(obj)],
                       input=source, text=True, check=True)
        objects[name] = obj.read_bytes()
    assert budget.unresolved_symbols(objects) == ({"named"} if binding == "static" else set())


@pytest.mark.parametrize("bad", ["false_success", "different_refusal", "fake_elf"])
def test_false_link_claims_never_create_a_report(tmp_path, monkeypatch, bad):
    original = subprocess.run

    def corrupt(command, *args, **kwargs):
        result = original(command, *args, **kwargs)
        if "cc" in command or "ld.lld" in command:
            if bad == "false_success":
                return subprocess.CompletedProcess(command, 0, "", "")
            if bad == "different_refusal":
                return subprocess.CompletedProcess(command, 1, "", "some unrelated error")
            Path(command[command.index("-o") + 1]).write_bytes(b"not firmware")
        return result

    monkeypatch.setattr(budget.subprocess, "run", corrupt)
    output = tmp_path / bad
    with pytest.raises(ValueError, match="whole link must refuse|expected failed map only"):
        budget.build(output, zig())
    assert not (output / "budget-report.json").exists()
