"""Offline proof integrity guards. No firmware, BLE or image-writing API.

Capture InputSnapshot before compiling, verify at stage boundaries, and snapshot
the ELF/collection report before execution. Verify every snapshot immediately
before writing a success manifest. This detects content drift between checks,
not a transient edit that is restored between them; it is not a filesystem lock.

Use sanitized_pytest_env(), then set the build-owned WHIP_UNIFIED_TEST_ELF.
Run pytest with explicit test paths, ``-c /dev/null --noconftest -o addopts=``
and ``-p whip.fwproof_guard`` in BOTH phases:

* ``--collect-only --proof-report collected.json``
* ``--proof-expected collected.json --proof-report executed.json``

The plugin rejects deselection, skips, xfails, duplicate/missing phase reports,
changed collection identity and reused output paths. Failed reports are retained.
It validates test identities/outcomes, not their assertions or coverage quality.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path


class ProofIntegrityError(RuntimeError):
    """The evidence no longer matches the declared proof inputs or test run."""


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class InputSnapshot:
    """Content fingerprints of named files, without mutating those files.

    Paths are made absolute but symlinks are NOT resolved: replacing a source
    symlink must verify the file the compiler would now see, not its old target.
    ``hashes`` returns a copy suitable for a manifest, never the mutable baseline.
    """

    def __init__(self, paths: Mapping[str, Path]):
        if not paths or any(not isinstance(name, str) or not name for name in paths):
            raise ValueError("snapshot requires nonempty named file paths")
        self._paths = {name: Path(path).absolute() for name, path in paths.items()}
        self._hashes = self._capture()

    def _capture(self) -> dict[str, str]:
        hashes = {}
        for name, path in self._paths.items():
            try:
                hashes[name] = _digest(path)
            except OSError as exc:
                raise ProofIntegrityError(f"proof file unavailable: {name}") from exc
        return hashes

    @property
    def hashes(self) -> dict[str, str]:
        return dict(self._hashes)

    def verify(self) -> None:
        current = self._capture()
        changed = sorted(name for name, digest in current.items() if digest != self._hashes[name])
        if changed:
            raise ProofIntegrityError("proof files changed: " + ", ".join(changed))


def sanitized_pytest_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy an environment without inherited pytest/Python injection knobs.

    Callers still own the executable, working directory and explicit CLI; this
    is not a security sandbox. In particular, do not append unchecked pytest
    options or plugins. Set build-owned fixture paths only AFTER sanitizing.
    """
    source = os.environ if base is None else base
    result = {key: value for key, value in source.items()
              if not key.startswith(("PYTEST_", "PYTHON")) and
              key not in ("WHIP_UNIFIED_TEST_ELF", "WHIP_STOCK_LINK_ELF")}
    result.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONNOUSERSITE="1",
                  PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    return result


def load_proof_report(path: Path, *, phase: str | None = None) -> dict:
    """Read only a successful identity report; failed evidence stays on disk."""
    try:
        report = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ProofIntegrityError("proof report unavailable or malformed") from exc
    if (not isinstance(report, dict) or report.get("schema") != 1
            or report.get("phase") not in ("collection", "execution")
            or (phase is not None and report.get("phase") != phase)
            or report.get("valid") is not True or report.get("exitstatus") != 0
            or report.get("violations") != [] or report.get("deselected") != []
            or report.get("collection_problems") != []):
        raise ProofIntegrityError("proof report does not establish a complete passing run")
    nodeids = report.get("collected")
    if (not isinstance(nodeids, list) or not nodeids
            or any(not isinstance(nodeid, str) or not nodeid for nodeid in nodeids)
            or len(set(nodeids)) != len(nodeids)):
        raise ProofIntegrityError("proof report has invalid collection identities")
    if report["phase"] == "execution":
        outcomes = report.get("reports")
        if not isinstance(outcomes, dict) or set(outcomes) != set(nodeids):
            raise ProofIntegrityError("proof report has incomplete execution identities")
        for nodeid in nodeids:
            if outcomes[nodeid] != [
                    {"when": when, "outcome": "passed", "xfail": False}
                    for when in ("setup", "call", "teardown")]:
                raise ProofIntegrityError("proof report has incomplete passing phases")
    return report


