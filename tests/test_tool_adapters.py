"""Adapter regression tests for the analyzers that were silently broken.

These tests capture the adapter contract that the seeded-defect verifier
(implementation_plan 1.13) relies on:

* eslint builds a valid argv both for a PATH eslint and for the npx fallback.
* shellcheck receives file arguments, never the directory `.`.
* gitleaks writes its JSON report to --report-path (parsed from the file),
  scans the working tree (--no-git), and surfaces real failures as errors.
* ruff severity mapping ranks bug-shaped rules above style noise.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from polycheck.finding import Severity
from polycheck.tools.eslint import EslintTool
from polycheck.tools.gitleaks import GitleaksTool
from polycheck.tools.ruff import RuffTool
from polycheck.tools.shellcheck import ShellcheckTool


def test_eslint_argv_has_no_duplicate_when_on_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "polycheck.tools.eslint.shutil.which",
        lambda name: "/usr/local/bin/eslint" if name == "eslint" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.eslint.subprocess.run", fake_run)

    EslintTool().run(tmp_path)

    assert captured["cmd"] == ["eslint", "--format=json", "--no-warn-ignored", "."]


def test_eslint_falls_back_to_npx_with_eslint_arg(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "polycheck.tools.eslint.shutil.which",
        lambda name: "/usr/local/bin/npx" if name == "npx" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.eslint.subprocess.run", fake_run)

    EslintTool().run(tmp_path)

    assert captured["cmd"] == [
        "npx", "eslint", "--format=json", "--no-warn-ignored", ".",
    ]


def test_shellcheck_receives_files_not_directory(monkeypatch, tmp_path: Path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.sh").write_text("echo hi\n")
    (tmp_path / "setup.sh").write_text("echo hi\n")

    monkeypatch.setattr(
        "polycheck.tools.shellcheck.shutil.which",
        lambda name: "/usr/bin/shellcheck" if name == "shellcheck" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.shellcheck.subprocess.run", fake_run)

    findings = ShellcheckTool().run(tmp_path)

    assert findings == []
    assert "." not in captured["cmd"]
    assert captured["cmd"][:4] == ["shellcheck", "-f", "gcc", "--severity=style"]
    files = sorted(captured["cmd"][4:])
    assert files == ["scripts/deploy.sh", "setup.sh"]


def test_shellcheck_returns_empty_without_shell_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "polycheck.tools.shellcheck.shutil.which",
        lambda name: "/usr/bin/shellcheck" if name == "shellcheck" else None,
    )
    called = {"run": False}

    def fake_run(cmd, **kwargs):
        called["run"] = True
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.shellcheck.subprocess.run", fake_run)

    assert ShellcheckTool().run(tmp_path) == []
    assert called["run"] is False


def _fake_gitleaks(monkeypatch, tmp_path: Path, returncode: int, report: list | None):
    monkeypatch.setattr(
        "polycheck.tools.gitleaks.shutil.which",
        lambda name: "/usr/bin/gitleaks" if name == "gitleaks" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        if report is not None:
            report_path = Path(cmd[cmd.index("--report-path") + 1])
            report_path.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.gitleaks.subprocess.run", fake_run)
    return captured


def test_gitleaks_parses_report_file_and_scans_working_tree(
    monkeypatch, tmp_path: Path,
):
    report = [{
        "RuleID": "aws-access-key-id",
        "File": "src/config.py",
        "StartLine": 3,
        "StartColumn": 7,
        "Description": "AWS Access Key",
        "Match": "AKIA********",
    }]
    captured = _fake_gitleaks(monkeypatch, tmp_path, returncode=1, report=report)

    findings = GitleaksTool().run(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "aws-access-key-id"
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].file == "src/config.py"
    assert findings[0].line == 3
    assert "--no-git" in captured["cmd"]
    assert "--report-path" in captured["cmd"]
    assert "--report-format" in captured["cmd"]


def test_gitleaks_no_report_file_means_no_findings(monkeypatch, tmp_path: Path):
    _fake_gitleaks(monkeypatch, tmp_path, returncode=0, report=None)

    assert GitleaksTool().run(tmp_path) == []


def test_gitleaks_surfaces_real_failures_as_errors(monkeypatch, tmp_path: Path):
    _fake_gitleaks(monkeypatch, tmp_path, returncode=2, report=None)

    with pytest.raises(RuntimeError, match="gitleaks exited 2"):
        GitleaksTool().run(tmp_path)


def _fake_ruff(monkeypatch, tmp_path: Path, items: list):
    monkeypatch.setattr(
        "polycheck.tools.ruff.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(items), stderr="",
        ),
    )


def test_ruff_severity_mapping_ranks_bugs_above_style(monkeypatch, tmp_path: Path):
    items = [
        {"code": "F821", "message": "undefined name 'x'",
         "location": {"row": 1, "column": 1}, "filename": "a.py", "fix": None},
        {"code": "E722", "message": "Do not use bare except",
         "location": {"row": 2, "column": 1}, "filename": "a.py", "fix": None},
        {"code": "N801", "message": "Class naming style",
         "location": {"row": 3, "column": 1}, "filename": "a.py", "fix": None},
        {"code": "E501", "message": "Line too long",
         "location": {"row": 4, "column": 1}, "filename": "a.py", "fix": None},
    ]
    _fake_ruff(monkeypatch, tmp_path, items)

    findings = RuffTool().run(tmp_path)
    by_rule = {f.rule: f.severity for f in findings}

    assert by_rule["F821"] is Severity.HIGH
    assert by_rule["E722"] is Severity.MEDIUM
    assert by_rule["N801"] is Severity.INFO
    assert by_rule["E501"] is Severity.LOW
