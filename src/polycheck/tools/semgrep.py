"""semgrep — multi-language pattern-based static analyzer.

semgrep's JSON output (``--json``) is an envelope with ``results`` and
``errors`` arrays. We take results only; errors are reported via the
ToolResult.error channel.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

_SEVERITY_MAP = {
    "INFO": Severity.INFO,
    "WARNING": Severity.MEDIUM,
    "ERROR": Severity.HIGH,
}


class SemgrepTool(Tool):
    name = "semgrep"
    category = Category.SECURITY
    languages = [
        "python", "javascript", "typescript", "go", "rust", "java",
        "ruby", "php", "csharp", "kotlin", "swift", "scala",
    ]
    installer = "pipx:semgrep"

    def is_applicable(self, repo: Path) -> bool:
        # semgrep is applicable everywhere there's source code.
        return any(repo.glob("**/*.*"))

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("semgrep") is None:
            return []
        # The "auto" config covers most common patterns without
        # requiring users to download the full ruleset.
        cmd = [
            "semgrep", "scan",
            "--config=auto",
            "--json",
            "--quiet",
            "--error",    # exit non-zero on findings so we can ignore the code
            "--no-rewrite-rule-ids",
        ]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=600
        )
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for r in data.get("results", []):
            extra = r.get("extra", {})
            severity = _SEVERITY_MAP.get(extra.get("severity", "WARNING"), Severity.MEDIUM)
            findings.append(
                Finding(
                    tool=self.name,
                    rule=r.get("check_id", "?").rsplit(".", 1)[-1],
                    severity=severity,
                    category=Category.SECURITY,
                    message=extra.get("message", "").splitlines()[0] if extra.get("message") else "",
                    file=r.get("path"),
                    line=extra.get("start", {}).get("line"),
                    column=extra.get("start", {}).get("col"),
                    fixable=bool(extra.get("fix")),
                    fix_command=None,
                    doc_url=r.get("check_id"),
                    raw=r,
                )
            )
        return findings
