"""polycheck MCP server (stdio transport).

Exposes one primary workflow tool to an AI agent:

  * ``polycheck`` — guided dependency check, scan, reports, summary,
    and next approval step.

And advanced/low-level tools:

  * ``polycheck.audit_run`` — run the scan primitive and return the
    report paths, dependency context, and a short summary. Heavy: spawns
    subprocesses.
  * ``polycheck.list_tools`` — list available analyzers.
  * ``polycheck.explain_finding`` — explain a finding's category and
    how to triage it.
  * ``polycheck.doctor`` — check which tools are installed and which
    are missing. Reports Docker status for sonarless.
  * ``polycheck.install`` — install missing tools.

And resources for reports and session context:

  * ``polycheck://findings/markdown`` — last run's markdown report.
  * ``polycheck://findings/json`` — last run's JSON report.
  * ``polycheck://session/latest`` — latest guided workflow summary.
  * ``polycheck://triage/prompt`` — the LLM triage prompt template.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.types import TextContent

from .config import Config
from .finding import Category, Severity
from .registry import default_registry
from .reporters import render as render_report
from .runner import Runner, dedupe, filter_by_severity
from .session import append_event, write_run_summary, write_session_summary
from .tools.base import Tool

# Module-level state for the last run's reports. Safe for stdio transport
# (single request at a time). Not thread-safe for concurrent requests.
_LAST_RUN: dict = {}

# Status messages for tool availability checks.
_STATUS_NOT_FOUND = "not found"
_STATUS_INSTALLED = "installed"


def _text_content(payload: dict) -> list:
    return [TextContent(type="text", text=json.dumps(payload, indent=2))]


_TRIAGE_PROMPT = """\
You are a senior code reviewer guiding the user through code quality
improvements. The file polycheck-report.md is the output of a
static-analysis pipeline covering LINT, TYPE, SECURITY, DEAD_CODE,
DEPS, CVE, and SECRETS findings — including results from SonarQube
(bugs, vulnerabilities, code smells across 30+ languages).

## Workflow

1. Read the polycheck-report.md file.
2. Present findings grouped by severity:
   - CRITICAL and HIGH first (urgent — these are likely real bugs)
   - MEDIUM next (real smells, worth fixing)
   - LOW and INFO only if the user asks
3. For each finding, tell the user:
   - Which tool found it (ruff, mypy, sonarless, gitleaks, etc.)
   - What the issue is (one sentence)
   - Why it matters (security risk, type error, dead code, etc.)
4. Ask: "Should I fix the [HIGH/CRITICAL] issues?"
5. Apply fixes ONLY after user approval.
6. Summarize: what was fixed, what was deferred, what was flagged as
   false positive.

## Missing Tools

If the report mentions missing tools or the user asks about installing them:

1. Use the guided `polycheck` workflow again with `install_mode: "tools_only"`.
2. Ask the user to approve analyzer installation before setting
   `install_confirmed: true`.
3. Do not manually chain `polycheck.doctor` and `polycheck.install` for
   the normal workflow. Use those only for debugging or advanced use.
4. For tools requiring manual installation, such as Docker for sonarless:
   - **Docker**: Ask your LLM coding assistant to help install Docker
     for this OS. Common options:
     * Linux: `sudo apt install docker.io && sudo usermod -aG docker $USER`
     * Or follow https://docs.docker.com/get-docker/
     * After install, log out and back in for group changes to take effect
   - After Docker is installed, sonarless can be used automatically.


## Triage Rules

For each finding, classify it as:

  REAL BUG       — must be fixed; do not ship without a fix.
  REAL SMELL     — not wrong, but worth refactoring; flag for follow-up.
  FALSE POSITIVE — analyzer is wrong here; suppress or whitelist.
  DEFERRED       — known issue, tracked elsewhere; leave it.

For REAL BUG and REAL SMELL, give the smallest possible patch. Do not
rewrite surrounding code. Do not add new dependencies. Do not change
public APIs unless the finding says to. Prefer the analyzer's suggested
fix if one exists.

