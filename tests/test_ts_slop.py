"""ts-slop adapter tests — shapes captured from real ast-grep 0.51.3.

polycheck's own slop rule set for TypeScript (scb-check 0.2.0 is
197/197 python rules and its extra-rules env mechanism does not reach
the analysis pipeline — verified in source). The adapter ships its
rules as package data and runs ast-grep via the local binary or the
npx fallback (`npx -p @ast-grep/cli ast-grep`, the package name form —
`npx ast-grep` cannot resolve the bin).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from polycheck.finding import Category, Severity
from polycheck.tools.base import npx_command
from polycheck.tools.ts_slop import TsSlopTool

# Verbatim hit from `ast-grep scan --rule ts_slop_rules.yaml --json`
# (0.51.3) on a seeded `x as unknown as User` defect.
_REAL_HIT = {
    "text": "x as unknown as User",
    "range": {
        "byteOffset": {"start": 10, "end": 30},
        "start": {"line": 0, "column": 10},
        "end": {"line": 0, "column": 30},
    },
    "file": "src/sloppy.ts",
    "lines": "const u = x as unknown as User;\n",
    "charCount": {"leading": 10, "trailing": 1},
    "language": "TypeScript",
    "metaVariables": {"single": {"X": {"text": "x"}}},
    "ruleId": "ts-as-unknown-as",
    "severity": "error",
    "message": "double cast `as unknown as T` - fix the type instead",
}


def test_is_applicable_requires_typescript_source(tmp_path: Path):
    assert not TsSlopTool().is_applicable(tmp_path)
    (tmp_path / "service.ts").write_text("export const x = 1;\n")
    assert TsSlopTool().is_applicable(tmp_path)


def test_is_installed_accepts_npx_fallback(monkeypatch):
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.shutil.which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )
    assert TsSlopTool().is_installed() is True


def test_parses_real_hit_shape(monkeypatch, tmp_path: Path):
    (tmp_path / "service.ts").write_text("x\n")
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.shutil.which",
        lambda name: "/usr/bin/ast-grep" if name == "ast-grep" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 1, stdout=json.dumps([_REAL_HIT]), stderr="",
        ),
    )

    findings = TsSlopTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "ts-slop"
    assert f.rule == "ts-as-unknown-as"
    # ast-grep --json is 0-indexed; the Finding schema is 1-indexed.
    assert f.line == 1 and f.column == 11
    assert f.file == "src/sloppy.ts"
    assert f.category is Category.LINT
    assert f.severity is Severity.MEDIUM


def test_severity_mapping(monkeypatch, tmp_path: Path):
    (tmp_path / "service.ts").write_text("x\n")
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.shutil.which",
        lambda name: "/usr/bin/ast-grep" if name == "ast-grep" else None,
    )
    payloads = iter(
        json.dumps([dict(_REAL_HIT, severity=sev)])
        for sev in ("error", "warning", "hint", "info")
    )

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout=next(payloads), stderr="")

    monkeypatch.setattr("polycheck.tools.ts_slop.subprocess.run", fake_run)
    tool = TsSlopTool()

    assert tool.run(tmp_path)[0].severity is Severity.MEDIUM
    assert tool.run(tmp_path)[0].severity is Severity.LOW
    assert tool.run(tmp_path)[0].severity is Severity.INFO
    assert tool.run(tmp_path)[0].severity is Severity.INFO


def test_clean_repo_returns_empty(monkeypatch, tmp_path: Path):
    (tmp_path / "service.ts").write_text("export const ok = 1;\n")
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.shutil.which",
        lambda name: "/usr/bin/ast-grep" if name == "ast-grep" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr=""),
    )

    assert TsSlopTool().run(tmp_path) == []


def test_non_json_output_raises(monkeypatch, tmp_path: Path):
    (tmp_path / "service.ts").write_text("x\n")
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.shutil.which",
        lambda name: "/usr/bin/ast-grep" if name == "ast-grep" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 2, stdout="Error: bad rules", stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="ts-slop"):
        TsSlopTool().run(tmp_path)


def test_npx_fallback_uses_package_name_form(monkeypatch, tmp_path: Path):
    """`npx ast-grep` cannot resolve the bin — the fallback must pass
    the package explicitly: `npx -p @ast-grep/cli ast-grep`."""
    (tmp_path / "service.ts").write_text("x\n")
    monkeypatch.setattr(
        "polycheck.tools.ts_slop.shutil.which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.ts_slop.subprocess.run", fake_run)

    TsSlopTool().run(tmp_path)

    prefix = [*npx_command(), "-p", "@ast-grep/cli", "ast-grep"]
    assert captured["cmd"][: len(prefix)] == prefix
    assert "--rule" in captured["cmd"]
    assert "--json" in captured["cmd"]


def test_shipped_rules_file_exists_and_has_only_ts_rules():
    import yaml  # noqa: F401 — pyyaml is a runtime dependency

    from polycheck.tools.ts_slop import _rules_path

    docs = list(yaml.safe_load_all(_rules_path().read_text(encoding="utf-8")))
    assert len(docs) >= 9
    assert all(d["language"] == "ts" for d in docs)
    ids = {d["id"] for d in docs}
    assert {"ts-for-index", "ts-as-unknown-as", "ts-ignore-comment"} <= ids
