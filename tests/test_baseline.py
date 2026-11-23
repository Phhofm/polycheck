"""Tests for the findings baseline (diff mode)."""
from __future__ import annotations

import json
from pathlib import Path

from polycheck.finding import Category, Finding, Severity
from polycheck.runner import load_baseline, save_baseline


def _finding(rule: str, line: int) -> Finding:
    return Finding(
        tool="t", rule=rule, severity=Severity.MEDIUM,
        category=Category.LINT, message=f"{rule}", file="a.py", line=line,
    )


def test_save_then_load_roundtrip(tmp_path: Path):
    findings = [_finding("F401", 1), _finding("F821", 2)]

    path = save_baseline(tmp_path, findings)
    loaded = load_baseline(tmp_path)

    assert path.exists()
    assert path.name == "polycheck-baseline.json"
    assert loaded == {f.fingerprint() for f in findings}


def test_save_baseline_is_stable_and_sorted(tmp_path: Path):
    findings = [_finding("F821", 2), _finding("F401", 1)]

    path = save_baseline(tmp_path, findings)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    assert data["fingerprints"] == sorted(data["fingerprints"])
    assert data["created_at"]


def test_load_baseline_missing_returns_none(tmp_path: Path):
    assert load_baseline(tmp_path) is None


def test_load_baseline_malformed_returns_none(tmp_path: Path):
    (tmp_path / "polycheck-baseline.json").write_text("{not json", encoding="utf-8")

    assert load_baseline(tmp_path) is None


def test_load_baseline_wrong_shape_returns_none(tmp_path: Path):
    (tmp_path / "polycheck-baseline.json").write_text(
        json.dumps({"fingerprints": "nope"}), encoding="utf-8"
    )

    assert load_baseline(tmp_path) is None


def test_save_overwrites_previous_baseline(tmp_path: Path):
    save_baseline(tmp_path, [_finding("F401", 1)])
    save_baseline(tmp_path, [_finding("F821", 2)])

    loaded = load_baseline(tmp_path)

    assert loaded == {_finding("F821", 2).fingerprint()}