Ignore findings that are clearly tooling noise (e.g. "Library stubs
not installed for X" from mypy — that's the lint venv, not the project).

Do not re-read the source files unless a finding's message is genuinely
ambiguous. Trust the static report. Read the full markdown report with
the `read_file` tool, then the JSON report with `read_file` for any
findings you need full `raw` data on.

## Output

When you're done, return a single JSON object shaped like:

{
  "actions": [
    {
      "tool": "ruff",
      "rule": "I001",
      "file": "src/foo.py",
      "line": 12,
      "verdict": "REAL BUG",
      "patch": "…unified diff or null…",
      "comment": "one sentence"
    }
  ],
  "summary": "X real bugs, Y real smells, Z false positives, W deferred"
}
"""


def run_server() -> None:
    """Start the MCP server. Blocks until the parent closes stdin."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Resource, TextContent, Tool
    except ImportError as e:
        raise SystemExit(
            f"polycheck MCP requires the `mcp` package: {e}. "
            "Install with `pip install mcp`."
        ) from e

    server = Server("polycheck")

    @server.list_tools()
    async def _list_tools():
        return _build_tool_definitions()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict):
        return _dispatch_tool(name, arguments)

    @server.list_resources()
    async def _list_resources():
        return [
            Resource(
                uri="polycheck://triage/prompt",
                name="LLM triage prompt",
                description="The prompt to feed to an LLM with the markdown report.",
                mimeType="text/plain",
            ),
            Resource(
                uri="polycheck://session/latest",
                name="Latest polycheck session",
                description="The latest guided workflow summary.",
                mimeType="text/markdown",
            ),
        ]

    @server.read_resource()
    async def _read_resource(uri: str):
        return _read_resource_content(uri)

    import anyio

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(_run)


def _build_tool_definitions():
    """Build the list of MCP tool definitions."""
    from mcp.types import Tool

    return [
        Tool(
            name="polycheck.audit_run",
            description=(
                "Run the polycheck pipeline on a repository. Returns the "
                "report paths, dependency context, and a one-line summary. "
                "Use the `polycheck://findings/markdown` resource to read "
                "the full report."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Path to the repo root"},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict to specific tool names",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
                    },
                },
                "required": ["repo"],
            },
        ),
        Tool(
            name="polycheck",
            description=(
                "Run the guided polycheck workflow. This is the primary "
                "tool for LLM coding assistants: it checks dependencies, "
                "runs the scan, writes reports, returns a compact summary, "
                "and indicates the next user approval step."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Path to the repo root"},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Restrict to specific tool names",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
                        "description": "Minimum severity to keep. Default: MEDIUM.",
                    },
                    "install_mode": {
                        "type": "string",
                        "enum": ["none", "tools_only"],
                        "description": "none or tools_only. Default: none.",
                    },
                    "install_confirmed": {
                        "type": "boolean",
                        "description": "Must be true when install_mode is tools_only. Default: false.",
                    },
                    "parallel": {
                        "type": "boolean",
                        "description": "Run tools concurrently. Default: true.",
                    },
                },
                "required": ["repo"],
            },
        ),
        Tool(
            name="polycheck.list_tools",
            description="List every analyzer polycheck knows about.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="polycheck.explain_finding",
            description=(
                "Explain what a category of finding means and how to "
                "triage it (e.g. 'CVE', 'DEAD_CODE', 'LINT')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": [c.value for c in Category],
                    },
                    "tool": {"type": "string", "description": "Optional tool name"},
                },
                "required": ["category"],
            },
        ),
        Tool(
            name="polycheck.doctor",
            description=(
                "Check which tools are installed and which are missing. "
                "Reports Docker status (needed for sonarless)."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="polycheck.install",
            description=(
                "Install missing tools. Without arguments, installs all "
                "missing tools. Pass specific tool names to install only those."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific tool names to install (default: all missing)",
                    },
                },
            },
        ),
    ]


def _dispatch_tool(name: str, arguments: dict):
    """Dispatch an MCP tool call to the appropriate handler."""
    handlers = {
        "polycheck": _handle_polycheck,
        "polycheck.audit_run": _handle_audit_run,
        "polycheck.list_tools": lambda _: _handle_list_tools(),
        "polycheck.explain_finding": _handle_explain,
        "polycheck.doctor": lambda _: _handle_doctor(),
        "polycheck.install": _handle_install,
    }
    handler = handlers.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return handler(arguments)


def _read_resource_content(uri: str) -> str:
    """Read content from an MCP resource URI."""
    if uri == "polycheck://triage/prompt":
        return _TRIAGE_PROMPT
    if uri == "polycheck://findings/markdown":
        return _last("polycheck-report.md")
    if uri == "polycheck://findings/json":
        return _last("polycheck-report.json")
    if uri == "polycheck://session/latest":
        latest = _latest_session_markdown()
        if latest:
            return latest
        return "(no session yet — run polycheck first)"
    raise ValueError(f"Unknown resource: {uri}")