def pytest_addoption(parser):
    group = parser.getgroup("whip-offline-proof")
    group.addoption("--proof-report", metavar="PATH", help="new complete-proof identity report path")
    group.addoption("--proof-expected", metavar="PATH", help="successful prior collection report")


def pytest_configure(config):
    import pytest

    report = config.getoption("--proof-report")
    expected = config.getoption("--proof-expected")
    collecting = bool(config.option.collectonly)
    if not report or (collecting and expected) or (not collecting and not expected):
        raise pytest.UsageError(
            "proof plugin requires --proof-report and either --collect-only or --proof-expected"
        )
    try:
        plugin = _IdentityPlugin(Path(report), Path(expected) if expected else None)
    except (ProofIntegrityError, ValueError) as exc:
        raise pytest.UsageError(str(exc)) from exc
    config.pluginmanager.register(plugin, "whip-proof-identities")


class _IdentityPlugin:
    def __init__(self, output: Path, expected: Path | None):
        if output.exists() or not output.parent.is_dir():
            raise ValueError("proof report must be a new path in an existing directory")
        self.output = output
        self.expected_snapshot = InputSnapshot({"collection report": expected}) if expected else None
        self.expected = load_proof_report(expected, phase="collection")["collected"] if expected else None
        if self.expected_snapshot:
            self.expected_snapshot.verify()
        self.collected = []
        self.deselected = []
        self.collection_problems = []
        self.reports = {}
        self.violations = []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.deselected.extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.outcome != "passed":
            self.collection_problems.append({"nodeid": report.nodeid, "outcome": report.outcome})

    def pytest_runtest_logreport(self, report):
        self.reports.setdefault(report.nodeid, []).append(
            {"when": report.when, "outcome": report.outcome, "xfail": hasattr(report, "wasxfail")}
        )

    def pytest_sessionfinish(self, session, exitstatus):
        problems = self.violations
        if exitstatus:
            problems.append(f"pytest exit status {int(exitstatus)}")
        if not self.collected or len(set(self.collected)) != len(self.collected):
            problems.append("empty or duplicate collection identities")
        if self.deselected:
            problems.append("test deselection is forbidden")
        if self.collection_problems:
            problems.append("collection failed or skipped")
        if self.expected is not None:
            if self.collected != self.expected:
                problems.append("execution collection differs from the expected ordered identities")
            try:
                self.expected_snapshot.verify()
            except ProofIntegrityError as exc:
                problems.append(str(exc))
            if set(self.reports) != set(self.collected):
                problems.append("missing or unexpected executed test identities")
            passing = [{"when": when, "outcome": "passed", "xfail": False}
                       for when in ("setup", "call", "teardown")]
            for nodeid, reports in self.reports.items():
                if reports != passing:
                    problems.append(f"nonpassing, skipped, xfail, missing or duplicate phases: {nodeid}")
        elif self.reports:
            problems.append("collection-only phase unexpectedly executed tests")
        if problems:
            session.exitstatus = 1
        report = {
            "schema": 1, "phase": "execution" if self.expected is not None else "collection",
            "valid": not problems, "exitstatus": int(session.exitstatus),
            "collected": self.collected, "deselected": self.deselected,
            "collection_problems": self.collection_problems,
            "reports": self.reports, "violations": problems,
        }
        # Exclusive create: even a competing writer must not be overwritten.
        try:
            with self.output.open("x") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
        except OSError as exc:
            session.exitstatus = 1
            problems.append(f"cannot create proof report: {exc}")

    def pytest_terminal_summary(self, terminalreporter):
        if self.violations:
            terminalreporter.write_sep("=", "incomplete offline proof")
            for problem in self.violations:
                terminalreporter.write_line(problem)
