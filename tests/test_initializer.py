"""Tests for coding-assistant initializer."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from polycheck.cli import app
from polycheck.initializer import normalize_hosts, resolve_mcp_config_path, resolve_workflow_path
from polycheck.workflows import WORKFLOW_TEMPLATES


def test_normalize_hosts_all_and_duplicates():
    assert normalize_hosts(["all"]) == ["kilo", "opencode", "claude"]
    assert normalize_hosts(["kilo,opencode", "all", "opencode"]) == [
        "kilo",
        "opencode",
        "claude",
    ]


def test_normalize_hosts_rejects_unknown():
    try:
        normalize_hosts(["not-a-host"])
    except ValueError as exc:
        assert "Unknown host" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_init_writes_project_workflow_files_and_mcp_configs(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--host", "all", "--scope", "project", "--yes"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".kilo" / "commands" / "polycheck.md").exists()
    assert (tmp_path / ".opencode" / "commands" / "polycheck.md").exists()
    assert (tmp_path / ".claude" / "skills" / "polycheck" / "SKILL.md").exists()
    assert (tmp_path / "kilo.jsonc").exists()
    assert (tmp_path / "opencode.jsonc").exists()
    assert (tmp_path / ".mcp.json").exists()

    claude_mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert claude_mcp["mcpServers"]["polycheck"] == {
        "command": "polycheck",
        "args": ["mcp"],
    }


def test_init_writes_global_files_with_patched_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(project)

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--host", "all", "--scope", "global", "--yes"])

    assert result.exit_code == 0, result.output
    assert (home / ".config" / "kilo" / "commands" / "polycheck.md").exists()
    assert (home / ".config" / "kilo" / "kilo.jsonc").exists()
    assert (home / ".claude" / "skills" / "polycheck" / "SKILL.md").exists()
    assert (home / ".claude.json").exists()


def test_init_dry_run_does_not_write(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--host", "kilo", "--scope", "project", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert "Dry run complete" in result.output
    assert ".kilo/commands/polycheck.md" in result.output
    assert not (tmp_path / ".kilo" / "commands" / "polycheck.md").exists()


def test_init_skips_existing_workflow_without_force(tmp_path: Path, monkeypatch):
    workflow_dir = tmp_path / ".kilo" / "commands"
    workflow_dir.mkdir(parents=True)
    workflow = workflow_dir / "polycheck.md"
    workflow.write_text("old workflow", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--host", "kilo", "--scope", "project", "--yes"])

    assert result.exit_code == 0, result.output
    assert workflow.read_text(encoding="utf-8") == "old workflow"
    assert "already exists" in result.output


def test_init_force_overwrites_existing_workflow(tmp_path: Path, monkeypatch):
    workflow_dir = tmp_path / ".kilo" / "commands"
    workflow_dir.mkdir(parents=True)
    workflow = workflow_dir / "polycheck.md"
    workflow.write_text("old workflow", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--host", "kilo", "--scope", "project", "--yes", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert "Run the Polycheck guided static analysis workflow" in workflow.read_text(
        encoding="utf-8"
    )


def test_init_no_mcp_writes_only_workflow(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--host", "kilo", "--scope", "project", "--yes", "--no-mcp"],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".kilo" / "commands" / "polycheck.md").exists()
    assert not (tmp_path / "kilo.jsonc").exists()


def test_init_mcp_only_writes_only_mcp_config(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--host", "kilo", "--scope", "project", "--yes", "--mcp-only"],
    )

    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".kilo" / "commands").exists()
    assert (tmp_path / "kilo.jsonc").exists()


def test_init_rejects_conflicting_mcp_flags(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--host",
            "kilo",
            "--scope",
            "project",
            "--yes",
            "--no-mcp",
            "--mcp-only",
        ],
    )

    assert result.exit_code == 2
    assert "not both" in result.output


def test_workflow_templates_include_mcp_and_cli_fallback():
    for template in WORKFLOW_TEMPLATES.values():
        assert "polycheck.run" in template.content
        assert "polycheck run . --severity MEDIUM" in template.content


def test_init_merges_claude_global_mcp_config(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    claude_config = home / ".claude.json"
    claude_config.write_text(
        json.dumps({"mcpServers": {"existing": {"command": "old"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--host", "claude", "--scope", "global", "--yes", "--mcp-only"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(claude_config.read_text(encoding="utf-8"))
    assert data["mcpServers"]["existing"] == {"command": "old"}
    assert data["mcpServers"]["polycheck"] == {
        "command": "polycheck",
        "args": ["mcp"],
    }


def test_path_resolution_for_project_and_global(tmp_path: Path):
    project = tmp_path / "project"
    home = tmp_path / "home"

    assert (
        resolve_workflow_path(
            host="opencode",
            scope="project",
            project_root=project,
            home=home,
        )
        == project / ".opencode" / "commands" / "polycheck.md"
    )
    assert (
        resolve_workflow_path(
            host="opencode",
            scope="global",
            project_root=project,
            home=home,
        )
        == home / ".config" / "opencode" / "commands" / "polycheck.md"
    )
    assert (
        resolve_mcp_config_path(
            host="claude",
            scope="global",
            project_root=project,
            home=home,
        )
        == home / ".claude.json"
    )
