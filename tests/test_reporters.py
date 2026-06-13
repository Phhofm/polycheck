"""Tests for the reporters.

These check that the JSON reporter produces a well-shaped envelope
and that the markdown reporter has the expected sections.
"""
from __future__ import annotations

import json
from pathlib import Path

from polycheck.finding import Category, Finding, Severity
from polycheck.reporters import render
from polycheck.runner import ToolResult


def _findings():
    return [
        Finding(tool="ruff", rule="I001", severity=Severity.LOW,
                category=Category.LINT, message="imports unsorted",
                file="a.py", line=10, column=1, fixable=True),
        Finding(tool="mypy", rule="attr-defined", severity=Severity.HIGH,
                category=Category.TYPE, message="x has no attribute y",
                file="b.py", line=20, column=5),
    ]


def _results():
    return [
        ToolResult(tool="ruff", status="ok", findings=_findings()[:1],
                   duration_sec=0.1),
        ToolResult(tool="mypy", status="ok", findings=_findings()[1:],
                   duration_sec=0.2),
    ]


def test_json_reporter(tmp_path: Path):
    written = render("json", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out")
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["summary"]["total_findings"] == 2
    assert "ruff" in payload["summary"]["by_tool"]
    assert "mypy" in payload["summary"]["by_tool"]
    # Findings preserve tool/rule/severity/category.
    ruff = next(f for f in payload["findings"] if f["tool"] == "ruff")
    assert ruff["rule"] == "I001"
    assert ruff["severity"] == "LOW"


def test_markdown_reporter(tmp_path: Path):
    written = render("markdown", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out")
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "# polycheck report" in text
    assert "## By severity" in text
    assert "## By category" in text
    assert "## Tool execution" in text
    assert "## lint" in text
    assert "## type" in text
    assert "I001" in text
    assert "attr-defined" in text


def test_sarif_reporter(tmp_path: Path):
    written = render("sarif", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out")
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["version"] == "2.1.0"
    assert len(payload["runs"]) == 1
    run = payload["runs"][0]
    assert run["tool"]["driver"]["name"] == "polycheck"
    assert len(run["results"]) == 2
    # Each result has a level, message, and (when known) a physical location.
    ruff = next(r for r in run["results"] if r["ruleId"] == "ruff/I001")
    assert ruff["level"] == "note"
    assert ruff["locations"][0]["physicalLocation"]["region"]["startLine"] == 10


def test_unknown_format_is_noop(tmp_path: Path):
    written = render("pdf", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out")
    assert written == []
