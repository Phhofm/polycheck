"""dependency-cruiser adapter tests — shapes captured from real
dependency-cruiser 18.9.0 output.

Second structural adapter (0.3.6, deep-profile family, JS/TS
counterpart to tach): `depcruise --output-type json` reports rule
violations (circular dependencies, path rules) under
``summary.violations``. The adapter runs only when the repo carries a
dependency-cruiser config — rules are user-defined.

CLI quirks pinned here:
  * the npm package installs a binary named ``depcruise``, but
    ``npx depcruise`` resolves a placeholder package — the npx fallback
    must use the package name ``dependency-cruiser``;
  * violations do not change the exit code in 18.x (exit 0 with
    findings) — the parser never trusts the exit code;
  * some documentation references an ``output.violations`` envelope —
    the parser reads ``summary.violations`` first and tolerates the
    alias.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from polycheck.finding import Category, Severity
from polycheck.tools.base import npx_command

_CONFIG = '{"forbidden":[{"name":"no-circular","severity":"error","from":{},"to":{"circular":true}}]}'


def _config_repo(tmp_path: Path) -> None:
    (tmp_path / ".dependency-cruiser.json").write_text(_CONFIG)


def test_is_applicable_requires_dependency_cruiser_config(tmp_path: Path):
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    assert not DependencyCruiserTool().is_applicable(tmp_path)
    (tmp_path / ".dependency-cruiser.cjs").write_text("module.exports = {};")
    assert DependencyCruiserTool().is_applicable(tmp_path)
    (tmp_path / ".dependency-cruiser.cjs").unlink()
    (tmp_path / ".dependency-cruiser.json").write_text("{}")
    assert DependencyCruiserTool().is_applicable(tmp_path)


def test_binary_is_depcruise_and_npx_fallback_uses_package_name(
    monkeypatch, tmp_path: Path,
):
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    _config_repo(tmp_path)
    which_results = {"depcruise": None, "npx": "/usr/bin/npx"}
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: which_results.get(name),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.subprocess.run", fake_run
    )

    DependencyCruiserTool().run(tmp_path)

    prefix = npx_command()
    assert captured["cmd"][: len(prefix) + 1] == [*prefix, "--yes"]
    assert captured["cmd"][len(prefix) + 1] == "dependency-cruiser"  # not the placeholder
    assert "--output-type" in captured["cmd"]


def test_prefers_local_depcruise_binary(monkeypatch, tmp_path: Path):
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    _config_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: "/usr/bin/depcruise" if name == "depcruise" else None,
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.subprocess.run", fake_run
    )

    DependencyCruiserTool().run(tmp_path)

    assert captured["cmd"][0] == "depcruise"


def test_parses_cycle_violation_from_real_shape(monkeypatch, tmp_path: Path):
    """Verbatim violation entry from dependency-cruiser 18.9.0 on a seeded
    a.js <-> b.js cycle with a no-circular rule."""
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    _config_repo(tmp_path)
    payload = {
        "modules": [
            {"source": "a.js", "dependencies": [], "valid": False},
        ],
        "summary": {
            "violations": [
                {
                    "type": "cycle",
                    "from": "a.js",
                    "to": "b.js",
                    "unresolvedTo": "./b.js",
                    "dependencyTypes": ["local", "import"],
                    "rule": {"severity": "error", "name": "no-circular"},
                    "cycle": [
                        {"name": "b.js", "dependencyTypes": ["local"]},
                        {"name": "a.js", "dependencyTypes": ["local"]},
                    ],
                }
            ]
        },
    }
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: "/usr/bin/depcruise" if name == "depcruise" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload), stderr="",
        ),
    )

    findings = DependencyCruiserTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "dependency-cruiser"
    assert f.rule == "no-circular"
    assert f.category is Category.ARCHITECTURE
    assert f.severity is Severity.MEDIUM
    assert f.file == "a.js"
    assert f.line is None  # dependency-level finding
    assert "b.js" in f.message and "a.js" in f.message


def test_severity_mapping(monkeypatch, tmp_path: Path):
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    _config_repo(tmp_path)

    def _payload(sev: str) -> dict:
        return {
            "modules": [],
            "summary": {"violations": [
                {"from": "a.js", "to": "b.js", "type": "cycle",
                 "rule": {"severity": sev, "name": "no-circular"}},
            ]},
        }

    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: "/usr/bin/depcruise" if name == "depcruise" else None,
    )
    outs = iter(json.dumps(_payload(s)) for s in ("error", "warn", "info"))

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=next(outs), stderr="")

    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.subprocess.run", fake_run
    )
    tool = DependencyCruiserTool()

    assert tool.run(tmp_path)[0].severity is Severity.MEDIUM
    assert tool.run(tmp_path)[0].severity is Severity.LOW
    assert tool.run(tmp_path)[0].severity is Severity.INFO


def test_reads_output_violations_alias(monkeypatch, tmp_path: Path):
    """Some dependency-cruiser versions/reporters document an
    ``output.violations`` envelope — read it when summary has none."""
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    _config_repo(tmp_path)
    payload = {
        "output": {"violations": [
            {"from": "a.js", "to": "b.js", "type": "cycle",
             "rule": {"severity": "warn", "name": "no-circular"}},
        ]},
    }
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: "/usr/bin/depcruise" if name == "depcruise" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(payload), stderr="",
        ),
    )

    findings = DependencyCruiserTool().run(tmp_path)

    assert len(findings) == 1
    assert findings[0].severity is Severity.LOW


def test_non_json_output_raises(monkeypatch, tmp_path: Path):
    """A broken config must surface as an error, never as a clean repo."""
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    _config_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: "/usr/bin/depcruise" if name == "depcruise" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 1, stdout="ERROR: Cannot parse config", stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="dependency-cruiser"):
        DependencyCruiserTool().run(tmp_path)


def test_is_installed_accepts_npx_fallback(monkeypatch):
    """The runner skips tools that report not-installed — but depcruise
    is usable via npx without a global install. Same fix as knip
    (0.3.6): an npx-capable tool must not report installed=False."""
    from polycheck.tools.dependency_cruiser import DependencyCruiserTool

    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )
    assert DependencyCruiserTool().is_installed() is True

    monkeypatch.setattr(
        "polycheck.tools.dependency_cruiser.shutil.which", lambda name: None
    )
    assert DependencyCruiserTool().is_installed() is False
