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


def test_markdown_caps_repeated_rule_examples(tmp_path: Path):
    """One rule repeated many times is one insight: the report shows a
    bounded number of example rows plus an exact hidden count."""
    findings = [
        Finding(tool="ruff", rule="E501", severity=Severity.LOW,
                category=Category.LINT, message=f"line too long {i}",
                file=f"f{i}.py", line=i)
        for i in range(20)
    ]
    results = [ToolResult(tool="ruff", status="ok", findings=findings,
                          duration_sec=0.1)]

    written = render("markdown", tmp_path, findings, results,
                     report_dir=tmp_path / "out")
    text = written[0].read_text(encoding="utf-8")

    rows = [
        row for row in text.splitlines()
        if row.startswith("| LOW ") and "`ruff`" in row and "`E501`" in row
    ]
    assert len(rows) == 5  # per-rule example cap
    assert "and 15 more" in text


def test_markdown_shows_distinct_rules_beyond_five(tmp_path: Path):
    """The cap is per rule, not per category: six distinct rules all show."""
    findings = [
        Finding(tool="ruff", rule=f"E50{i}", severity=Severity.LOW,
                category=Category.LINT, message=f"issue {i}",
                file="a.py", line=i)
        for i in range(6)
    ]
    results = [ToolResult(tool="ruff", status="ok", findings=findings,
                          duration_sec=0.1)]

    written = render("markdown", tmp_path, findings, results,
                     report_dir=tmp_path / "out")
    text = written[0].read_text(encoding="utf-8")

    for i in range(6):
        assert f"E50{i}" in text
    assert "and 0 more" not in text


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


# --- coverage (0.3.14) ---------------------------------------------------------


def _coverage(complete: bool) -> dict:
    return {
        "profile": "deep",
        "complete": complete,
        "candidates": 2,
        "ran": 1,
        "tools": [
            {"name": "ruff", "status": "ran"},
            {
                "name": "sonarless",
                "status": "missing",
                "reason": "not installed",
                "executor": "human",
                "install_hint": "curl -sSL https://example.com/install.sh | bash",
            },
        ],
    }


def test_markdown_incomplete_coverage_banner(tmp_path: Path):
    written = render("markdown", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out", coverage=_coverage(False))
    text = written[0].read_text(encoding="utf-8")

    assert "DEEP SCAN INCOMPLETE" in text
    assert "sonarless" in text
    assert "install (human)" in text
    assert "example.com/install.sh" in text
    assert "## Coverage" in text


def test_markdown_complete_coverage_has_no_banner(tmp_path: Path):
    written = render("markdown", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out", coverage=_coverage(True))
    text = written[0].read_text(encoding="utf-8")

    assert "INCOMPLETE" not in text
    assert "## Coverage" in text
    assert "complete" in text


def test_json_reporter_embeds_coverage(tmp_path: Path):
    written = render("json", tmp_path, _findings(), _results(),
                     report_dir=tmp_path / "out", coverage=_coverage(False))
    payload = json.loads(written[0].read_text(encoding="utf-8"))

    assert payload["coverage"]["complete"] is False
    assert payload["coverage"]["profile"] == "deep"


def test_reporters_unchanged_without_coverage(tmp_path: Path):
    md = render("markdown", tmp_path, _findings(), _results(),
                report_dir=tmp_path / "md")
    payload = json.loads(render("json", tmp_path, _findings(), _results(),
                                report_dir=tmp_path / "js")[0].read_text(encoding="utf-8"))

    assert "Coverage" not in md[0].read_text(encoding="utf-8")
    assert "coverage" not in payload
