import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from whip.fwproof_guard import (
    InputSnapshot, ProofIntegrityError, _IdentityPlugin, load_proof_report, sanitized_pytest_env,
)


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_detects_source_and_elf_drift_without_changing_files(tmp_path):
    source, elf = tmp_path / "runtime.c", tmp_path / "proof.elf"
    source.write_bytes(b"first source")
    elf.write_bytes(b"first ELF")
    original_mapping = {"source": source, "ELF": elf}
    snapshot = InputSnapshot(original_mapping)
    assert snapshot.hashes == {name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for name, path in original_mapping.items()}
    snapshot.hashes["source"] = "cannot mutate stored baseline"
    original_mapping.clear()
    snapshot.verify()
    source.write_bytes(b"second source")
    with pytest.raises(ProofIntegrityError, match="source"):
        snapshot.verify()
    assert source.read_bytes() == b"second source"
    source.write_bytes(b"first source")
    elf.write_bytes(b"swapped ELF")
    with pytest.raises(ProofIntegrityError, match="ELF"):
        snapshot.verify()
    assert elf.read_bytes() == b"swapped ELF"


def test_snapshot_rejects_missing_file_and_tracks_symlink_target(tmp_path):
    first, second, link = (tmp_path / name for name in ("first", "second", "source"))
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    link.symlink_to(first)
    snapshot = InputSnapshot({"source": link})
    link.unlink()
    link.symlink_to(second)
    with pytest.raises(ProofIntegrityError, match="changed"):
        snapshot.verify()
    link.unlink()
    with pytest.raises(ProofIntegrityError, match="unavailable"):
        snapshot.verify()
    with pytest.raises(ProofIntegrityError, match="unavailable"):
        InputSnapshot({"missing": link})
    with pytest.raises(ValueError):
        InputSnapshot({})


