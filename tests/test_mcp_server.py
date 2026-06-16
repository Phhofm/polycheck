"""Tests for the guided MCP workflow."""
from __future__ import annotations

import json
from pathlib import Path

from polycheck.finding import Category, Finding, Severity
from polycheck.runner import ToolResult


def test_handle_polycheck_writes_reports_and_session(tmp_path: Path, monkeypatch):
    from polycheck import mcp_server

    finding = Finding(
        tool="ruff",
        rule="F401",
        severity=Severity.HIGH,
        category=Category.LINT,
        message="unused import",
        file="app.py",
        line=1,
        fixable=True,
    )
    result = ToolResult(tool="ruff", status="ok", findings=[finding], duration_sec=0.1)

    class _FakeRunner:
        def __init__(self, repo, config):
            self.repo = repo
            self.config = config

        def run(self, parallel=False, tools=None):
            return [finding], [result]

    monkeypatch.setattr(mcp_server, "Runner", _FakeRunner)
    monkeypatch.setattr(
        mcp_server,
        "_dependency_check",
        lambda repo, cfg=None, tools=None: {"missing_tools": [], "missing_system_dependencies": []},
    )

    response = mcp_server._handle_polycheck({
        "repo": str(tmp_path),
        "severity": "MEDIUM",
        "parallel": False,
    })
    payload = json.loads(response[0].text)

    assert payload["status"] == "needs_user_input"
    assert payload["total_findings"] == 1
    assert payload["by_severity"]["HIGH"] == 1
    assert payload["tools_run"][0]["name"] == "ruff"
    assert Path(payload["reports"][0]).exists()
    assert Path(payload["session"]["latest_markdown"]).exists()
    assert "ask user whether to fix" in payload["next_action"]


def test_handle_polycheck_partial_scan_needs_user_input(tmp_path: Path, monkeypatch):
    from polycheck import mcp_server

    class _FakeRunner:
        def __init__(self, repo, config):
            self.repo = repo
            self.config = config

        def run(self, parallel=False, tools=None):
            return [], []

    monkeypatch.setattr(mcp_server, "Runner", _FakeRunner)
    monkeypatch.setattr(
        mcp_server,
        "_dependency_check",
        lambda repo, cfg=None, tools=None: {
            "missing_tools": [
                {
                    "name": "ruff",
                    "kind": "analyzer",
                    "install_hint": "pipx install ruff",
                    "auto_installable": True,
                    "risk": "low",
                }
            ],
            "missing_system_dependencies": [],
        },
    )

    response = mcp_server._handle_polycheck({
        "repo": str(tmp_path),
        "severity": "MEDIUM",
        "parallel": False,
    })
    payload = json.loads(response[0].text)

    assert payload["status"] == "needs_user_input"
    assert payload["total_findings"] == 0
    assert payload["scan_coverage"]["coverage"] == "partial"
    assert payload["scan_coverage"]["applicable_tools"] == 1
    assert payload["scan_coverage"]["tools_run"] == []
    assert payload["scan_coverage"]["missing_tools"][0]["name"] == "ruff"
    assert "Partial scan" in payload["scan_coverage"]["warning"]
    assert "polycheck.run" in payload["next_action"]


def test_handle_polycheck_returns_completed_when_no_findings_and_full_coverage(tmp_path: Path, monkeypatch):
    from polycheck import mcp_server

    class _FakeRunner:
        def __init__(self, repo, config):
            self.repo = repo
            self.config = config

        def run(self, parallel=False, tools=None):
            return [], []

    monkeypatch.setattr(mcp_server, "Runner", _FakeRunner)
    monkeypatch.setattr(
        mcp_server,
        "_dependency_check",
        lambda repo, cfg=None, tools=None: {"missing_tools": [], "missing_system_dependencies": []},
    )

    response = mcp_server._handle_polycheck({
        "repo": str(tmp_path),
        "severity": "MEDIUM",
        "parallel": False,
    })
    payload = json.loads(response[0].text)

    assert payload["status"] == "completed"
    assert payload["next_action"] == ""
    assert payload["total_findings"] == 0
    assert payload["scan_coverage"]["coverage"] == "full"


    from polycheck import mcp_server

    (tmp_path / ".polycheck.yml").write_text(
        "output:\n  report_dir: ../outside\n", encoding="utf-8"
    )

    class _FakeRunner:
        def __init__(self, repo, config):
            self.repo = repo
            self.config = config

        def run(self, parallel=False, tools=None):
            return [], []

    monkeypatch.setattr(mcp_server, "Runner", _FakeRunner)
    monkeypatch.setattr(
        mcp_server,
        "_dependency_check",
        lambda repo, cfg=None, tools=None: {"missing_tools": [], "missing_system_dependencies": []},
    )

    response = mcp_server._handle_polycheck({
        "repo": str(tmp_path),
        "severity": "MEDIUM",
        "parallel": False,
    })
    payload = json.loads(response[0].text)

    assert "error" in payload
    assert "report_dir" in payload["error"]


