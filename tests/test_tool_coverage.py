"""Tests for the coverage adapter — the test-coverage signal no static
tool sees. Runs a real mini-suite (coverage + pytest are in the dev
extra), so these tests prove the full path: run suite → parse JSON →
findings + metrics.
"""
from __future__ import annotations

from pathlib import Path

from polycheck.config import Config
from polycheck.finding import Severity
from polycheck.profiles import is_skipped, resolve_profile
from polycheck.tools.coverage import CoverageTool


def _mini_repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fx'\n")
    (tmp_path / "app.py").write_text("def covered():\n    return 1\n")
    (tmp_path / "util.py").write_text("def never_called():\n    return 2\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(
        "from app import covered\n\n\ndef test_covered():\n    assert covered() == 1\n"
    )
    return tmp_path


def test_coverage_is_deep_only():
    tool_cls = CoverageTool
    assert is_skipped(tool_cls, None) is True  # default scan: too slow
    assert is_skipped(tool_cls, resolve_profile("pr")) is True
    assert is_skipped(tool_cls, resolve_profile("deep")) is False


def test_coverage_reports_untested_module_as_medium(tmp_path: Path):
    tool = CoverageTool(config=Config())
    findings = tool.run(_mini_repo(tmp_path))

    uncovered = [f for f in findings if f.file == "util.py"]
    assert uncovered, f"util.py must be flagged: {findings}"
    assert uncovered[0].severity == Severity.MEDIUM
    assert "untested module" in uncovered[0].message

    covered = [f for f in findings if f.file == "app.py"]
    assert not covered, "fully covered module must not be flagged"

    metrics = getattr(tool, "scan_metrics", {})
    assert 0 < metrics["coverage_percent"] < 100
    assert metrics["files_uncovered"] >= 1


def test_coverage_survives_failing_tests(tmp_path: Path):
    """Test failures are pytest's business; coverage still measures."""
    repo = _mini_repo(tmp_path)
    test = repo / "tests" / "test_app.py"
    test.write_text(
        "from app import covered\n\n\ndef test_covered():\n    assert covered() == 1\n"
        "\n\ndef test_broken():\n    assert 1 == 2\n"
    )
    tool = CoverageTool(config=Config())
    findings = tool.run(repo)

    assert [f for f in findings if f.file == "util.py"], findings


def test_coverage_not_applicable_without_tests(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fx'\n")
    tool = CoverageTool(config=Config())
    assert tool.is_applicable(tmp_path) is False
