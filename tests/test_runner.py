"""Tests for the runner's filtering logic.

We don't run real tools here — we just verify that the runner
correctly handles enable/disable lists, applicability, and result
shapes. Real tool subprocesses are exercised in the smoke test.
"""
from __future__ import annotations

from pathlib import Path

from polycheck.config import Config
from polycheck.finding import Category, Finding, Severity
from polycheck.runner import dedupe, filter_by_severity, group_by_category
from polycheck.tools.base import Tool


class _StubTool(Tool):
    name = "stub"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return [
            Finding(
                tool="stub", rule="X1", severity=Severity.HIGH,
                category=Category.LINT, message="real", file="a.py", line=1,
            ),
            Finding(
                tool="stub", rule="X1", severity=Severity.HIGH,
                category=Category.LINT, message="dup", file="a.py", line=1,
            ),
            Finding(
                tool="stub", rule="X2", severity=Severity.INFO,
                category=Category.LINT, message="info", file="a.py", line=2,
            ),
        ]


def test_dedupe_collapses_fingerprints():
    f1 = Finding(tool="t", rule="r", severity=Severity.HIGH,
                 category=Category.LINT, message="a", file="x", line=1)
    f2 = Finding(tool="t", rule="r", severity=Severity.LOW,
                 category=Category.LINT, message="b", file="x", line=1)
    out = dedupe([f1, f2])
    assert len(out) == 1
    # The first one wins; severity doesn't affect fingerprint.
    assert out[0].message == "a"


def test_filter_by_severity_threshold():
    f_high = Finding(tool="t", rule="r", severity=Severity.HIGH,
                     category=Category.LINT, message="", file="x", line=1)
    f_low = Finding(tool="t", rule="r", severity=Severity.LOW,
                    category=Category.LINT, message="", file="x", line=2)
    f_info = Finding(tool="t", rule="r", severity=Severity.INFO,
                     category=Category.LINT, message="", file="x", line=3)
    out = filter_by_severity([f_high, f_low, f_info], "MEDIUM")
    assert out == [f_high]
    out = filter_by_severity([f_high, f_low, f_info], "INFO")
    assert len(out) == 3
    out = filter_by_severity([f_high, f_low, f_info], "BOGUS")
    assert len(out) == 3  # unknown threshold → no filtering


def test_group_by_category():
    f1 = Finding(tool="t", rule="r", severity=Severity.HIGH,
                 category=Category.SECURITY, message="", file="x", line=1)
    f2 = Finding(tool="t", rule="r", severity=Severity.HIGH,
                 category=Category.LINT, message="", file="x", line=2)
    out = group_by_category([f1, f2])
    assert Category.SECURITY in out
    assert Category.LINT in out
    assert f1 in out[Category.SECURITY]


def test_runner_picks_up_stub(tmp_path: Path):
    """The runner should at least be able to drive a stub tool end-to-end."""
    from polycheck.registry import ToolRegistry
    from polycheck.runner import Runner

    # Make the dir "look like Python" so the language detector picks it up.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    reg = ToolRegistry()
    reg.register(_StubTool)
    cfg = Config()
    runner = Runner(repo=tmp_path, config=cfg, registry=reg)
    findings, results = runner.run()
    assert len(findings) == 3
    assert results[0].status == "ok"
    assert results[0].tool == "stub"


def test_runner_marks_errors(tmp_path: Path):
    class _Boom(Tool):
        name = "boom"
        category = Category.LINT
        languages = ["python"]

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return True

        def run(self, repo):
            raise RuntimeError("kaboom")

    from polycheck.registry import ToolRegistry
    from polycheck.runner import Runner

    # Create a Python file so the language is detected
    (tmp_path / "test.py").write_text("x = 1\n")

    reg = ToolRegistry()
    reg.register(_Boom)
    runner = Runner(repo=tmp_path, config=Config(), registry=reg)
    findings, results = runner.run()
    assert findings == []
    assert results[0].status == "error"
    assert "kaboom" in (results[0].error or "")


def _finding(rule: str, file: str = "a.py", line: int = 1) -> Finding:
    return Finding(
        tool="t", rule=rule, severity=Severity.MEDIUM,
        category=Category.LINT, message=f"{rule} in {file}:{line}",
        file=file, line=line,
    )


def test_apply_suppressions_rule_only():
    from polycheck.runner import apply_suppressions

    f1 = _finding("F401")
    f2 = _finding("F821")
    out = apply_suppressions([f1, f2], ["F401"])

    assert out == [f2]


def test_apply_suppressions_rule_at_file():
    from polycheck.runner import apply_suppressions

    f1 = _finding("SC2086", file="script.sh")
    f2 = _finding("SC2086", file="other.sh")
    out = apply_suppressions([f1, f2], ["SC2086@script.sh"])

    assert out == [f2]


def test_apply_suppressions_file_match_ignores_fileless():
    """A finding without a file cannot match a rule@file suppression."""
    from polycheck.runner import apply_suppressions

    f1 = _finding("F401")
    f1.file = None
    assert apply_suppressions([f1], ["F401@a.py"]) == [f1]


def test_apply_suppressions_empty_pattern_list_is_identity():
    from polycheck.runner import apply_suppressions

    findings = [_finding("F401"), _finding("F821")]
    assert apply_suppressions(findings, []) == findings
    assert apply_suppressions(findings, ["  "]) == findings


def test_filter_by_baseline_keeps_only_new():
    from polycheck.runner import filter_by_baseline

    known = _finding("F401", line=1)
    new = _finding("F401", line=2)
    baseline = {known.fingerprint()}

    assert filter_by_baseline([known, new], baseline) == [new]


def test_filter_by_baseline_none_is_identity():
    from polycheck.runner import filter_by_baseline

    findings = [_finding("F401")]
    assert filter_by_baseline(findings, None) == findings
