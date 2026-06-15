"""polycheck MCP server (stdio transport).

Exposes five tools to an AI agent:

  * ``polycheck.audit_run`` — run the full pipeline and return the
    report paths + a short summary. Heavy: spawns subprocesses.
  * ``polycheck.list_tools`` — list available analyzers.
  * ``polycheck.explain_finding`` — explain a finding's category and
    how to triage it.
  * ``polycheck.doctor`` — check which tools are installed and which
    are missing. Reports Docker status for sonarless.
  * ``polycheck.install`` — install missing tools.

And three resources:

  * ``polycheck://findings/markdown`` — last run's markdown report.
  * ``polycheck://findings/json`` — last run's JSON report.
  * ``polycheck://triage/prompt`` — the LLM triage prompt template.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Config
from .finding import Category
from .registry import default_registry
from .reporters import render as render_report
from .runner import Runner, dedupe, filter_by_severity

from mcp.types import TextContent

# Module-level state for the last run's reports. Safe for stdio transport
# (single request at a time). Not thread-safe for concurrent requests.
_LAST_RUN: dict = {}

# Status messages for tool availability checks.
_STATUS_NOT_FOUND = "not found"
_STATUS_INSTALLED = "installed"


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

1. Run `polycheck.doctor` to check which tools are installed.
2. For tools that can be auto-installed (pipx, npm, apt), run
   `polycheck.install` with the tool names.
3. For tools requiring manual installation (e.g., Docker for sonarless):
   - **Docker**: Guide the user to install Docker Desktop for their OS:
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
                "report paths and a one-line summary. Use the "
                "`polycheck://findings/markdown` resource to read the "
                "full report."
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
    raise ValueError(f"Unknown resource: {uri}")


def _last(name: str) -> str:
    path = _LAST_RUN.get("report_dir")
    if not path:
        return "(no report yet — run polycheck.audit_run first)"
    p = Path(path) / name
    if not p.exists():
        return f"(report not written: {p})"
    return p.read_text(encoding="utf-8")


def _handle_audit_run(arguments: dict) -> list:
    repo = Path(arguments["repo"]).resolve()
    if not repo.exists():
        return [TextContent(type="text", text=f"Repo not found: {repo}")]
    if not repo.is_dir():
        return [TextContent(type="text", text=f"Not a directory: {repo}")]

    cfg = Config.load(repo)
    if arguments.get("severity"):
        cfg.severity_threshold = arguments["severity"].upper()

    runner = Runner(repo=repo, config=cfg)
    findings, results = runner.run(tools=arguments.get("tools"))
    findings = dedupe(findings)
    findings = filter_by_severity(findings, cfg.severity_threshold)

    out_dir = repo / cfg.output.report_dir
    written: list[Path] = []
    for fmt in cfg.output.formats:
        written.extend(render_report(fmt, repo, findings, results, report_dir=out_dir))

    _LAST_RUN["report_dir"] = str(out_dir)
    _LAST_RUN["findings"] = [f.to_dict() for f in findings]

    summary = {
        "repo": str(repo),
        "total_findings": len(findings),
        "by_severity": {},
        "tools_run": len(results),
        "tools_failed": [r.tool for r in results if r.status in ("error", "timeout")],
        "reports": [str(p) for p in written],
        "next": "Read polycheck://triage/prompt and the markdown report.",
    }
    for f in findings:
        summary["by_severity"][f.severity.name] = summary["by_severity"].get(f.severity.name, 0) + 1
    return [TextContent(type="text", text=json.dumps(summary, indent=2))]


def _handle_list_tools() -> list:
    rows = []
    for cls in default_registry.all():
        rows.append({
            "name": cls.name,
            "category": cls.category.value,
            "languages": cls.languages,
            "universal": cls.universal,
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
