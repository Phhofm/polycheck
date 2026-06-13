"""depcheck — find unused / missing JS/TS dependencies.

Parses depcheck's plain text output. Each finding is one line of the
form::

    Missing: package-name
    Unused: another-package
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool


class DepcheckTool(Tool):
    name = "depcheck"
    category = Category.DEPS
    languages = ["javascript", "typescript"]
    installer = "npm:depcheck"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "package.json").exists()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("depcheck") is None and shutil.which("npx") is None:
            return []
        binary = "depcheck" if shutil.which("depcheck") else "npx"
        # depcheck's JSON output is unstable across versions, so we
        # use text. -q makes it print only findings.
        cmd = [binary, "depcheck", ".", "-q", "--no-dev"]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        return self._parse(out.stdout + "\n" + out.stderr)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            line = raw.strip()
            m = re.match(r"^(Missing|Unused):\s*(.+)$", line)
            if not m:
                continue
            kind, pkg = m.group(1), m.group(2)
            severity = Severity.MEDIUM if kind == "Missing" else Severity.LOW
            findings.append(
                Finding(
                    tool="depcheck",
                    rule=f"depcheck-{kind.lower()}",
                    severity=severity,
                    category=Category.DEPS,
                    message=f"{kind} dependency: {pkg}",
                    file=pkg,
                    line=0,
                    column=0,
                    fixable=False,
                    raw={"line": line},
                )
            )
        return findings
