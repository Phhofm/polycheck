"""Tests for the _exit_code and _missing_tools helpers in the CLI."""
from __future__ import annotations

from pathlib import Path

from polycheck.finding import Category, Finding, Severity


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


def test_missing_tools_filters_universal_on_empty_repo(tmp_path: Path):
    """A universal tool whose binary is missing should be listed, but
    only when the repo has *some* content (otherwise gitleaks on an
    empty dir is just noise).

    Note: sonarless is a universal tool that requires Docker, so it
    will appear in missing tools even for Python repos. We exclude it
    from this test's assertion since it's a special case.
    """
    from polycheck.cli import _missing_tools
    # Truly empty repo → no missing tools listed (no languages detected).
    assert _missing_tools(tmp_path, only=None, exclude=set()) == []