def _last(name: str) -> str:
    path = _LAST_RUN.get("report_dir")
    if not path:
        return "(no report yet — run polycheck.audit_run first)"
    p = Path(path) / name
    if not p.exists():
        return f"(report not written: {p})"
    return p.read_text(encoding="utf-8")


def _latest_session_markdown() -> str:
    path_text = _LAST_RUN.get("latest_markdown", "")
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.is_file():
        path = Path(_LAST_RUN.get("repo", ".")) / ".polycheck" / "latest.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _repo_from_arguments(arguments: dict) -> Path | list:
    repo = Path(arguments["repo"]).resolve()
    if not repo.exists():
        return _text_content({"error": f"Repo not found: {repo}"})
    if not repo.is_dir():
        return _text_content({"error": f"Not a directory: {repo}"})
    return repo


def _validate_report_dir(repo: Path, configured: str) -> Path | list:
    configured_path = Path(configured)
    if configured_path.is_absolute() or ".." in configured_path.parts:
        return _text_content({"error": "output.report_dir must be a relative path inside the repo"})
    base = (repo / configured_path).resolve()
    try:
        base.relative_to(repo.resolve())
    except ValueError:
        return _text_content({"error": "output.report_dir must stay inside the repo"})
    return base


def _guided_report_dir(repo: Path, configured: str, run_id: str) -> Path | list:
    base = _validate_report_dir(repo, configured)
    if isinstance(base, list):
        return base
    out_dir = base / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _handle_audit_run(arguments: dict) -> list:
    """Run the scan primitive and return report paths plus context."""
    repo = _repo_from_arguments(arguments)
    if isinstance(repo, list):
        return repo

    cfg = Config.load(repo)
    severity = arguments.get("severity", "MEDIUM").upper()
    if severity not in Severity.__members__:
        return _text_content({"error": f"Unknown severity: {severity}"})

    dependency = _dependency_check(repo, cfg, tools=arguments.get("tools"))
    runner = Runner(repo=repo, config=cfg)
    findings, results = runner.run(
        parallel=bool(arguments.get("parallel", True)),
        tools=arguments.get("tools"),
    )
    findings = dedupe(findings)
    findings = filter_by_severity(findings, severity)

    report_dir = _validate_report_dir(repo, cfg.output.report_dir)
    if isinstance(report_dir, list):
        return report_dir
    written: list[Path] = []
    for fmt in cfg.output.formats:
        written.extend(render_report(fmt, repo, findings, results, report_dir=report_dir))

    _LAST_RUN["report_dir"] = str(report_dir)
    _LAST_RUN["findings"] = [f.to_dict() for f in findings]
    _LAST_RUN["repo"] = str(repo)

    summary = _audit_summary(
        repo=repo,
        findings=findings,
        results=results,
        reports=written,
        dependency=dependency,
        severity=severity,
    )
    return [TextContent(type="text", text=json.dumps(summary, indent=2, default=str))]


