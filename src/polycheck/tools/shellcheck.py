"""shellcheck — shell script linter (works for bash, sh, dash, ksh).

shellcheck's default output is the GNU-style
``file:line:column: severity: message [code]`` format.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool, iter_source_files

_SHELLCHECK_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*"
    r"(?P<severity>error|warning|note|info|style):\s*"
    r"(?P<message>.*?)(?:\s*\[(?P<code>SC\d+)\])?\s*$"
)


class ShellcheckTool(Tool):
    name = "shellcheck"
    category = Category.LINT
    languages = ["shell"]
    installer = "github-release:koalaman/shellcheck"

    def is_applicable(self, repo: Path) -> bool:
        return any(repo.glob("**/*.sh")) or any(repo.glob("**/bin/*"))

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("shellcheck") is None:
            return []
        # shellcheck takes file arguments, not a directory. Collect the
        # project shell scripts (vendored trees are skipped).
        files = [
            str(p) for p in iter_source_files(repo, ("*.sh", "*.bash"))
        ]
        if not files:
            return []
        # Use -f gcc for parseable one-line findings.
        cmd = ["shellcheck", "-f", "gcc", "--severity=style", *files]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        return self._parse(out.stdout + "\n" + out.stderr)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _SHELLCHECK_LINE.match(raw.strip())
            if not m:
                continue
            severity = {
                "error": Severity.HIGH,
                "warning": Severity.MEDIUM,
                "note": Severity.LOW,
                "info": Severity.LOW,
                "style": Severity.INFO,
            }.get(m.group("severity"), Severity.LOW)
            findings.append(
                Finding(
                    tool="shellcheck",
                    rule=m.group("code") or m.group("severity"),
                    severity=severity,
                    category=Category.LINT,
                    message=m.group("message").strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    fixable=False,
                    doc_url=f"https://www.shellcheck.net/wiki/{m.group('code') or ''}",
                    raw={"line": raw},
                )
            )
        return findings