def test_pytest_environment_removes_inherited_selection_and_injection():
    inherited = {"PATH": "/toolchain", "WHIP_ZIG": "/zig", "KEEP": "value",
                 "PYTEST_ADDOPTS": "-k one", "PYTEST_PLUGINS": "untrusted",
                 "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "0", "PYTEST_CURRENT_TEST": "outer",
                 "PYTHONPATH": "/untrusted", "PYTHONHOME": "/untrusted",
                 "WHIP_UNIFIED_TEST_ELF": "/stale.elf", "WHIP_STOCK_LINK_ELF": "/stale-stock.elf"}
    clean = sanitized_pytest_env(inherited)
    assert clean == {"PATH": "/toolchain", "WHIP_ZIG": "/zig", "KEEP": "value",
                     "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONNOUSERSITE": "1",
                     "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
    assert inherited["PYTEST_ADDOPTS"] == "-k one"


def _run(source, report, *, expected=None, extra=(), inherited=None):
    env = sanitized_pytest_env(inherited)
    command = [sys.executable, "-m", "pytest", "-q", "-c", os.devnull, "--noconftest",
               "-o", "addopts=", "-p", "whip.fwproof_guard", str(source),
               "--proof-report", str(report)]
    command += ["--proof-expected", str(expected)] if expected else ["--collect-only"]
    return subprocess.run([*command, *extra], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "test_fixture.py"
    path.write_text("def test_one(): pass\ndef test_two(): pass\n")
    return path


def test_two_phase_identity_report_and_sanitized_selection_env(source, tmp_path):
    collected, executed = tmp_path / "collected.json", tmp_path / "executed.json"
    inherited = dict(os.environ, PYTEST_ADDOPTS="-k nonexistent", PYTEST_PLUGINS="missing_plugin",
                     PYTHONPATH="/untrusted", WHIP_UNIFIED_TEST_ELF="/stale.elf")
    result = _run(source, collected, inherited=inherited)
    assert result.returncode == 0, result.stdout + result.stderr
    initial = load_proof_report(collected, phase="collection")
    assert len(initial["collected"]) == 2
    result = _run(source, executed, expected=collected, inherited=inherited)
    assert result.returncode == 0, result.stdout + result.stderr
    final = load_proof_report(executed, phase="execution")
    assert final["collected"] == initial["collected"]
    assert set(final["reports"]) == set(initial["collected"])


@pytest.mark.parametrize("phase", ["collection", "execution"])
def test_explicit_selection_is_rejected_even_if_one_test_passes(source, tmp_path, phase):
    expected = None
    if phase == "execution":
        expected = tmp_path / "expected.json"
        assert _run(source, expected).returncode == 0
    output = tmp_path / "partial.json"
    result = _run(source, output, expected=expected, extra=("-k", "test_one"))
    assert result.returncode != 0
    report = json.loads(output.read_text())
    assert not report["valid"] and len(report["deselected"]) == 1
    with pytest.raises(ProofIntegrityError):
        load_proof_report(output)


@pytest.mark.parametrize("body", [
    "import pytest\n@pytest.mark.skip(reason='missing proof')\ndef test_one(): pass\n",
    "import pytest\ndef test_one(): pytest.skip('runtime missing proof')\n",
    "import pytest\ndef test_one(): pytest.xfail('not proven')\n",
    "import pytest\n@pytest.mark.xfail(reason='unexpected pass')\ndef test_one(): pass\n",
    "def test_one(): assert False\n",
    "import pytest\n@pytest.fixture\ndef check():\n yield\n pytest.skip('teardown')\ndef test_one(check): pass\n",
])
def test_nonpassing_execution_never_counts_as_a_complete_proof(source, tmp_path, body):
    source.write_text(body)
    collected, executed = tmp_path / "collected.json", tmp_path / "executed.json"
    assert _run(source, collected).returncode == 0
    result = _run(source, executed, expected=collected)
    assert result.returncode != 0
    assert executed.exists()  # Preserve failed evidence; never silently delete it.
    with pytest.raises(ProofIntegrityError):
        load_proof_report(executed)


def test_module_collection_skip_and_empty_selection_are_rejected(source, tmp_path):
    source.write_text("import pytest\npytest.skip('module unavailable', allow_module_level=True)\n")
    report = tmp_path / "skipped.json"
    assert _run(source, report).returncode != 0
    assert json.loads(report.read_text())["collection_problems"]
    source.write_text("# no tests\n")
    empty = tmp_path / "empty.json"
    assert _run(source, empty).returncode != 0
    with pytest.raises(ProofIntegrityError):
        load_proof_report(empty)


def test_collection_identity_change_fails_execution(source, tmp_path):
    collected, executed = tmp_path / "collected.json", tmp_path / "executed.json"
    assert _run(source, collected).returncode == 0
    source.write_text("def test_one(): pass\n")
    assert _run(source, executed, expected=collected).returncode != 0
    assert any("differs" in text for text in json.loads(executed.read_text())["violations"])


def test_expected_report_drift_during_execution_fails(source, tmp_path):
    collected, executed = tmp_path / "collected.json", tmp_path / "executed.json"
    source.write_text(f"from pathlib import Path\ndef test_one(): Path({str(collected)!r}).write_text('{{}}')\n")
    assert _run(source, collected).returncode == 0
    assert _run(source, executed, expected=collected).returncode != 0
    assert any("changed" in text for text in json.loads(executed.read_text())["violations"])


def test_report_output_is_never_overwritten(source, tmp_path):
    output = tmp_path / "already-present.json"
    output.write_bytes(b"preserve failed or successful artifacts")
    assert _run(source, output).returncode != 0
    assert output.read_bytes() == b"preserve failed or successful artifacts"


@pytest.mark.parametrize("phases", [(), ("setup", "call"), ("setup", "call", "call", "teardown")])
def test_missing_or_duplicate_execution_phases_fail_closed(source, tmp_path, phases):
    collected = tmp_path / "collected.json"
    assert _run(source, collected).returncode == 0
    expected = load_proof_report(collected)
    output = tmp_path / "executed.json"
    plugin = _IdentityPlugin(output, collected)
    session = SimpleNamespace(items=[SimpleNamespace(nodeid=nodeid) for nodeid in expected["collected"]],
                              exitstatus=0)
    plugin.pytest_collection_finish(session)
    for nodeid in expected["collected"]:
        for phase in phases:
            plugin.pytest_runtest_logreport(SimpleNamespace(nodeid=nodeid, when=phase, outcome="passed"))
    plugin.pytest_sessionfinish(session, 0)
    assert session.exitstatus != 0
    with pytest.raises(ProofIntegrityError):
        load_proof_report(output)
