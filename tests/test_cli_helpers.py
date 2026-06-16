"""Tests for the _exit_code and _missing_tools helpers in the CLI."""
from __future__ import annotations

from pathlib import Path

from polycheck.finding import Category, Finding, Severity
from polycheck.registry import ToolRegistry
from polycheck.tools.base import Tool


def _f(severity: Severity, tool: str = "t", rule: str = "r") -> Finding:
    return Finding(
        tool=tool, rule=rule, severity=severity, category=Category.LINT,
        message="x", file="x", line=1,
    )


def test_exit_code_no_findings():
    from polycheck.cli import _exit_code
    assert _exit_code([], "MEDIUM") == 0


def test_exit_code_below_threshold():
    from polycheck.cli import _exit_code
    findings = [_f(Severity.INFO), _f(Severity.LOW)]
    assert _exit_code(findings, "MEDIUM") == 0


def test_exit_code_at_threshold():
    from polycheck.cli import _exit_code
    findings = [_f(Severity.LOW), _f(Severity.MEDIUM)]
    assert _exit_code(findings, "MEDIUM") == 1


def test_exit_code_above_threshold():
    from polycheck.cli import _exit_code
    findings = [_f(Severity.LOW), _f(Severity.CRITICAL)]
    assert _exit_code(findings, "MEDIUM") == 1


def test_exit_code_unknown_threshold_is_permissive():
    """An unknown --fail-on value should not crash the CLI; treat as 'never fail'."""
    from polycheck.cli import _exit_code
    findings = [_f(Severity.CRITICAL)]
    assert _exit_code(findings, "BOGUS") == 0


def test_missing_tools_filters_universal_on_empty_repo(tmp_path: Path, monkeypatch):
    """A universal tool whose binary is missing should be listed, but
    only when the repo has *some* content (otherwise gitleaks on an
    empty dir is just noise).
    """
    reg = ToolRegistry()

    class _MissingUniversal(Tool):
        name = "missing-universal"
        category = Category.LINT
        languages = []
        universal = True

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return False

        def run(self, repo):
            return []

    reg.register(_MissingUniversal)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    from polycheck.cli import _missing_tools

    # Truly empty repo → no missing tools listed (no languages detected).
    assert _missing_tools(tmp_path, only=None, exclude=set()) == []


def test_missing_tools_only_reports_applicable_language_tools(tmp_path: Path, monkeypatch):
    reg = ToolRegistry()

    class _MissingPython(Tool):
        name = "missing-python"
        category = Category.LINT
        languages = ["python"]

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return False

        def run(self, repo):
            return []

    class _MissingGo(Tool):
        name = "missing-go"
        category = Category.LINT
        languages = ["go"]

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return False

        def run(self, repo):
            return []

    reg.register(_MissingPython)
    reg.register(_MissingGo)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    from polycheck.cli import _missing_tools

    missing = _missing_tools(tmp_path, only=None, exclude=set())
    assert [cls.name for cls in missing] == ["missing-python"]


def test_doctor_exits_zero_by_default_when_tools_missing(monkeypatch):
    from typer.testing import CliRunner

    from polycheck.cli import app

    reg = ToolRegistry()

    class _MissingPython(Tool):
        name = "missing-python"
        category = Category.LINT
        languages = ["python"]

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return False

        def run(self, repo):
            return []

    reg.register(_MissingPython)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "missing-python" in result.output


def test_doctor_fail_on_missing_exits_one(monkeypatch):
    from typer.testing import CliRunner

    from polycheck.cli import app

    reg = ToolRegistry()

    class _MissingPython(Tool):
        name = "missing-python"
        category = Category.LINT
        languages = ["python"]

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return False

        def run(self, repo):
            return []

    reg.register(_MissingPython)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(app, ["doctor", "--fail-on-missing"])
    assert result.exit_code == 1
    assert "missing-python" in result.output