def _handle_polycheck(arguments: dict) -> list:
    """Run the guided workflow used by LLM coding assistants."""
    repo = _repo_from_arguments(arguments)
    if isinstance(repo, list):
        return repo

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    cfg = Config.load(repo)
    severity = arguments.get("severity", "MEDIUM").upper()
    install_mode = arguments.get("install_mode", "none")
    if install_mode not in {"none", "tools_only"}:
        return _text_content({"error": "install_mode must be none or tools_only"})
    install_confirmed = bool(arguments.get("install_confirmed", False))

    append_event(repo, run_id, {"event": "dependency_check_started"})
    dependency = _dependency_check(repo, cfg, tools=arguments.get("tools"))
    append_event(repo, run_id, {"event": "dependency_check_finished", **dependency})

    if install_mode == "tools_only":
        append_event(repo, run_id, {"event": "install_started", "install_confirmed": install_confirmed})
        if install_confirmed:
            install_results = _install_missing_tools(dependency["missing_tools"])
        else:
            install_results = []
        append_event(repo, run_id, {"event": "install_finished", "results": install_results})
        dependency = _dependency_check(repo, cfg, tools=arguments.get("tools"))
    else:
        install_results = []

    append_event(repo, run_id, {"event": "scan_started", "severity": severity})
    cfg.severity_threshold = severity
    runner = Runner(repo=repo, config=cfg)
    findings, results = runner.run(
        parallel=bool(arguments.get("parallel", True)),
        tools=arguments.get("tools"),
    )
    findings = dedupe(findings)
    findings = filter_by_severity(findings, cfg.severity_threshold)
    append_event(repo, run_id, {"event": "scan_finished", "total_findings": len(findings)})

    out_dir = _guided_report_dir(repo, cfg.output.report_dir, run_id)
    if isinstance(out_dir, list):
        return out_dir
    written: list[Path] = []

    for fmt in cfg.output.formats:
        written.extend(render_report(fmt, repo, findings, results, report_dir=out_dir))

    _LAST_RUN["report_dir"] = str(out_dir)
    _LAST_RUN["findings"] = [f.to_dict() for f in findings]
    _LAST_RUN["repo"] = str(repo)

    summary = _workflow_summary(
        repo=repo,
        findings=findings,
        results=results,
        reports=written,
        dependency=dependency,
        install_results=install_results,
        install_requested=install_mode == "tools_only",
        install_confirmed=install_confirmed,
        severity=severity,
        run_id=run_id,
    )

    session = write_session_summary(repo, summary)
    summary["session"] = session
    _LAST_RUN["latest_markdown"] = session["latest_markdown"]
    _LAST_RUN["latest_json"] = session["latest_json"]

    write_run_summary(repo, run_id, summary)
    return [TextContent(type="text", text=json.dumps(summary, indent=2, default=str))]


def _dependency_check(repo: Path, cfg: Config | None = None, tools: list[str] | None = None) -> dict:
    missing_tools = _missing_tools_for_mcp(repo, cfg, only=tools)
    missing_system = _missing_system_dependencies(repo, cfg, tools=tools)
    return {
        "missing_tools": [_missing_tool_to_dict(cls) for cls in missing_tools],
        "missing_system_dependencies": missing_system,
    }


def _missing_tools_for_mcp(repo: Path, cfg: Config | None = None, only: list[str] | None = None) -> list[type]:
    from .cli import _missing_tools

    return _missing_tools(repo, only=only, exclude=set(), config=cfg)


def _missing_tool_to_dict(cls: type[Tool]) -> dict:
    inst = cls()
    return {
        "name": inst.name,
        "kind": "analyzer",
        "install_hint": inst.install_hint(),
        "auto_installable": inst.can_auto_install(),
        "risk": "low",
    }


def _missing_system_dependencies(repo: Path, cfg: Config | None, tools: list[str] | None = None) -> list[dict]:
    if tools is not None and "sonarless" not in tools:
        return []
    if not _tool_enabled_by_config("sonarless", cfg):
        return []
    docker = _check_docker()
    if docker["status"] == _STATUS_INSTALLED:
        return []
    return [{
        "name": "docker",
        "kind": "system",
        "needed_for": ["sonarless"],
        "status": docker["status"],
        "install_hint": (
            "Docker is required for sonarless. Ask your LLM coding assistant "
            "to help install Docker for this OS, then rerun /polycheck."
        ),
        "auto_installable": False,
        "risk": "high",
    }]


def _tool_enabled_by_config(name: str, cfg: Config | None) -> bool:
    if cfg and cfg.enable and name not in cfg.enable:
        return False
    if cfg and name in cfg.disable:
        return False
    return True


def _install_missing_tools(missing_tools: list[dict]) -> list[dict]:
    results = []
    for item in missing_tools:
        cls = default_registry.get(item["name"])
        if cls is None:
            results.append({"name": item["name"], "installed": False, "message": "unknown tool"})
            continue
        inst = cls()
        ok, message = inst.install()
        results.append({"name": item["name"], "installed": ok, "message": message})
    return results


