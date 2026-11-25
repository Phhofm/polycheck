"""Scan-level metrics (SlopCodeBench composites) — 0.3.8.

External live test #4 asked for the SlopCodeBench composites as
first-class report metadata so agent-driven codebases become trendable
("did the codebase stay stable under the skill?"). The scb-check CLI
emits them via `scb-check check <path> --report` (verified on real
output); the adapter publishes them through the `scan_metrics` hook and
the JSON report carries them under a top-level `metrics` key.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from polycheck.config import Config
from polycheck.finding import Category
from polycheck.registry import ToolRegistry
from polycheck.runner import Runner, ToolResult
from polycheck.tools.base import Tool

# Verbatim `scb-check check . --report` payload (0.3.7-era scb-check).
_REPORT_PAYLOAD = {
    "verbosity": 0.4,
    "erosion": 0.0,
    "cog_erosion": 0.0,
    "files_scanned": 1,
    "total_loc": 5,
    "verbosity_flagged_loc": 2,
    "clone_loc": 0,
    "ast_grep_flagged_loc": 2,
    "structural_rule_loc": 0,
    "structural_rule_findings": 0,
    "total_functions": 1,
    "high_cc_functions": 0,
    "high_cog_functions": 0,
    "total_mass": 6.0,
    "high_cc_mass": 0.0,
    "total_cog_mass": 5.0,
    "high_cog_mass": 0.0,
    "syntax_tree_count": 1,
    "syntax_node_count": 20,
    "syntax_by_language": {"python": {"files": 1, "nodes": 20}},
}

_HUMAN_OUTPUT = (
    "warning[for-range-len]: `for i in range(len(x))` - use `enumerate(x)` or iterate `x` directly\n"
    "  ┌─ a.py:3:5\n"
)


class _MetricsTool(Tool):
    name = "metrics-stub"
    category = Category.LINT
    languages = []
    universal = True

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        self.scan_metrics = {"verbosity": 0.4, "erosion": 0.0}
        return []


def test_runner_copies_scan_metrics_into_tool_result(tmp_path: Path):
    reg = ToolRegistry()
    reg.register(_MetricsTool)

    runner = Runner(repo=tmp_path, config=Config(), registry=reg)
    _, results = runner.run()

    assert results[0].metrics == {"verbosity": 0.4, "erosion": 0.0}


def test_tool_without_metrics_gets_empty_dict(tmp_path: Path):
    class _Plain(Tool):
        name = "plain-stub"
        category = Category.LINT
        languages = []
        universal = True

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return True

        def run(self, repo):
            return []

    reg = ToolRegistry()
    reg.register(_Plain)

    runner = Runner(repo=tmp_path, config=Config(), registry=reg)
    _, results = runner.run()

    assert results[0].metrics == {}


def test_scb_check_publishes_composites_from_report_run(
    monkeypatch, tmp_path: Path,
):
    """One scan, two invocations: the human run feeds the battle-tested
    finding parser, the --report run feeds the composites."""
    from polycheck.tools.scb_check import ScbCheckTool

    captured: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        if "--report" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps(_REPORT_PAYLOAD), stderr="",
            )
        return subprocess.CompletedProcess(
            cmd, 1, stdout=_HUMAN_OUTPUT, stderr="",
        )

    monkeypatch.setattr(
        "polycheck.tools.scb_check.shutil.which",
        lambda name: "/usr/local/bin/scb-check" if name == "scb-check" else None,
    )
    monkeypatch.setattr("polycheck.tools.scb_check.subprocess.run", fake_run)

    tool = ScbCheckTool()
    findings = tool.run(tmp_path)

    assert len(findings) == 1  # the human parser is untouched
    assert len(captured) == 2
    assert "--report" in captured[1]
    assert tool.scan_metrics is not None
    assert tool.scan_metrics["verbosity"] == 0.4
    assert tool.scan_metrics["erosion"] == 0.0
    assert tool.scan_metrics["files_scanned"] == 1


def test_scb_check_survives_a_failed_report_run(monkeypatch, tmp_path: Path):
    """Metrics are additive: a failed --report invocation must never
    break the findings of the scan."""
    from polycheck.tools.scb_check import ScbCheckTool

    def fake_run(cmd, **kwargs):
        if "--report" in cmd:
            raise subprocess.TimeoutExpired(cmd, 600)
        return subprocess.CompletedProcess(cmd, 1, stdout=_HUMAN_OUTPUT, stderr="")

    monkeypatch.setattr(
        "polycheck.tools.scb_check.shutil.which",
        lambda name: "/usr/local/bin/scb-check" if name == "scb-check" else None,
    )
    monkeypatch.setattr("polycheck.tools.scb_check.subprocess.run", fake_run)

    tool = ScbCheckTool()
    findings = tool.run(tmp_path)

    assert len(findings) == 1
    assert tool.scan_metrics is None


# --- reporters ----------------------------------------------------------------


def _report_inputs(tmp_path: Path) -> tuple[list, list[ToolResult]]:
    from polycheck.finding import Finding, Severity

    f = Finding(
        tool="scb-check", rule="for-range-len", severity=Severity.LOW,
        category=Category.LINT, message="slop", file="a.py", line=3,
    )
    result = ToolResult(
        tool="scb-check", status="ok", findings=[f], duration_sec=0.5,
        metrics={"verbosity": 0.4, "erosion": 0.0},
    )
    return [f], [result]


def test_json_report_embeds_metrics(tmp_path: Path):
    from polycheck.reporters.json_reporter import render

    findings, results = _report_inputs(tmp_path)
    render(tmp_path, findings, results, report_dir=tmp_path)

    report = json.loads((tmp_path / "polycheck-report.json").read_text())
    assert report["metrics"]["scb-check"]["verbosity"] == 0.4
    assert report["metrics"]["scb-check"]["erosion"] == 0.0


def test_json_report_omits_metrics_when_none(tmp_path: Path):
    from polycheck.reporters.json_reporter import render

    findings, _ = _report_inputs(tmp_path)
    render(tmp_path, findings, [], report_dir=tmp_path)

    report = json.loads((tmp_path / "polycheck-report.json").read_text())
    assert "metrics" not in report


def test_markdown_report_shows_metrics(tmp_path: Path):
    from polycheck.reporters.markdown_reporter import render

    findings, results = _report_inputs(tmp_path)
    render(tmp_path, findings, results, report_dir=tmp_path)

    md = (tmp_path / "polycheck-report.md").read_text()
    assert "Scan metrics" in md
    assert "verbosity" in md


# --- portable npx/npm spawning (0.3.8, windows CI finding) -------------------


def test_npx_command_routes_through_cmd_exe_on_windows(monkeypatch):
    """Windows: npm's shims are .cmd files CreateProcess cannot execute
    directly (WinError 2 in the smoke test) — route through cmd.exe."""
    import os

    from polycheck.tools.base import npx_command

    monkeypatch.setattr(os, "name", "nt")
    assert npx_command() == ["cmd", "/c", "npx"]

    monkeypatch.setattr(os, "name", "posix")
    assert npx_command() == ["npx"]


def test_npm_command_routes_through_cmd_exe_on_windows(monkeypatch):
    import os

    from polycheck.tools.base import npm_command

    monkeypatch.setattr(os, "name", "nt")
    assert npm_command() == ["cmd", "/c", "npm"]

    monkeypatch.setattr(os, "name", "posix")
    assert npm_command() == ["npm"]
