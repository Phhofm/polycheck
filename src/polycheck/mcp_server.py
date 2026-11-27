"""polycheck MCP server (stdio transport).

Exposes one primary workflow tool to an AI agent:

  * ``polycheck.run`` — primary guided dependency check, scan, reports,
    summary, coverage metadata, and next approval step.
  * ``polycheck`` — compatibility alias for ``polycheck.run``.

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
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from mcp.types import TextContent

from .config import Config
from .finding import Category, Finding, Severity
from .profiles import (
    ProfileError,
    ProfileSpec,
    changed_files,
    default_severity,
    filter_by_scope,
    resolve_profile,
)
from .registry import default_registry
from .reporters import render as render_report
from .runner import (
    Runner,
    apply_suppressions,
    dedupe,
    filter_by_baseline,
    filter_by_severity,
    load_baseline,
)
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

1. For normal polycheck runs, call the guided MCP tool `polycheck.run`
   first. Diagnostics and installs are built into its guided flow; use
   the CLI (`polycheck doctor`, `polycheck install`) only if the user
   explicitly asks.
2. Read the returned `status`, `next_action`, and `scan_coverage`.
3. If `status` is `needs_user_input` and the tool reports missing
   analyzers, ask the user whether to approve installation.
4. If the user approves, call `polycheck.run` again with:
   - `install_mode: "tools_only"`
   - `install_confirmed: true`
5. Present findings grouped by severity:
   - CRITICAL and HIGH first (urgent — these are likely real bugs)
   - MEDIUM next (real smells, worth fixing)
   - LOW and INFO only if the user asks
6. For each finding, tell the user:
   - Which tool found it (ruff, mypy, sonarless, gitleaks, etc.)
   - What the issue is (one sentence)
   - Why it matters (security risk, type error, dead code, etc.)
7. Ask: "Should I fix the [HIGH/CRITICAL] issues?"
8. Apply fixes ONLY after user approval.
9. Summarize: what was fixed, what was deferred, what was flagged as
   false positive.

## Baseline & Durable Suppressions

Keep the triage loop cheap across runs:

1. After a run the user accepts (fixed or triaged everything), suggest
   taking a baseline: `polycheck baseline <repo>`.
2. Later runs with `diff: true` report only NEW findings — the payload's
   `baseline` object carries `known` and `new` counts.
3. When a finding is a FALSE POSITIVE, persist the verdict instead of
   re-arguing it every run: append the rule to the `suppress:` list in
   `.polycheck.yml` (format: `- RULE` for everywhere, or
   `- RULE@path/file.ext` for one file). Example:

     suppress:
       - F401
       - SC2086@scripts/legacy.sh

4. Never edit reports or code to silence a finding — suppressions live
   in `.polycheck.yml` so they are reviewable and revertible.

## Missing Tools

If the report mentions missing tools or the user asks about installing them:

1. Use the guided `polycheck.run` workflow again with
   `install_mode: "tools_only"`.
2. Ask the user to approve analyzer installation before setting
   `install_confirmed: true`.
3. The MCP surface has no separate doctor/install tools; for manual
   diagnostics use the CLI: `polycheck doctor`, `polycheck install`.
4. For tools requiring manual installation, such as Docker for sonarless:
   - **Docker**: Ask your LLM coding assistant to help install Docker
     for this OS. Common options:
     * Linux: `sudo apt install docker.io && sudo usermod -aG docker $USER`
     * Or follow https://docs.docker.com/get-docker/
     * After install, log out and back in for group changes to take effect
    - After Docker is installed, rerun `polycheck.run`; polycheck will
      offer to install sonarless if it is still missing.



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

Category notes:

- LINT: style + simple bug shapes, mostly auto-fixable; prefer the
  analyzer's --fix, suppress inline only when the rule truly doesn't fit.
- TYPE: may be real bugs or env noise ("library stubs not installed");
  stubs noise is FALSE POSITIVE for this run plus a mypy requirement.
- SECURITY: high signal, not always bugs; ask whether the dangerous
  operation is reachable with attacker-controlled input.
- DEAD_CODE: mostly REAL SMELL, not REAL BUG; many false positives in
  dynamic or plugin code; DEFER if removal would break tests.
- DEPS: add the missing dependency or remove the unused one; "dev-only"
  imports belong in optional-dependencies.
- CVE: upgrade to the fix version; if none exists, DEFER with a
  runtime mitigation.
- SECRETS: rotate the credential immediately, scrub history, then
  allowlist only after rotation.

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
        from mcp.types import AnyUrl, Resource, TextContent, Tool
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
        return await _call_tool_with_progress(server, name, arguments)

    @server.list_resources()
    async def _list_resources():
        return [
            Resource(
                uri=AnyUrl("polycheck://triage/prompt"),
                name="LLM triage prompt",
                description="The prompt to feed to an LLM with the markdown report.",
                mimeType="text/plain",
            ),
            Resource(
                uri=AnyUrl("polycheck://session/latest"),
                name="Latest polycheck session",
                description="The latest guided workflow summary.",
                mimeType="text/markdown",
            ),
            Resource(
                uri=AnyUrl("polycheck://setup"),
                name="LLM setup guide",
                description="Setup and operations guide for LLM coding "
                "assistants: profiles, prerequisites (Docker for "
                "sonarless), install policy.",
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


_WORKFLOW_TOOL_DESCRIPTION = (
    "Primary guided workflow entrypoint for normal use. This is the "
    "only tool most LLMs should call for polycheck. It checks dependencies, "
    "offers approved analyzer installs, runs the scan, writes reports, "
    "supports diff mode against a baseline (diff: true), and returns "
    "coverage metadata and next_action."
)


def _workflow_tool(name: str):
    from mcp.types import Tool

    return Tool(
        name=name,
        description=_WORKFLOW_TOOL_DESCRIPTION,
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
                "diff": {
                    "type": "boolean",
                    "description": "Only report findings that are new since the last "
                    "baseline (created by running polycheck with diff off and "
                    "saving it via `polycheck baseline`). Default: false.",
                },
                "profile": {
                    "type": "string",
                    "enum": ["pr", "deep"],
                    "description": "Scan preset. 'pr': fast tools only, findings "
                    "scoped to changed tracked files, HIGH severity floor. "
                    "'deep': every tool including heavy ones — use for project "
                    "onboarding. Default: full scan, MEDIUM floor.",
                },
                "parallel": {
                    "type": "boolean",
                    "description": "Run tools concurrently. Default: true.",
                },
            },
            "required": ["repo"],
        },
    )


def _build_tool_definitions():
    """Build the list of MCP tool definitions.

    Deliberately slim: two tools. Diagnostics, listings, explanations,
    and installs belong to the CLI (`polycheck doctor`, `polycheck
    install`, `polycheck list-tools`); fewer tools means LLMs pick the
    right one reliably.
    """
    from mcp.types import Tool

    return [
        _workflow_tool("polycheck.run"),
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
                    "profile": {
                        "type": "string",
                        "enum": ["pr", "deep"],
                        "description": "Scan preset: 'pr' (fast tools, changed-file "
                        "scope) or 'deep' (everything). Default: full scan.",
                    },
                },
                "required": ["repo"],
            },
        ),
    ]


def _dispatch_tool(name: str, arguments: dict):
    """Dispatch an MCP tool call to the appropriate handler.

    Deliberately slim (see _build_tool_definitions); unknown names —
    including tools retired in favor of their CLI equivalents — raise.
    """
    handlers = {
        "polycheck.run": _handle_polycheck,
        "polycheck.audit_run": _handle_audit_run,
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
        return "(no session yet — run polycheck.run first)"
    if uri == "polycheck://setup":
        from .readiness import SETUP_GUIDE

        return SETUP_GUIDE
    raise ValueError(f"Unknown resource: {uri}")


def _last(name: str) -> str:
    path = _LAST_RUN.get("report_dir")
    if not path:
        return "(no report yet — run polycheck.run first)"
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


def _resolve_profile_or_error(arguments: dict) -> ProfileSpec | None | list:
    """Resolve the profile argument; a list payload signals an error."""
    try:
        return resolve_profile(arguments.get("profile"))
    except ProfileError as exc:
        return _text_content({"error": str(exc)})


def _apply_change_scope(
    spec, repo: Path, findings: list
) -> tuple[list, dict | None]:
    """pr-style scoping; a non-None error payload signals failure."""
    changed = changed_files(repo)
    if changed is None:
        return findings, {
            "error": f"--profile {spec.name} requires a git repository",
        }
    return filter_by_scope(findings, changed), None


def _handle_audit_run(arguments: dict) -> list:
    """Run the scan primitive and return report paths plus context."""
    repo = _repo_from_arguments(arguments)
    if isinstance(repo, list):
        return repo

    profile_spec = _resolve_profile_or_error(arguments)
    if isinstance(profile_spec, list):
        return profile_spec

    cfg = Config.load(repo)
    severity = arguments.get("severity", "MEDIUM").upper()
    if severity not in Severity.__members__:
        return _text_content({"error": f"Unknown severity: {severity}"})

    dependency = _dependency_check(repo, cfg, tools=arguments.get("tools"))
    runner = Runner(repo=repo, config=cfg)
    findings, results, coverage = runner.run_with_coverage(
        parallel=bool(arguments.get("parallel", True)),
        tools=arguments.get("tools"),
        profile=profile_spec,
    )
    findings = dedupe(findings)
    findings = filter_by_severity(findings, severity)
    if profile_spec and profile_spec.scoped_to_changes:
        findings, scope_error = _apply_change_scope(profile_spec, repo, findings)
        if scope_error:
            return _text_content(scope_error)

    report_dir = _validate_report_dir(repo, cfg.output.report_dir)
    if isinstance(report_dir, list):
        return report_dir
    written: list[Path] = []
    for fmt in cfg.output.formats:
        written.extend(render_report(fmt, repo, findings, results,
                                     report_dir=report_dir, coverage=coverage))

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


async def _call_tool_with_progress(server, name: str, arguments: dict):
    """Dispatch a tool call, emitting spec-standard MCP progress
    notifications when the client requested them (``_meta.progressToken``).

    Only ``polycheck.run`` reports progress — it is the one long-running
    tool. Notifications are queued as tasks and awaited before the
    result returns so ordering is preserved.
    """
    import asyncio

    if name != "polycheck.run":
        return _dispatch_tool(name, arguments)

    ctx = server.request_context
    token = ctx.meta.progressToken if ctx.meta else None
    if token is None:
        return _handle_polycheck(arguments)

    pending: list[asyncio.Task] = []

    def progress(progress_value: float, message: str | None = None) -> None:
        pending.append(asyncio.create_task(
            ctx.session.send_progress_notification(token, progress_value, None, message)
        ))

    try:
        return _handle_polycheck(arguments, progress=progress)
    finally:
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def _handle_polycheck(arguments: dict, progress: Callable[[float, str | None], None] | None = None) -> list:
    """Run the guided workflow used by LLM coding assistants."""
    repo = _repo_from_arguments(arguments)
    if isinstance(repo, list):
        return repo

    profile_spec = _resolve_profile_or_error(arguments)
    if isinstance(profile_spec, list):
        return profile_spec

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    cfg = Config.load(repo)
    severity = arguments.get(
        "severity", default_severity(profile_spec)
    ).upper()
    install_mode = arguments.get("install_mode", "none")
    if install_mode not in {"none", "tools_only"}:
        return _text_content({"error": "install_mode must be none or tools_only"})
    install_confirmed = bool(arguments.get("install_confirmed", False))

    append_event(repo, run_id, {"event": "dependency_check_started"})
    dependency = _dependency_check(repo, cfg, tools=arguments.get("tools"))
    append_event(repo, run_id, {"event": "dependency_check_finished", **dependency})
    if progress:
        progress(0.15, "dependency check finished")

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
    if progress:
        progress(0.3, "scan started")
    cfg.severity_threshold = severity
    runner = Runner(repo=repo, config=cfg)
    findings, results, coverage = runner.run_with_coverage(
        parallel=bool(arguments.get("parallel", True)),
        tools=arguments.get("tools"),
        profile=profile_spec,
    )
    findings = dedupe(findings)
    findings = filter_by_severity(findings, cfg.severity_threshold)
    findings = apply_suppressions(findings, cfg.suppress)
    if profile_spec and profile_spec.scoped_to_changes:
        findings, scope_error = _apply_change_scope(profile_spec, repo, findings)
        if scope_error:
            return _text_content(scope_error)
    append_event(repo, run_id, {"event": "scan_finished", "total_findings": len(findings)})
    if progress:
        progress(0.7, "scan finished")

    diff_requested = bool(arguments.get("diff", False))
    baseline_info: dict | None = None
    if diff_requested:
        findings, baseline_info = _filter_to_new_findings(repo, cfg, findings)

    out_dir = _guided_report_dir(repo, cfg.output.report_dir, run_id)
    if isinstance(out_dir, list):
        return out_dir
    written: list[Path] = []

    for fmt in cfg.output.formats:
        written.extend(render_report(fmt, repo, findings, results,
                                     report_dir=out_dir, coverage=coverage))
    if progress:
        progress(0.9, "reports written")

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
    if baseline_info is not None:
        summary["baseline"] = baseline_info
    _LAST_RUN["latest_markdown"] = session["latest_markdown"]
    _LAST_RUN["latest_json"] = session["latest_json"]

    write_run_summary(repo, run_id, summary)
    return [TextContent(type="text", text=json.dumps(summary, indent=2, default=str))]


def _filter_to_new_findings(
    repo: Path, cfg: Config, findings: list[Finding]
) -> tuple[list[Finding], dict]:
    """Diff mode: keep only findings newer than the baseline and return
    the payload the summary should carry about it."""
    baseline = load_baseline(repo / cfg.output.report_dir)
    if baseline is None:
        return findings, {
            "diff": True,
            "baseline": None,
            "note": (
                "no baseline yet — take one with `polycheck baseline` so "
                "future runs report only new findings"
            ),
        }
    new = filter_by_baseline(findings, baseline)
    info = {
        "diff": True,
        "baseline_count": len(baseline),
        "known": len(findings) - len(new),
        "new": len(new),
    }
    return new, info


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


def _scan_coverage(results: list, missing_tools: list[dict], missing_system: list[dict]) -> dict:
    # not-applicable rows are visibility, not coverage — they must not
    # inflate the "N of M applicable analyzers ran" math.
    tools_run = [r.tool for r in results if r.status != "not-applicable"]
    applicable_tools = len(tools_run) + len(missing_tools)
    coverage = "full" if not missing_tools and not missing_system else "partial"
    warnings = []
    if missing_tools or missing_system:
        warnings.append(
            f"Partial scan: only {len(tools_run)} of {applicable_tools} applicable analyzers ran. "
            "No findings does not mean the repo is clean."
        )
    if missing_system:
        names = ", ".join(item.get("name", "system dependency") for item in missing_system)
        warnings.append(f"Missing system dependencies blocked some analyzers: {names}.")
    return {
        "coverage": coverage,
        "applicable_tools": applicable_tools,
        "tools_run": tools_run,
        "missing_tools": missing_tools,
        "missing_system_dependencies": missing_system,
        "warning": " ".join(warnings) if warnings else "",
    }


def _audit_summary(
    *,
    repo: Path,
    findings: list,
    results: list,
    reports: list[Path],
    dependency: dict,
    severity: str,
) -> dict:
    from .readiness import profile_guidance
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
        "resources": [
            "polycheck://findings/markdown",
            "polycheck://findings/json",
            "polycheck://setup",
        ],
        "profile_guidance": profile_guidance(),
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
    from .readiness import profile_guidance
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
    scan_coverage = _scan_coverage(results, missing_tools, missing_system)
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
        "scan_coverage": scan_coverage,
        "tools_run": tools_run,
        "tools_skipped": missing_tools + missing_system,
        "missing_tools": missing_tools,
        "missing_system_dependencies": missing_system,
        "install_requested": install_requested,
        "install_confirmed": install_confirmed,
        "install_results": install_results,
        "tools_failed": [r.tool for r in results if r.status in ("error", "timeout")],
        "reports": [str(p) for p in reports],
        "resources": [
            "polycheck://findings/markdown",
            "polycheck://findings/json",
            "polycheck://setup",
        ],
        "profile_guidance": profile_guidance(),
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
            return "ask user to confirm analyzer tool installation before continuing with polycheck.run"
        if missing_system:
            return (
                "system dependencies are missing, so some analyzers did not run; "
                "ask the user to install the listed system dependencies with their "
                "LLM coding assistant or rerun with available tools"
            )
        return "ask user to approve installing missing analyzers, then rerun polycheck.run"
    if any(f.fixable for f in findings):
        return f"ask user whether to fix {severity}+ findings or skip fixes"
    if findings:
        return "no fixable findings; ask user whether to lower the severity threshold, install skipped tools, or end the workflow"
    return ""



def _check_docker() -> dict:
    """Check if Docker is installed and running (single source of truth:
    readiness.docker_status, shared with `polycheck doctor --json`)."""
    from .readiness import docker_status

    return docker_status()