def _audit_summary(
    *,
    repo: Path,
    findings: list,
    results: list,
    reports: list[Path],
    dependency: dict,
    severity: str,
) -> dict:
    by_severity = {
        severity_name: sum(1 for f in findings if f.severity.name == severity_name)
        for severity_name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
    }
    by_tool = {
        tool_name: sum(1 for f in findings if f.tool == tool_name)
        for tool_name in sorted({f.tool for f in findings})
    }
    tools_run = [
        {
            "name": r.tool,
            "status": r.status,
            "finding_count": len(r.findings),
            "duration_sec": round(r.duration_sec, 2),
            "error": r.error,
        }
        for r in results
    ]
    return {
        "schema_version": 1,
        "status": "completed",
        "next_action": "",
        "repo": str(repo),
        "severity": severity,
        "total_findings": len(findings),
        "by_severity": by_severity,
        "by_tool": by_tool,
        "tools_run": tools_run,
        "tools_failed": [r.tool for r in results if r.status in ("error", "timeout")],
        "missing_tools": dependency["missing_tools"],
        "missing_system_dependencies": dependency["missing_system_dependencies"],
        "reports": [str(p) for p in reports],
        "resources": ["polycheck://findings/markdown", "polycheck://findings/json"],
    }


def _workflow_summary(
    *,
    repo: Path,
    findings: list,
    results: list,
    reports: list[Path],
    dependency: dict,
    install_results: list[dict],
    install_requested: bool,
    install_confirmed: bool,
    severity: str,
    run_id: str,
) -> dict:
    by_severity = {
        severity_name: sum(1 for f in findings if f.severity.name == severity_name)
        for severity_name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
    }
    by_tool = {
        tool_name: sum(1 for f in findings if f.tool == tool_name)
        for tool_name in sorted({f.tool for f in findings})
    }
    tools_run = [
        {
            "name": r.tool,
            "status": r.status,
            "finding_count": len(r.findings),
            "duration_sec": round(r.duration_sec, 2),
            "error": r.error,
        }
        for r in results
    ]
    missing_tools = dependency["missing_tools"]
    missing_system = dependency["missing_system_dependencies"]
    next_action = _next_action(
        findings=findings,
        missing_tools=missing_tools,
        missing_system=missing_system,
        install_requested=install_requested,
        install_confirmed=install_confirmed,
        install_results=install_results,
        severity=severity,
    )
    status = "needs_user_input" if next_action else "completed"

    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "next_action": next_action,
        "repo": str(repo),
        "severity": severity,
        "total_findings": len(findings),
        "by_severity": by_severity,
        "by_tool": by_tool,
        "tools_run": tools_run,
        "tools_skipped": missing_tools + missing_system,
        "missing_tools": missing_tools,
        "missing_system_dependencies": missing_system,
        "install_requested": install_requested,
        "install_confirmed": install_confirmed,
        "install_results": install_results,
        "tools_failed": [r.tool for r in results if r.status in ("error", "timeout")],
        "reports": [str(p) for p in reports],
        "resources": ["polycheck://findings/markdown", "polycheck://findings/json"],
    }


def _next_action(
    *,
    findings: list,
    missing_tools: list[dict],
    missing_system: list[dict],
    install_requested: bool,
    install_confirmed: bool,
    install_results: list[dict],
    severity: str,
) -> str:
    failed_installs = [r for r in install_results if not r.get("installed")]
    if failed_installs:
        names = ", ".join(r.get("name", "tool") for r in failed_installs)
        return f"install failed for {names}; ask user to review the install message and rerun"
    if missing_tools or missing_system:
        if install_requested and not install_confirmed:
            return "ask user to confirm analyzer tool installation before continuing"
        if missing_system:
            return "ask user whether to install analyzer tools, install system dependencies manually, or skip missing items and run with available tools"
        return "ask user whether to install missing analyzer tools and rerun"
    if any(f.fixable for f in findings):
        return f"ask user whether to fix {severity}+ findings or skip fixes"
    if findings:
        return "no fixable findings; ask user whether to lower the severity threshold, install skipped tools, or end the workflow"
    return ""


def _handle_list_tools() -> list:
    rows = []
    for cls in default_registry.all():
        inst = cls()
        installed = inst.is_installed()
        rows.append({
            "name": cls.name,
            "category": cls.category.value,
            "languages": cls.languages,
            "universal": cls.universal,
            "installed": installed,
            "version": inst.version() if installed else None,
            "install_hint": "" if installed else inst.install_hint(),
        })
    return [TextContent(type="text", text=json.dumps(rows, indent=2))]


def _handle_explain(arguments: dict) -> list:
    cat = arguments.get("category", "").upper()
    tool = arguments.get("tool")
    text = _CATEGORY_HELP.get(cat, f"No help for category: {cat}")
    if tool:
        cls = default_registry.get(tool)
        if cls is None:
            text += f"\n\nNote: unknown tool '{tool}'."
        else:
            inst = cls()
            text += f"\n\nFor {tool}, run: `{inst.install_hint()}`."
    return [TextContent(type="text", text=text)]


