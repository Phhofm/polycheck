"""Feedback fixes from the external live test (0.3.7 work block).

An LLM reviewer ran a complete reviewer loop in another repo and found:
installed-but-not-applicable tools were invisible in the run table (a
deep run showed 9 tools while tach/pip-audit/dependency-cruiser were
installed-but-skipped silently — understanding why required a doctor
cross-check). These tests pin the fix: the run shows every eligible
tool that did NOT run, with the reason when the adapter can state one.
"""
from __future__ import annotations

from pathlib import Path

from polycheck.config import Config
from polycheck.finding import Category
from polycheck.registry import ToolRegistry
from polycheck.runner import Runner
from polycheck.tools.base import Tool


class _FastTool(Tool):
    name = "fast-stub"
    category = Category.LINT
    languages = []
    universal = True

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return []


class _NotApplicableTool(_FastTool):
    name = "needs-manifest"

    def is_applicable(self, repo):
        return False

    def not_applicable_reason(self, repo):
        return "no demo manifest"


def _runner(tmp_path: Path, *classes: type[Tool]) -> Runner:
    reg = ToolRegistry()
    for cls in classes:
        reg.register(cls)
    return Runner(repo=tmp_path, config=Config(), registry=reg)


def test_runner_reports_installed_but_not_applicable_with_reason(tmp_path: Path):
    runner = _runner(tmp_path, _FastTool, _NotApplicableTool)

    findings, results = runner.run()

    rows = [r for r in results if r.status == "not-applicable"]
    assert len(rows) == 1
    assert rows[0].tool == "needs-manifest"
    assert rows[0].message == "no demo manifest"
    assert rows[0].findings == []


def test_not_applicable_without_reason_gets_empty_message(tmp_path: Path):
    class _Silent(_NotApplicableTool):
        name = "silent-skip"

        def not_applicable_reason(self, repo):
            return None

    runner = _runner(tmp_path, _Silent)

    _, results = runner.run()

    assert results[0].status == "not-applicable"
    assert results[0].message == ""


def test_not_applicable_respects_tools_and_profile_filters(tmp_path: Path):
    from polycheck.profiles import resolve_profile

    class _Heavy(_NotApplicableTool):
        name = "pip-audit"  # a HEAVY_TOOLS name

    runner = _runner(tmp_path, _Heavy)

    # tools= filter: requested but not applicable → row must still show.
    _, results = runner.run(tools=["pip-audit"])
    assert [r.status for r in results] == ["not-applicable"]

    # pr profile skips heavy tools entirely → no not-applicable row.
    _, results = runner.run(profile=resolve_profile("pr"))
    assert results == []


def test_run_table_shows_not_applicable_row(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from polycheck.cli import app

    reg = ToolRegistry()
    reg.register(_FastTool)
    reg.register(_NotApplicableTool)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(app, ["run", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "not-applicable" in result.output
    assert "no demo manifest" in result.output
