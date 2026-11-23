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


def test_handle_polycheck_rejects_escaping_report_dir(tmp_path: Path, monkeypatch):
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


def test_tool_definitions_are_slim_two_tools():
    from polycheck import mcp_server

    tools = {tool.name: tool for tool in mcp_server._build_tool_definitions()}

    assert set(tools) == {"polycheck.run", "polycheck.audit_run"}
    assert "polycheck.doctor" not in tools["polycheck.run"].description


def test_dispatch_rejects_retired_tools(monkeypatch):
    import pytest

    from polycheck import mcp_server

    calls = []

    def fake_handle(args):
        calls.append(args)
        return ["ok"]

    monkeypatch.setattr(mcp_server, "_handle_polycheck", fake_handle)

    assert mcp_server._dispatch_tool("polycheck.run", {"repo": "a"}) == ["ok"]
    assert mcp_server._dispatch_tool("polycheck.audit_run", {"repo": "a"})

    for retired in ("polycheck", "polycheck.doctor", "polycheck.install",
                    "polycheck.list_tools", "polycheck.explain_finding"):
        with pytest.raises(ValueError, match="Unknown tool"):
            mcp_server._dispatch_tool(retired, {"repo": "x"})
    assert calls == [{"repo": "a"}]


def test_handle_polycheck_emits_progress_phases(tmp_path: Path, monkeypatch):
    """The guided run reports phase progress (deps → scan → reports) so
    MCP clients with a progress token can show live status."""
    import json as _json

    from polycheck import mcp_server
    from polycheck.finding import Category, Finding, Severity
    from polycheck.runner import ToolResult

    finding = Finding(
        tool="stub", rule="F401", severity=Severity.MEDIUM,
        category=Category.LINT, message="unused import", file="a.py", line=1,
    )
    result = ToolResult(tool="stub", status="ok", findings=[finding], duration_sec=0.1)

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

    phases: list[tuple[float, str | None]] = []

    def collect(p: float, msg: str | None = None) -> None:
        phases.append((p, msg))

    response = mcp_server._handle_polycheck(
        {"repo": str(tmp_path), "severity": "MEDIUM", "parallel": False},
        progress=collect,
    )
    payload = _json.loads(response[0].text)
    assert payload["status"] in ("completed", "needs_user_input")

    assert len(phases) >= 3
    floats = [p for p, _ in phases]
    assert floats == sorted(floats)
    assert any("scan" in (msg or "") for _, msg in phases)
    assert any("report" in (msg or "") for _, msg in phases)


def test_call_tool_sends_progress_notifications(monkeypatch):
    """When the client passes a progressToken, the server emits MCP
    progress notifications during the guided run."""
    import asyncio
    import types

    from polycheck import mcp_server

    def fake_handle(args, progress=None):
        if progress:
            progress(0.5, "halfway")
        return ["ok"]

    monkeypatch.setattr(mcp_server, "_handle_polycheck", fake_handle)

    notifications: list[tuple[float, str | None]] = []

    class _FakeSession:
        async def send_progress_notification(self, token, progress, total=None, message=None):
            notifications.append((progress, message))

    class _FakeContext:
        meta = types.SimpleNamespace(progressToken="tok-1")
        session = _FakeSession()

    class _FakeServer:
        request_context = _FakeContext()

    result = asyncio.run(
        mcp_server._call_tool_with_progress(_FakeServer(), "polycheck.run", {"repo": "x"})
    )

    assert result == ["ok"]
    assert (0.5, "halfway") in notifications
    assert len(notifications) >= 1


def test_call_tool_without_progress_token_skips_notifications(monkeypatch):
    import asyncio

    from polycheck import mcp_server

    def fake_handle(args, progress=None):
        return ["ok"]

    monkeypatch.setattr(mcp_server, "_handle_polycheck", fake_handle)

    class _FakeContext:
        meta = None  # client did not request progress
        session = None

    class _FakeServer:
        request_context = _FakeContext()

    result = asyncio.run(
        mcp_server._call_tool_with_progress(_FakeServer(), "polycheck.run", {"repo": "x"})
    )

    assert result == ["ok"]


def test_diff_param_reports_only_new_findings(tmp_path: Path, monkeypatch):
    """diff:true filters findings to those newer than the baseline and
    carries known/new counts in the summary payload."""
    import json as _json

    from polycheck import mcp_server
    from polycheck.finding import Category, Finding, Severity
    from polycheck.runner import ToolResult, save_baseline

    finding = Finding(
        tool="stub", rule="F401", severity=Severity.MEDIUM,
        category=Category.LINT, message="unused import", file="a.py", line=1,
    )
    new_finding = Finding(
        tool="stub", rule="F821", severity=Severity.MEDIUM,
        category=Category.LINT, message="undefined name", file="b.py", line=2,
    )
    result = ToolResult(tool="stub", status="ok", findings=[finding, new_finding], duration_sec=0.1)

    class _FakeRunner:
        def __init__(self, repo, config):
            self.repo = repo
            self.config = config

        def run(self, parallel=False, tools=None):
            return [finding, new_finding], [result]

    monkeypatch.setattr(mcp_server, "Runner", _FakeRunner)
    monkeypatch.setattr(
        mcp_server,
        "_dependency_check",
        lambda repo, cfg=None, tools=None: {"missing_tools": [], "missing_system_dependencies": []},
    )

    # Baseline knows the first finding only.
    save_baseline(tmp_path / "polycheck-reports", [finding])

    response = mcp_server._handle_polycheck({
        "repo": str(tmp_path),
        "severity": "MEDIUM",
        "parallel": False,
        "diff": True,
    })
    payload = _json.loads(response[0].text)

    assert payload["baseline"]["diff"] is True
    assert payload["baseline"]["baseline_count"] == 1
    assert payload["baseline"]["known"] == 1
    assert payload["baseline"]["new"] == 1


def test_diff_param_without_baseline_reports_all_with_note(tmp_path: Path, monkeypatch):
    import json as _json

    from polycheck import mcp_server
    from polycheck.finding import Category, Finding, Severity
    from polycheck.runner import ToolResult

    finding = Finding(
        tool="stub", rule="F401", severity=Severity.MEDIUM,
        category=Category.LINT, message="unused import", file="a.py", line=1,
    )
    result = ToolResult(tool="stub", status="ok", findings=[finding], duration_sec=0.1)

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
        "diff": True,
    })
    payload = _json.loads(response[0].text)

    assert payload["baseline"]["baseline"] is None
    assert "baseline" in payload["baseline"]["note"]


def test_claude_workflow_template_has_required_frontmatter():
    from polycheck.workflows import CLAUDE_WORKFLOW

    assert CLAUDE_WORKFLOW.startswith("---")
    assert "name: polycheck" in CLAUDE_WORKFLOW
    assert "description:" in CLAUDE_WORKFLOW


def test_shared_workflow_steps_mention_baseline_and_suppress():
    from polycheck.workflows import _SHARED_STEPS

    assert "polycheck baseline" in _SHARED_STEPS
    assert "diff: true" in _SHARED_STEPS
    assert "suppress:" in _SHARED_STEPS
