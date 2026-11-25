"""CLI-level tests for --profile pr|deep (hermetic, stub tools)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from polycheck.finding import Category, Finding, Severity
from polycheck.registry import ToolRegistry
from polycheck.tools.base import Tool


def _finding(rule: str, file: str, severity: Severity = Severity.MEDIUM) -> Finding:
    return Finding(
        tool="stub", rule=rule, severity=severity,
        category=Category.LINT, message=rule, file=file, line=1,
    )


class _ScopedStub(Tool):
    """Finds in the changed file and in an unchanged file."""

    name = "stub"
    category = Category.LINT
    languages = []
    universal = True

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return [
            _finding("CHANGED", "b.py"),
            _finding("UNTOUCHED", "a.py"),
        ]


class _HeavyStub(_ScopedStub):
    name = "pip-audit"  # a HEAVY_TOOLS name


def _register(monkeypatch, cls: type[Tool]) -> None:
    reg = ToolRegistry()
    reg.register(cls)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)


def _git_repo(tmp_path: Path) -> None:
    """A repo whose upstream is IN SYNC with the base commit — the
    realistic PR/push scenario: new work is staged, history is pushed."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "a.py"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
        cwd=tmp_path, check=True,
    )
    remote = tmp_path.parent / f"{tmp_path.name}-remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "push", "-q", str(remote), "HEAD"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "remote.origin.url", str(remote)], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        cwd=tmp_path, check=True,
    )
    head = subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["git", "config", f"branch.{head}.remote", "origin"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", f"branch.{head}.merge", f"refs/heads/{head}"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=tmp_path, check=True)
    (tmp_path / "b.py").write_text("y = 2\n")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "b.py"],
        cwd=tmp_path, check=True,
    )


def test_profile_pr_without_upstream_gates_committed_high(tmp_path: Path, monkeypatch):
    """First push to a fresh remote: no upstream, nothing pushed yet —
    a committed HIGH finding must still block the gate (0.3.5)."""
    _register(monkeypatch, _ScopedStub)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "a.py"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
        cwd=tmp_path, check=True,
    )

    class _High(_ScopedStub):
        def run(self, repo):
            return [_finding("HIGH-BUG", "a.py", Severity.HIGH)]

    reg = ToolRegistry()
    reg.register(_High)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "pr"]
    )

    assert result.exit_code == 1, result.output


def test_profile_pr_scopes_findings_to_changed_files(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _ScopedStub)
    _git_repo(tmp_path)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "pr"]
    )

    assert result.exit_code == 0, result.output  # MEDIUM finding is below the HIGH gate
    assert "changed tracked file(s)" in result.output
    report = json.loads(
        (tmp_path / "polycheck-reports" / "polycheck-report.json")
        .read_text(encoding="utf-8")
    )
    rules = [f["rule"] for f in report["findings"]]
    assert rules == ["CHANGED"]


def test_profile_pr_fails_on_high_in_changed_file(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _ScopedStub)
    _git_repo(tmp_path)

    class _High(_ScopedStub):
        def run(self, repo):
            return [_finding("HIGH-BUG", "b.py", Severity.HIGH)]

    reg = ToolRegistry()
    reg.register(_High)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "pr"]
    )

    assert result.exit_code == 1, result.output  # HIGH gate


def test_profile_pr_requires_git_repo(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _ScopedStub)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "pr"]
    )

    assert result.exit_code == 2
    assert "git repository" in result.output


def test_profile_pr_skips_heavy_tools(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _HeavyStub)
    _git_repo(tmp_path)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "pr"]
    )

    assert result.exit_code == 0, result.output
    assert "pip-audit" not in result.output  # skipped entirely


def test_profile_deep_runs_heavy_tools_and_never_gates(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _HeavyStub)
    _git_repo(tmp_path)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "deep"]
    )

    assert "pip-audit" in result.output  # heavy tool ran
    assert result.exit_code == 0  # no gate by default


def test_profile_unknown_rejected(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _ScopedStub)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "turbo"]
    )

    assert result.exit_code == 2
    assert "unknown profile" in result.output


def test_profile_pr_explicit_fail_on_overrides_preset(tmp_path: Path, monkeypatch):
    _register(monkeypatch, _ScopedStub)
    _git_repo(tmp_path)

    result = CliRunner().invoke(
        _app(), ["run", str(tmp_path), "--profile", "pr", "--fail-on", "LOW"]
    )

    assert result.exit_code == 1, result.output  # explicit LOW gate beats HIGH preset


def _app():
    from polycheck.cli import app
    return app
