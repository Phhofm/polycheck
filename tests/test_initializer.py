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
    # Path separators differ on Windows; compare the joined path loosely.
    assert ".kilo" in result.output
    assert "polycheck.md" in result.output
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


def test_init_writes_parseable_configs_and_frontmatter(tmp_path: Path, monkeypatch):
    """Characterization of the real onboarding output: the configs a
    colleague receives must parse and carry the essentials."""
    import re

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["init", "--host", "all", "--scope", "project", "--yes"]
    )
    assert result.exit_code == 0, result.output

    for jsonc_name in ("kilo.jsonc", "opencode.jsonc"):
        text = (tmp_path / jsonc_name).read_text(encoding="utf-8")
        data = json.loads(re.sub(r"//[^\n]*", "", text))
        command = data["mcp"]["polycheck"]["command"]
        assert command == ["polycheck", "mcp"], jsonc_name

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["polycheck"]["args"] == ["mcp"]

    skill = (tmp_path / ".claude" / "skills" / "polycheck" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---")
    assert "name: polycheck" in skill

    kilo_workflow = (tmp_path / ".kilo" / "commands" / "polycheck.md").read_text(encoding="utf-8")
    assert "polycheck.run" in kilo_workflow
    assert "diff: true" in kilo_workflow
    assert "suppress:" in kilo_workflow


def test_init_writes_reviewer_agents_for_all_hosts(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["init", "--host", "all", "--scope", "project", "--yes"])
    assert result.exit_code == 0, result.output

    kilo_agent = tmp_path / ".kilo" / "agent" / "polycheck-reviewer.md"
    opencode_agent = tmp_path / ".opencode" / "agents" / "polycheck-reviewer.md"
    claude_agent = tmp_path / ".claude" / "agents" / "polycheck-reviewer.md"
    for agent in (kilo_agent, opencode_agent, claude_agent):
        assert agent.exists(), agent

    body = kilo_agent.read_text(encoding="utf-8")
    assert "mode: subagent" in body
    assert "polycheck-review-checklist.md" in body
    assert "REAL BUG" in body and "FALSE POSITIVE" in body
    assert "suppress:" in body
    claude_body = claude_agent.read_text(encoding="utf-8")
    assert "name: polycheck-reviewer" in claude_body
    assert "tools:" in claude_body


def test_init_no_agents_and_agents_only(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["init", "--host", "kilo", "--scope", "project", "--yes", "--no-agents"]
    )
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".kilo" / "agent" / "polycheck-reviewer.md").exists()
    assert (tmp_path / ".kilo" / "commands" / "polycheck.md").exists()

    result = CliRunner().invoke(
        app, ["init", "--host", "kilo", "--scope", "project", "--yes", "--agents-only", "--force"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".kilo" / "agent" / "polycheck-reviewer.md").exists()


def test_init_git_hook_pre_push(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = CliRunner().invoke(
        app, ["init", "--host", "kilo", "--scope", "project", "--yes",
              "--no-mcp", "--no-agents", "--git-hook", "pre-push"]
    )
    assert result.exit_code == 0, result.output

    hook = tmp_path / ".git" / "hooks" / "pre-push"
    assert hook.exists()
    import os
    assert os.access(hook, os.X_OK)
    content = hook.read_text(encoding="utf-8")
    assert "polycheck run . --parallel --fail-on HIGH" in content
    assert "exit 1" in content


def test_init_git_hook_never_overwrites_existing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nmy-custom-hook\n", encoding="utf-8")

    result = CliRunner().invoke(
        app, ["init", "--host", "kilo", "--scope", "project", "--yes",
              "--no-mcp", "--no-agents", "--git-hook", "pre-push"]
    )
    assert result.exit_code == 0, result.output
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\nmy-custom-hook\n"
    assert "already exists" in result.output


def test_init_git_hook_rejects_unknown_hook_and_global_scope(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app, ["init", "--host", "kilo", "--scope", "project", "--yes", "--git-hook", "post-commit"]
    )
    assert result.exit_code == 2

    result = CliRunner().invoke(
        app, ["init", "--host", "kilo", "--scope", "global", "--yes", "--git-hook", "pre-push"]
    )
    assert result.exit_code == 2
