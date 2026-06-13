"""actionlint — GitHub Actions workflow linter.

actionlint is a single-binary tool. Default output is a one-line
diagnostic per finding. It exits 1 when findings exist.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# actionlint output:
#   .github/workflows/ci.yml:10:5: unexpected key "runs" in workflow ... [syntax_check]
_ACTIONLINT_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*"
    r"(?P<message>.*?)(?:\s*\[(?P<code>[^\]]+)\])?\s*$"
)


class ActionlintTool(Tool):
    name = "actionlint"
    category = Category.LINT
    languages = []   # applies to GH Actions
    universal = False
    installer = "github:rhysd/actionlint"

    def is_applicable(self, repo: Path) -> bool:
        wf = repo / ".github" / "workflows"
        return wf.exists() and any(wf.glob("*.yml")) or any(wf.glob("*.yaml"))

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("actionlint") is None:
            return []
        out = subprocess.run(
            ["actionlint", "-no-color"],
            cwd=repo, capture_output=True, text=True, timeout=120
        )
        text = out.stdout + "\n" + out.stderr
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _ACTIONLINT_LINE.match(raw.strip())
            if not m:
                continue
            findings.append(
                Finding(
                    tool="actionlint",
                    rule=m.group("code") or "syntax_check",
                    severity=Severity.MEDIUM,
                    category=Category.LINT,
                    message=m.group("message").strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    fixable=False,
                    raw={"line": raw},
                )
            )
        return findings
