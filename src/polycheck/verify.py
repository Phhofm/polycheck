"""Supported-tool verification helpers."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .registry import ToolRegistry, default_registry
from .tools.base import Tool

HEAVY_TOOLS = {"sonarless", "semgrep", "pip-audit", "npm-audit"}


@dataclass(frozen=True)
class ToolVerification:
    """Result of verifying one supported analyzer."""

    tool: str
    status: str
    installed: bool
    applicable: bool
    findings: int = 0
    duration_sec: float = 0.0
    message: str = ""


def verify_tools(
    registry: ToolRegistry | None = None,
    *,
    install: bool = False,
    include_heavy: bool = False,
    tools: list[str] | None = None,
    work_dir: Path | None = None,
) -> list[ToolVerification]:
    """Run every supported tool against a synthetic repo.

    Missing tools are reported as skipped, not errors. Heavy tools that use
    Docker or network access are skipped unless ``include_heavy`` is true.
    """
    reg = registry or default_registry
    base = work_dir or Path(tempfile.mkdtemp(prefix="polycheck-verify-"))
    selected = [name for name in (tools or [])]
    results: list[ToolVerification] = []

    for cls in reg.all():
        if selected and cls.name not in selected:
            continue
        repo = base / cls.name
        repo.mkdir(parents=True, exist_ok=True)
        _seed_repo(cls.name, repo)
        results.append(
            verify_one(
                cls,
                repo,
                install=install,
                include_heavy=include_heavy,
            )
        )
    return results


def verify_one(
    tool_cls: type[Tool],
    repo: Path,
    *,
    install: bool = False,
    include_heavy: bool = False,
) -> ToolVerification:
    """Verify one tool class."""
    tool = tool_cls()
    if tool_cls.name in HEAVY_TOOLS and not include_heavy:
        return ToolVerification(
            tool=tool_cls.name,
            status="skipped-heavy",
            installed=tool.is_installed(),
            applicable=_safe_applicable(tool, repo),
            message="pass --include-heavy to run Docker/network-heavy tools",
        )

    if install and not tool.is_installed() and tool.can_auto_install():
        ok, msg = tool.install()
        if not ok:
            return ToolVerification(
                tool=tool_cls.name,
                status="install-failed",
                installed=False,
                applicable=_safe_applicable(tool, repo),
                message=msg,
            )

    if not tool.is_installed():
        return ToolVerification(
            tool=tool_cls.name,
            status="skipped-not-installed",
            installed=False,
            applicable=_safe_applicable(tool, repo),
            message=tool.install_hint(),
        )

    if not _safe_applicable(tool, repo):
        return ToolVerification(
            tool=tool_cls.name,
            status="skipped-not-applicable",
            installed=True,
            applicable=False,
        )

    start = time.monotonic()
    try:
        findings = tool.run(repo)
    except subprocess.TimeoutExpired:
        return ToolVerification(
            tool=tool_cls.name,
            status="timeout",
            installed=True,
            applicable=True,
            duration_sec=time.monotonic() - start,
            message="tool timed out",
        )
    except Exception as exc:  # noqa: BLE001 — verification should capture tool crashes
        return ToolVerification(
            tool=tool_cls.name,
            status="error",
            installed=True,
            applicable=True,
            duration_sec=time.monotonic() - start,
            message=f"{type(exc).__name__}: {exc}",
        )

    return ToolVerification(
        tool=tool_cls.name,
        status="ok" if findings else "no-findings",
        installed=True,
        applicable=True,
        findings=len(findings),
        duration_sec=time.monotonic() - start,
    )


def _safe_applicable(tool: Tool, repo: Path) -> bool:
    try:
        return tool.is_applicable(repo)
    except Exception:  # noqa: BLE001
        return False


def _seed_repo(tool_name: str, repo: Path) -> None:
    """Create a synthetic repo that makes most tools applicable."""
    (repo / ".git").mkdir(exist_ok=True)
    (repo / "pyproject.toml").write_text(
        """
[project]
name = "polycheck-verify"
version = "0.0.0"
dependencies = ["requests==2.0.0"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "import os\n\nx: int = 'bad'\n\ndef unused_helper() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        json.dumps(
            {
                "name": "polycheck-verify",
                "private": True,
                "type": "module",
                "scripts": {
                    "lint": "eslint .",
                    "typecheck": "tsc --noEmit",
                },
                "dependencies": {"left-pad": "1.3.0"},
                "devDependencies": {
                    "eslint": "latest",
                    "typescript": "latest",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "eslint.config.js").write_text(
        """
export default [
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
    },
    rules: {
      "no-unused-vars": "error",
    },
  },
];
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (repo / "app.js").write_text("const unused = 1;\nconsole.log(unused);\n", encoding="utf-8")
    (repo / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ESNext",
                    "strict": True,
                    "noEmit": True,
                },
                "include": ["*.ts"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo / "bad.ts").write_text("const value: number = 'bad';\n", encoding="utf-8")
    (repo / "Dockerfile").write_text("FROM ubuntu\nRUN rm -rf /tmp\n", encoding="utf-8")
    (repo / "script.sh").write_text("#!/bin/sh\necho $HOME\n", encoding="utf-8")
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(
        """
name: ci
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - runz: echo hello
""".strip()
        + "\n",
        encoding="utf-8",
    )

    if tool_name == "gitleaks":
        (repo / "secret.txt").write_text(
            "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n",
            encoding="utf-8",
        )