def test_audit_run_returns_dependency_context_and_json_resource(tmp_path: Path, monkeypatch):
    from polycheck import mcp_server

    finding = Finding(
        tool="ruff",
        rule="F401",
        severity=Severity.HIGH,
        category=Category.LINT,
        message="unused import",
        file="app.py",
        line=1,
        fixable=True,
    )
    result = ToolResult(tool="ruff", status="ok", findings=[finding], duration_sec=0.1)

    class _FakeRunner:
        def __init__(self, repo, config):
            self.repo = repo
            self.config = config

        def run(self, parallel=False, tools=None):
            return [finding], [result]

    monkeypatch.setattr(mcp_server, "Runner", _FakeRunner)
    monkeypatch.setattr(
        mcp_server,
        "_dependency_check",
        lambda repo, cfg=None, tools=None: {
            "missing_tools": [],
            "missing_system_dependencies": [],
        },
    )

    response = mcp_server._handle_audit_run({
        "repo": str(tmp_path),
        "severity": "MEDIUM",
        "parallel": False,
    })
    payload = json.loads(response[0].text)

    assert payload["status"] == "completed"
    assert payload["next_action"] == ""
    assert payload["total_findings"] == 1
    assert Path(payload["reports"][0]).exists()
    assert mcp_server._read_resource_content("polycheck://findings/json")

    json_resource = json.loads(mcp_server._read_resource_content("polycheck://findings/json"))
    assert json_resource["summary"]["total_findings"] == 1


def test_dependency_check_reports_docker_for_sonarless(tmp_path: Path, monkeypatch):
    from polycheck import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_check_docker",
        lambda: {"name": "docker", "status": "not found", "note": "missing"},
    )

    dependency = mcp_server._dependency_check(tmp_path)

    assert dependency["missing_tools"] == []
    assert dependency["missing_system_dependencies"][0]["name"] == "docker"
    assert dependency["missing_system_dependencies"][0]["needed_for"] == ["sonarless"]


def test_dependency_check_scopes_system_dependency_to_requested_tools(tmp_path: Path, monkeypatch):
    from polycheck import mcp_server

    monkeypatch.setattr(
        mcp_server,
        "_check_docker",
        lambda: {"name": "docker", "status": "not found", "note": "missing"},
    )
    monkeypatch.setattr(
        mcp_server,
        "_missing_tools_for_mcp",
        lambda repo, cfg=None, only=None: [],
    )

    dependency = mcp_server._dependency_check(tmp_path, tools=["ruff"])

    assert dependency["missing_tools"] == []
    assert dependency["missing_system_dependencies"] == []


def test_tool_definitions_include_primary_workflow_tool_and_alias():
    from polycheck import mcp_server

    tools = {tool.name: tool for tool in mcp_server._build_tool_definitions()}

    assert "polycheck.run" in tools
    assert "polycheck" in tools
    assert "polycheck.audit_run" in tools
    assert "polycheck.list_tools" in tools
    assert "polycheck.doctor" in tools
    assert "Do not call polycheck.doctor" in tools["polycheck.run"].description
    assert "Compatibility alias" not in tools["polycheck.run"].description


def test_dispatch_routes_alias_to_guided_workflow(monkeypatch):
    from polycheck import mcp_server

    calls = []
    monkeypatch.setattr(mcp_server, "_handle_polycheck", lambda args: calls.append(args) or ["ok"])

    assert mcp_server._dispatch_tool("polycheck.run", {"repo": "a"}) == ["ok"]
    assert mcp_server._dispatch_tool("polycheck", {"repo": "b"}) == ["ok"]
    assert calls == [{"repo": "a"}, {"repo": "b"}]
