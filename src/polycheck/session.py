"""Session logging for guided polycheck workflows."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def new_run_id() -> str:
    """Return a stable, sortable run id for a workflow invocation."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_dir(repo: Path, run_id: str) -> Path:
    """Return the per-run log directory."""
    return repo / ".polycheck" / "runs" / run_id


def append_event(repo: Path, run_id: str, event: dict[str, Any]) -> Path:
    """Append one structured progress event to the run log."""
    directory = run_dir(repo, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "run.jsonl"
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")
    return path


def write_run_summary(repo: Path, run_id: str, summary: dict[str, Any]) -> Path:
    """Write a human-readable summary for one guided run."""
    directory = run_dir(repo, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "summary.md"
    path.write_text(_render_summary(summary), encoding="utf-8")
    return path


def write_session_summary(repo: Path, payload: dict[str, Any]) -> dict[str, str]:
    """Write the latest workflow summary under ``.polycheck/``."""
    base = repo / ".polycheck"
    sessions = base / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)

    run_id = new_run_id()
    md_path = sessions / f"{run_id}.md"
    json_path = sessions / f"{run_id}.json"

    md_path.write_text(_render_summary(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    latest_md = base / "latest.md"
    latest_json = base / "latest.json"
    latest_md.write_text(_render_summary(payload), encoding="utf-8")
    latest_json.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    return {
        "markdown": str(md_path),
        "json": str(json_path),
        "latest_markdown": str(latest_md),
        "latest_json": str(latest_json),
    }


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# polycheck session",
        "",
        f"**Repo:** `{payload.get('repo', '')}`",
        f"**Status:** {payload.get('status', '')}",
        "",
        "## Next action",
        "",
        payload.get("next_action", "none"),
        "",
        "## Findings",
        "",
        f"Total: {payload.get('total_findings', 0)}",
        "",
    ]

    by_severity = payload.get("by_severity", {})
    if by_severity:
        lines.extend(["| Severity | Count |", "|----------|-------|"])
        for severity, count in by_severity.items():
            lines.append(f"| {severity} | {count} |")
        lines.append("")

    lines.extend(["## Tools run", ""])
    tools_run = payload.get("tools_run", [])
    if tools_run:
        lines.extend([
            "| Tool | Status | Findings |",
            "|------|--------|----------|",
        ])
        for tool in tools_run:
            lines.append(
                f"| {tool.get('name', '')} | {tool.get('status', '')} | "
                f"{tool.get('finding_count', 0)} |"
            )
    else:
        lines.append("No tools ran.")
    lines.append("")

    missing_tools = payload.get("missing_tools", [])
    if missing_tools:
        lines.extend(["## Missing tools", ""])
        for tool in missing_tools:
            lines.append(f"- {tool.get('name', '')}: {tool.get('install_hint', '')}")
        lines.append("")

    missing_system = payload.get("missing_system_dependencies", [])
    if missing_system:
        lines.extend(["## Missing system dependencies", ""])
        for dep in missing_system:
            lines.append(f"- {dep.get('name', '')}: {dep.get('install_hint', '')}")
        lines.append("")

    reports = payload.get("reports", [])
    if reports:
        lines.extend(["## Reports", ""])
        for report in reports:
            lines.append(f"- `{report}`")
        lines.append("")

    session = payload.get("session", {})
    if session:
        lines.extend(["## Session files", ""])
        for key, value in session.items():
            lines.append(f"- {key}: `{value}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
