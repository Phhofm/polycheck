"""Initializer for coding-assistant slash-command integrations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .workflows import WORKFLOW_TEMPLATES

HOSTS = ("kilo", "opencode", "claude")


@dataclass(frozen=True)
class InitAction:
    """One file that the initializer plans to write or skip."""

    host: str
    kind: str
    path: Path | None
    status: str
    message: str = ""


def normalize_hosts(hosts: list[str] | None) -> list[str]:
    """Normalize host CLI values."""
    values = hosts or ["all"]
    expanded: list[str] = []
    for value in values:
        for raw_host in value.split(","):
            host_value = raw_host.strip()
            if not host_value:
                continue
            if host_value == "all":
                expanded.extend(HOSTS)
            else:
                expanded.append(host_value)

    out: list[str] = []
    seen: set[str] = set()
    for host in expanded:
        host = host.lower()
        if host not in HOSTS:
            allowed = ", ".join((*HOSTS, "all"))
            raise ValueError(f"Unknown host '{host}'. Expected one of: {allowed}")
        if host not in seen:
            out.append(host)
            seen.add(host)
    return out


def resolve_workflow_path(
    *,
    host: str,
    scope: str,
    project_root: Path,
    home: Path,
) -> Path:
    """Resolve where a slash-command workflow file should live."""
    template = WORKFLOW_TEMPLATES[host]
    if scope == "project":
        return project_root / template.path
    if host == "kilo":
        return home / ".config" / "kilo" / "commands" / "polycheck.md"
    if host == "opencode":
        return home / ".config" / "opencode" / "commands" / "polycheck.md"
    return home / ".claude" / "skills" / "polycheck" / "SKILL.md"


def resolve_mcp_config_path(
    *,
    host: str,
    scope: str,
    project_root: Path,
    home: Path,
) -> Path | None:
    """Resolve MCP config path.

    Claude global/user-scope config is intentionally not written directly.
    Claude Code versions differ in how user-scope MCP servers are stored, so
    the initializer prints the official `claude mcp add` command for that case.
    """
    if scope == "project":
        if host == "claude":
            return project_root / ".mcp.json"
        if host == "kilo":
            return project_root / "kilo.jsonc"
        if host == "opencode":
            return project_root / "opencode.jsonc"
    if host == "kilo":
        return home / ".config" / "kilo" / "kilo.jsonc"
    if host == "opencode":
        return home / ".config" / "opencode" / "opencode.jsonc"
    if host == "claude":
        return home / ".claude.json"
    return None


def build_plan(
    *,
    hosts: list[str],
    scope: str,
    project_root: Path,
    home: Path,
    include_workflows: bool = True,
    include_mcp: bool = True,
) -> list[InitAction]:
    """Build all file actions for an initializer run."""
    actions: list[InitAction] = []
    for host in hosts:
        if include_workflows:
            actions.append(
                InitAction(
                    host=host,
                    kind="workflow",
                    path=resolve_workflow_path(
                        host=host,
                        scope=scope,
                        project_root=project_root,
                        home=home,
                    ),
                    status="planned",
                )
            )
        if include_mcp:
            path = resolve_mcp_config_path(
                host=host,
                scope=scope,
                project_root=project_root,
                home=home,
            )
            if path is None:
                actions.append(
                    InitAction(
                        host=host,
                        kind="mcp",
                        path=None,
                        status="skipped",
                        message="MCP config path is not available for this host/scope",
                    )
                )
            else:
                actions.append(
                    InitAction(
                        host=host,
                        kind="mcp",
                        path=path,
                        status="planned",
                    )
                )
    return actions


def apply_plan(
    actions: list[InitAction],
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[InitAction]:
    """Apply a plan and return the resulting actions."""
    results: list[InitAction] = []
    for action in actions:
        if action.kind == "workflow":
            results.append(_apply_workflow_action(action, force=force, dry_run=dry_run))
        elif action.kind == "mcp":
            results.append(_apply_mcp_action(action, force=force, dry_run=dry_run))
    return results


def _apply_workflow_action(
    action: InitAction,
    *,
    force: bool,
    dry_run: bool,
) -> InitAction:
    path = action.path
    if path is None:
        return InitAction(
            host=action.host,
            kind=action.kind,
            path=None,
            status="skipped",
            message="no path",
        )

    if path.exists() and not force:
        return InitAction(
            host=action.host,
            kind=action.kind,
            path=path,
            status="skipped",
            message="already exists; pass --force to overwrite",
        )

    if dry_run:
        return InitAction(
            host=action.host,
            kind=action.kind,
            path=path,
            status="planned",
            message="would write workflow" if not path.exists() else "would overwrite workflow",
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(WORKFLOW_TEMPLATES[action.host].content, encoding="utf-8")
    return InitAction(
        host=action.host,
        kind=action.kind,
        path=path,
        status="written",
        message="workflow written",
    )


def _apply_mcp_action(
    action: InitAction,
    *,
    force: bool,
    dry_run: bool,
) -> InitAction:
    path = action.path
    if path is None:
        return action

    if dry_run:
        status = "planned" if not path.exists() else "planned-merge"
        return InitAction(
            host=action.host,
            kind=action.kind,
            path=path,
            status=status,
            message="would merge MCP config",
        )

    merged = _merge_mcp_config(path, action.host)
    if isinstance(merged, str):
        return InitAction(
            host=action.host,
            kind=action.kind,
            path=path,
            status="skipped",
            message=merged,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return InitAction(
        host=action.host,
        kind=action.kind,
        path=path,
        status="written",
        message="MCP config merged",
    )


def _merge_mcp_config(path: Path, host: str) -> dict[str, Any] | str:
    """Merge polycheck MCP config into a JSON/JSONC file."""
    if path.exists():
        parsed = _read_json_file(path)
        if isinstance(parsed, str):
            return parsed
        data = parsed
    else:
        data = {}

    if not isinstance(data, dict):
        return f"{path} exists but is not a JSON object"

    if host in ("kilo", "opencode"):
        mcp = data.setdefault("mcp", {})
        if not isinstance(mcp, dict):
            return f"{path} has non-object 'mcp' key"
        mcp["polycheck"] = {
            "type": "local",
            "command": ["polycheck", "mcp"],
            "enabled": True,
        }
    elif host == "claude":
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            return f"{path} has non-object 'mcpServers' key"
        servers["polycheck"] = {
            "command": "polycheck",
            "args": ["mcp"],
        }
    else:
        return f"unsupported host: {host}"

    return data


def _read_json_file(path: Path) -> dict[str, Any] | list[Any] | str:
    """Read JSON. JSONC with comments is rejected to avoid destructive edits."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"could not read {path}: {exc}"

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if _strip_json_comments(text).strip():
            return (
                f"{path} contains comments or invalid JSON; "
                "convert it to valid JSON or pass --force with a manual edit"
            )
        return {}


def _strip_json_comments(text: str) -> str:
    """Return text with simple // and /* */ comments removed for detection."""
    without_line = re.sub(r"//.*", "", text)
    return re.sub(r"/\*.*?\*/", "", without_line, flags=re.DOTALL)


def format_action(action: InitAction) -> str:
    """Format one action for CLI output."""
    path = action.path or Path("—")
    if path.is_absolute():
        try:
            path = path.relative_to(Path.cwd())
        except ValueError:
            pass
    prefix = {
        "planned": "plan",
        "planned-merge": "plan",
        "written": "wrote",
        "skipped": "skip",
    }.get(action.status, action.status)
    suffix = f" — {action.message}" if action.message else ""
    return f"  {prefix}: {action.host}/{action.kind}: {path}{suffix}"
