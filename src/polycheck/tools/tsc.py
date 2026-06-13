"""tsc — TypeScript compiler (type checking only).

We run ``tsc --noEmit`` to get the well-known text output:

    path/to/file.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.

The (line,col) format in parens differs from mypy's, so it gets its
own parser.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

_TSC_LINE = re.compile(
    r"^(?P<file>[^:(][^:]*?)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<severity>error|warning|info):\s*"
    r"(?P<code>TS\d+):\s*"
    r"(?P<message>.*)$"
)


class TscTool(Tool):
    name = "tsc"
    category = Category.TYPE
    languages = ["javascript", "typescript"]
    installer = "npm:typescript"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "tsconfig.json").exists()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("tsc") is None and shutil.which("npx") is None:
            return []
        binary = "tsc" if shutil.which("tsc") else "npx"
        cmd = [binary, "tsc", "--noEmit", "--pretty", "false"]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        text = out.stdout + "\n" + out.stderr
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _TSC_LINE.match(raw.strip())
            if not m:
                continue
            severity = {
                "error": Severity.HIGH,
                "warning": Severity.MEDIUM,
                "info": Severity.INFO,
            }.get(m.group("severity"), Severity.MEDIUM)
            findings.append(
                Finding(
                    tool="tsc",
                    rule=m.group("code"),
                    severity=severity,
                    category=Category.TYPE,
                    message=m.group("message"),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    fixable=False,
                    raw={"line": raw},
                )
            )
        return findings
