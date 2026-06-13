"""hadolint — Dockerfile linter.

hadolint is a single binary; default output is one finding per line
in the same gcc-like format as shellcheck.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

_HADOLINT_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+)\s*"
    r"(?P<severity>error|warning|info|style):\s*"
    r"(?P<message>.*?)(?:\s*\[(?P<code>[^\]]+)\])?\s*$"
)


class HadolintTool(Tool):
    name = "hadolint"
    category = Category.LINT
    languages = []   # applies to Dockerfiles
    universal = False
    installer = "brew:hadolint"

    def is_applicable(self, repo: Path) -> bool:
        return any(repo.glob("**/Dockerfile*")) or (repo / "Dockerfile").exists()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("hadolint") is None:
            return []
        # Collect all Dockerfiles; hadolint takes files, not dirs.
        dockerfiles = list(repo.glob("**/Dockerfile*")) + [repo / "Dockerfile"]
        dockerfiles = [str(p) for p in dockerfiles if p.is_file()]
        if not dockerfiles:
            return []
        cmd = ["hadolint", "--no-fail", "--format", "gnu"] + dockerfiles
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=120
        )
        return self._parse(out.stdout + "\n" + out.stderr)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _HADOLINT_LINE.match(raw.strip())
            if not m:
                continue
            severity = {
                "error": Severity.HIGH,
                "warning": Severity.MEDIUM,
                "info": Severity.LOW,
                "style": Severity.INFO,
            }.get(m.group("severity"), Severity.LOW)
            findings.append(
                Finding(
                    tool="hadolint",
                    rule=m.group("code") or m.group("severity"),
                    severity=severity,
                    category=Category.LINT,
                    message=m.group("message").strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=0,
                    fixable=False,
                    doc_url=f"https://github.com/hadolint/hadolint/wiki/{m.group('code') or ''}",
                    raw={"line": raw},
                )
            )
        return findings
