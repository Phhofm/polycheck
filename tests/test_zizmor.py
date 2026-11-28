"""Tests for the zizmor adapter — real run against a seeded workflow
(zizmor is pipx-installed on this machine and in CI's tool job)."""
from __future__ import annotations

from pathlib import Path

import pytest

from polycheck.config import Config
from polycheck.finding import Severity
from polycheck.tools.zizmor import ZizmorTool


def _seed(tmp_path: Path) -> Path:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "name: ci\n"
        "on: push\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    return tmp_path


def test_zizmor_not_applicable_without_workflows(tmp_path: Path):
    assert ZizmorTool(config=Config()).is_applicable(tmp_path) is False


@pytest.mark.skipif(
    __import__("shutil").which("zizmor") is None,
    reason="zizmor not installed",
)
def test_zizmor_flags_unpinned_action_ref(tmp_path: Path):
    findings = ZizmorTool(config=Config()).run(_seed(tmp_path))

    rules = {f.rule for f in findings}
    assert "unpinned-uses" in rules or "artipacked" in rules, rules
    for f in findings:
        assert f.file and f.file.startswith(".github/workflows/")
        assert f.line and f.line >= 1
    severities = {f.severity for f in findings}
    assert severities <= {Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO}
