"""tach adapter tests — shapes captured from real tach 0.35.3 output.

tach is the first structural adapter (0.3.4): `tach check --output json`
reports undeclared dependencies and, with `forbid_circular_dependencies`,
dependency cycles as JSON. The adapter runs only when the repo carries a
tach.toml (or [tool.tach] in pyproject.toml) — architecture contracts are
user-defined; without one there is nothing to check.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from polycheck.finding import Category, Severity


def test_is_applicable_requires_tach_config(tmp_path: Path):
    from polycheck.tools.tach import TachTool

    assert not TachTool().is_applicable(tmp_path)
    (tmp_path / "tach.toml").write_text("[[modules]]\npath = 'app'\n")
    assert TachTool().is_applicable(tmp_path)

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname="x"\n\n[tool.tach]\n')
    assert TachTool().is_applicable(tmp_path)


def test_parses_undeclared_dependency_violation(monkeypatch, tmp_path: Path):
    from polycheck.tools.tach import TachTool

    (tmp_path / "tach.toml").write_text("[[modules]]\npath = 'app'\n")
    monkeypatch.setattr(
        "polycheck.tools.tach.shutil.which",
        lambda name: "/usr/local/bin/tach" if name == "tach" else None,
    )
    # Verbatim tach 0.35.3 `check --output json` payload for an undeclared
    # dependency (widgets/w1.py imports app; widgets does not declare it).
    payload = [
        {
            "Located": {
                "file_path": "widgets/w1.py",
                "line_number": 1,
                "original_line_number": 1,
                "severity": "Error",
                "details": {
                    "Code": {
                        "UndeclaredDependency": {
                            "dependency": "app",
                            "usage_module": "widgets",
                            "definition_module": "app",
                        }
                    }
                },
            }
        }
    ]
    monkeypatch.setattr(
        "polycheck.tools.tach.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1,
                                                      stdout=json.dumps(payload),
                                                      stderr=""),
    )

    findings = TachTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "tach"
    assert f.rule == "UndeclaredDependency"
    assert f.file == "widgets/w1.py"
    assert f.line == 1
    assert f.category is Category.ARCHITECTURE
    assert f.severity is Severity.MEDIUM
    assert "widgets" in f.message and "app" in f.message


def test_parses_circular_dependency_report(monkeypatch, tmp_path: Path):
    from polycheck.tools.tach import TachTool

    (tmp_path / "tach.toml").write_text("[[modules]]\npath = 'app'\n")
    monkeypatch.setattr(
        "polycheck.tools.tach.shutil.which",
        lambda name: "/usr/local/bin/tach" if name == "tach" else None,
    )
    # Verbatim payload for a declared cycle with forbid_circular_dependencies.
    payload = {"error": "Circular dependency",
               "dependencies": ["mypkg.core", "mypkg.cli"]}
    monkeypatch.setattr(
        "polycheck.tools.tach.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1,
                                                      stdout=json.dumps(payload),
                                                      stderr=""),
    )

    findings = TachTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "circular-dependency"
    assert f.category is Category.ARCHITECTURE
    assert f.file is None  # cycle spans modules — no single file
    assert "mypkg.core" in f.message and "mypkg.cli" in f.message


def test_clean_repo_returns_empty(monkeypatch, tmp_path: Path):
    from polycheck.tools.tach import TachTool

    (tmp_path / "tach.toml").write_text("[[modules]]\npath = 'app'\n")
    monkeypatch.setattr(
        "polycheck.tools.tach.shutil.which",
        lambda name: "/usr/local/bin/tach" if name == "tach" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.tach.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="[]",
                                                      stderr=""),
    )

    assert TachTool().run(tmp_path) == []


def test_non_json_output_raises_instead_of_silently_passing(
    monkeypatch, tmp_path: Path,
):
    """tach exits 1 both for violations and for config errors; the JSON
    parse distinguishes them. A broken tach.toml must surface as an
    error, never as 'no findings'."""
    from polycheck.tools.tach import TachTool

    (tmp_path / "tach.toml").write_text("dependencies = ['y']\n")
    monkeypatch.setattr(
        "polycheck.tools.tach.shutil.which",
        lambda name: "/usr/local/bin/tach" if name == "tach" else None,
    )
    # Verbatim stdout of tach 0.35.3 on a malformed tach.toml.
    stdout = ("Failed to parse project config: TOML parse error at line 1, "
              "column 1\n")
    monkeypatch.setattr(
        "polycheck.tools.tach.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=stdout,
                                                      stderr=""),
    )

    with pytest.raises(RuntimeError, match="tach"):
        TachTool().run(tmp_path)


def test_check_runs_with_json_output(monkeypatch, tmp_path: Path):
    from polycheck.tools.tach import TachTool

    (tmp_path / "tach.toml").write_text("[[modules]]\npath = 'app'\n")
    monkeypatch.setattr(
        "polycheck.tools.tach.shutil.which",
        lambda name: "/usr/local/bin/tach" if name == "tach" else None,
    )
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.tach.subprocess.run", fake_run)

    TachTool().run(tmp_path)

    assert captured["cmd"][:2] == ["tach", "check"]
    assert "--output" in captured["cmd"]
    assert "json" in captured["cmd"]


# --- cross-model audit (0.3.4): real-payload regression guards --------------


def test_pip_audit_pyproject_fallback_leaves_no_file_in_repo(monkeypatch, tmp_path: Path):
    """Audit finding: the pyproject fallback wrote its temp requirements
    file INTO the repo and never removed it — pollution gitleaks would
    scan on the next run. The temp file must live outside the repo."""
    from polycheck.tools.pip_audit import PipAuditTool

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["pillow==9.0.0"]\n'
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        req_path = Path(cmd[cmd.index("-r") + 1])
        # A real pip-audit would read this file; keep the temp file in place
        # during the run to prove it exists where the adapter put it.
        assert Path(req_path).exists()
        return subprocess.CompletedProcess(cmd, 1, stdout="[]", stderr="")

    monkeypatch.setattr(
        "polycheck.tools.pip_audit.shutil.which",
        lambda name: "/usr/bin/pip-audit" if name == "pip-audit" else None,
    )
    monkeypatch.setattr("polycheck.tools.pip_audit.subprocess.run", fake_run)

    PipAuditTool().run(tmp_path)

    req_arg = Path(captured["cmd"][captured["cmd"].index("-r") + 1])
    assert not req_arg.is_relative_to(tmp_path), (
        "temp requirements file must not live inside the repo"
    )
    assert not list(tmp_path.glob(".polycheck-pip-audit-reqs.txt"))


def test_semgrep_reads_start_from_result_level(monkeypatch, tmp_path: Path):
    """Audit finding: the real semgrep 1.186 payload carries
    `start.line`/`start.col` on the RESULT object, not under `extra` —
    the old parser read extra.start and dropped every location."""
    from polycheck.tools.semgrep import SemgrepTool

    # Verbatim from `semgrep scan --config=rule.yml --json` (1.186.0).
    payload = {
        "version": "1.186.0",
        "results": [
            {
                "check_id": "pyaml-unsafe-load",
                "path": "app/app.py",
                "start": {"line": 3, "col": 12, "offset": 34},
                "end": {"line": 3, "col": 27, "offset": 49},
                "extra": {
                    "severity": "ERROR",
                    "message": "yaml.load without Loader is unsafe",
                    "fix": None,
                },
            }
        ],
        "errors": [],
    }
    monkeypatch.setattr(
        "polycheck.tools.semgrep.shutil.which",
        lambda name: "/usr/bin/semgrep" if name == "semgrep" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.semgrep.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload), stderr="",
        ),
    )

    findings = SemgrepTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "pyaml-unsafe-load"
    assert f.severity is Severity.HIGH
    assert f.file == "app/app.py"
    assert f.line == 3 and f.column == 12
