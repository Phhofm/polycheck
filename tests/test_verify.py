"""Tests for supported-tool verification."""
from __future__ import annotations

from pathlib import Path

from polycheck.finding import Category, Finding, Severity
from polycheck.registry import ToolRegistry
from polycheck.tools.base import Tool
from polycheck.verify import verify_tools


class _InstalledTool(Tool):
    name = "installed"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return []


class _MissingTool(Tool):
    name = "missing"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def run(self, repo):
        raise AssertionError("missing tools should not run")


class _ErrorTool(Tool):
    name = "error"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        raise RuntimeError("boom")


def test_verify_tools_reports_installed_missing_and_errors(tmp_path: Path):
    reg = ToolRegistry()
    reg.register(_InstalledTool)
    reg.register(_MissingTool)
    reg.register(_ErrorTool)

    results = verify_tools(reg, work_dir=tmp_path)
    by_tool = {result.tool: result for result in results}

    assert by_tool["installed"].status == "no-findings"
    assert by_tool["installed"].installed is True
    assert by_tool["missing"].status == "skipped-not-installed"
    assert by_tool["missing"].installed is False
    assert by_tool["error"].status == "error"
    assert "RuntimeError: boom" in by_tool["error"].message


def test_verify_tools_filters_selected_tools(tmp_path: Path):
    reg = ToolRegistry()
    reg.register(_InstalledTool)
    reg.register(_MissingTool)

    results = verify_tools(reg, tools=["missing"], work_dir=tmp_path)

    assert [result.tool for result in results] == ["missing"]
    assert results[0].status == "skipped-not-installed"


class _SilentRuff(Tool):
    """Runs clean on a repo that is seeded with a defect it must catch."""

    name = "ruff"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return []


class _WorkingRuff(Tool):
    name = "ruff"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return [
            Finding(
                tool="ruff", rule="F401", severity=Severity.LOW,
                category=Category.LINT, message="unused import",
                file="app.py", line=1,
            ),
        ]


class _QuietTool(Tool):
    """No seeded-defect expectation registered for this name."""

    name = "quiet-unknown"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return []


def test_verify_flags_tool_that_misses_seeded_defect(tmp_path: Path):
    reg = ToolRegistry()
    reg.register(_SilentRuff)

    results = verify_tools(reg, work_dir=tmp_path)

    assert results[0].status == "missed-defects"
    assert "seeded" in results[0].message


def test_verify_passes_tool_that_finds_seeded_defect(tmp_path: Path):
    reg = ToolRegistry()
    reg.register(_WorkingRuff)

    results = verify_tools(reg, work_dir=tmp_path)

    assert results[0].status == "ok"
    assert results[0].findings == 1


def test_verify_keeps_no_findings_for_tools_without_expectation(tmp_path: Path):
    reg = ToolRegistry()
    reg.register(_QuietTool)

    results = verify_tools(reg, work_dir=tmp_path)

    assert results[0].status == "no-findings"