def _handle_doctor() -> list:
    """Check Docker, sonarless, and all registered tools."""
    rows = []

    # Docker check
    docker_status = _check_docker()
    rows.append(docker_status)

    # sonarless check
    sonarless_ok = shutil.which("sonarless") is not None
    rows.append({
        "name": "sonarless",
        "status": _STATUS_INSTALLED if sonarless_ok else _STATUS_NOT_FOUND,
        "note": "" if sonarless_ok else (
            "Install: curl -s https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash"
        ),
    })

    # All registered tools
    for cls in default_registry.all():
        inst = cls()
        installed = inst.is_installed()
        rows.append({
            "name": cls.name,
            "status": _STATUS_INSTALLED if installed else _STATUS_NOT_FOUND,
            "version": inst.version() if installed else None,
            "languages": cls.languages,
            "universal": cls.universal,
            "note": "" if installed else f"Install: {inst.install_hint()}",
        })

    return [TextContent(type="text", text=json.dumps(rows, indent=2))]


def _check_docker() -> dict:
    """Check if Docker is installed and running."""
    docker_ok = shutil.which("docker") is not None
    docker_running = False
    if docker_ok:
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            docker_running = r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            pass

    if docker_running:
        status = _STATUS_INSTALLED
    elif docker_ok:
        status = "exists but not running"
    else:
        status = _STATUS_NOT_FOUND

    note = "" if docker_running else (
        "Docker is needed for sonarless (SonarQube analysis). "
        "Install Docker: https://docs.docker.com/get-docker/"
    )
    return {"name": "docker", "status": status, "note": note}


def _handle_install(arguments: dict) -> list:
    """Install missing tools."""
    tools_filter = arguments.get("tools")
    results = []

    for cls in default_registry.all():
        if tools_filter and cls.name not in tools_filter:
            continue
        inst = cls()
        if inst.is_installed():
            results.append({"name": cls.name, "installed": True, "message": "already installed"})
            continue
        success, message = inst.install()
        results.append({"name": cls.name, "installed": success, "message": message})

    return [TextContent(type="text", text=json.dumps(results, indent=2))]


_CATEGORY_HELP = {
    "LINT": (
        "LINT findings are style + simple bug-shape rules. Mostly auto-fixable. "
        "Most are LOW/INFO. Triage: prefer the analyzer's --fix, or suppress "
        "with an inline directive if the rule genuinely doesn't fit."
    ),
    "TYPE": (
        "TYPE findings are static type errors. Usually HIGH. They may be real "
        "bugs (passing a string to a function expecting int) or env noise "
        "(missing library stubs in the lint venv). Triage: read the message; "
        "if it says 'library stubs not installed' or 'cannot find "
        "implementation', mark FALSE POSITIVE for *this run* and add the "
        "package to your mypy requirements."
    ),
    "SECURITY": (
        "SECURITY findings are pattern-based bugs, vulnerabilities, and "
        "security hotspots. Many are HIGH. They have a high signal but not "
        "all are bugs (e.g. 'use of MD5' is a smell, not always a bug). "
        "Triage: for each, ask 'is the dangerous operation actually "
        "reachable with attacker-controlled input?'"
    ),
    "DEAD_CODE": (
        "DEAD_CODE findings are symbols not called from anywhere. Mostly LOW. "
        "Many are false positives in dynamic or plugin code. Triage: prefer "
        "REAL SMELL over REAL BUG; if removing breaks tests, mark DEFERRED."
    ),
    "DEPS": (
        "DEPS findings are dependency hygiene (declared but unused, or used "
        "but undeclared). MEDIUM. Triage: add the missing dep to pyproject or "
        "remove the unused one. 'dev-only' findings mean the import happens "
        "in test code; declare under [project.optional-dependencies.test]."
    ),
    "CVE": (
        "CVE findings are known vulnerabilities in a dependency. CRITICAL. "
        "Triage: upgrade to the fix version listed in the finding. If no fix "
        "exists, mark DEFERRED and add a runtime mitigation (e.g. input "
        "validation)."
    ),
    "SECRETS": (
        "SECRETS findings are leaked credentials. CRITICAL. Triage: rotate "
        "the secret immediately, remove from git history (git filter-repo), "
        "and add a gitleaks:allow directive only after the rotation is "
        "complete."
    ),
}
