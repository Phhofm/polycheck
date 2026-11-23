"""Tests for the baseline and --diff CLI flow (hermetic, stub tools)."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from polycheck.finding import Category, Finding, Severity
from polycheck.registry import ToolRegistry
from polycheck.tools.base import Tool


class _StubTool(Tool):
    """Two stable findings; fingerprints depend only on rule/line."""

    name = "stub"
    category = Category.LINT
    languages = []
    universal = True

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return [
            self._finding("F401", 1),
            self._finding("F821", 2),
        ]

    @staticmethod
    def _finding(rule: str, line: int) -> Finding:
        return Finding(
            tool="stub", rule=rule, severity=Severity.MEDIUM,
            category=Category.LINT, message=f"{rule}", file="a.py", line=line,
        )


def _register(monkeypatch) -> None:
    reg = ToolRegistry()
    reg.register(_StubTool)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)


def test_baseline_writes_fingerprint_file(tmp_path: Path, monkeypatch):
    _register(monkeypatch)
    result = CliRunner().invoke(
        _app(), ["baseline", str(tmp_path), "--tool", "stub"]
    )

    assert result.exit_code == 0, result.output
    path = tmp_path / "polycheck-reports" / "polycheck-baseline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["fingerprints"]) == 2
    assert "2 findings" in result.output


def test_diff_reports_nothing_new_when_unchanged(tmp_path: Path, monkeypatch):
    _register(monkeypatch)
    app = _app()
    assert CliRunner().invoke(app, ["baseline", str(tmp_path), "--tool", "stub"]).exit_code == 0

    result = CliRunner().invoke(
        app, ["run", str(tmp_path), "--diff", "--tool", "stub"]
    )

    assert result.exit_code == 0, result.output
    assert "0 new" in result.output


def test_diff_reports_new_finding_when_code_grew(tmp_path: Path, monkeypatch):
    _register(monkeypatch)
    app = _app()
    assert CliRunner().invoke(app, ["baseline", str(tmp_path), "--tool", "stub"]).exit_code == 0

    class _Grown(_StubTool):
        def run(self, repo):
            return _StubTool.run(self, repo) + [self._finding("E501", 3)]

    reg = ToolRegistry()
    reg.register(_Grown)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(
        app, ["run", str(tmp_path), "--diff", "--tool", "stub"]
    )

    assert result.exit_code == 1, result.output  # new MEDIUM finding → fails gate
    assert "1 new" in result.output


def test_diff_without_baseline_reports_all_with_hint(tmp_path: Path, monkeypatch):
    _register(monkeypatch)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--diff", "--tool", "stub"]
    )

    assert result.exit_code == 1  # 2 MEDIUM findings, no baseline
    assert "no baseline" in result.output


def test_suppress_removes_finding_from_run(tmp_path: Path, monkeypatch):
    _register(monkeypatch)
    (tmp_path / ".polycheck.yml").write_text("suppress:\n  - F401\n")

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--tool", "stub"]
    )

    assert result.exit_code == 1  # F821 alone still fails the MEDIUM gate
    report = json.loads(
        (tmp_path / "polycheck-reports" / "polycheck-report.json")
        .read_text(encoding="utf-8")
    )
    rules = [f["rule"] for f in report["findings"]]
    assert rules == ["F821"]


def _app():
    from polycheck.cli import app
    return app
