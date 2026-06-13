"""Tests for the Finding schema.

These run without subprocesses — pure unit tests.
"""
from __future__ import annotations

from polycheck.finding import Category, Finding, Severity, fingerprint


def test_severity_ordering():
    assert Severity.CRITICAL > Severity.HIGH > Severity.MEDIUM > Severity.LOW > Severity.INFO
    assert Severity.HIGH >= Severity.HIGH
    assert Severity.LOW >= Severity.INFO


def test_finding_roundtrip():
    f = Finding(
        tool="ruff",
        rule="I001",
        severity=Severity.LOW,
        category=Category.LINT,
        message="Imports are unsorted.",
        file="src/foo.py",
        line=12,
        column=1,
        fixable=True,
        doc_url="https://docs.astral.sh/ruff/rules/i001",
    )
    blob = f.to_dict()
    again = Finding.from_dict(blob)
    assert again == f


def test_fingerprint_stable():
    a = Finding(
        tool="ruff", rule="I001", severity=Severity.LOW,
        category=Category.LINT, message="x", file="a.py", line=10, column=0,
    )
    b = Finding(
        tool="ruff", rule="I001", severity=Severity.HIGH,    # severity doesn't affect fp
        category=Category.LINT, message="different message",  # message doesn't either
        file="a.py", line=10, column=0,
    )
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_different_rule():
    a = Finding(tool="ruff", rule="I001", severity=Severity.LOW,
                category=Category.LINT, message="x", file="a.py", line=10)
    b = Finding(tool="ruff", rule="F401", severity=Severity.LOW,
                category=Category.LINT, message="x", file="a.py", line=10)
    assert a.fingerprint() != b.fingerprint()


def test_helper_fingerprint_matches_instance():
    f = Finding(
        tool="mypy", rule="attr-defined", severity=Severity.HIGH,
        category=Category.TYPE, message="x", file="a.py", line=42, column=0,
    )
    assert fingerprint(f.tool, f.rule, f.file, f.line, f.column or 0) == f.fingerprint()


def test_severity_from_str_unknown():
    # Unknown strings map to MEDIUM so we never crash the report.
    assert Severity.from_str("FOO") == Severity.MEDIUM
    assert Severity.from_str("high") == Severity.HIGH
    assert Severity.from_str("CRITICAL") == Severity.CRITICAL
    assert Severity.from_str("BLOCKER") == Severity.CRITICAL
    assert Severity.from_str("NOTE") == Severity.INFO


def test_category_values_unique():
    values = [c.value for c in Category]
    assert len(values) == len(set(values))
