"""deptry — find unused / missing Python dependencies.

deptry's text output is one line per finding. We parse it.

DEP001: imported but missing from the dependency definitions
DEP002: defined as a dependency but not used in the codebase
DEP003: imported but declared as a dev dependency
DEP004: imported but declared as an optional dependency
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# File-level findings (e.g. DEP002) print "file: DEPxxx 'name' ...";
# code-level findings (e.g. DEP001) print "file:line:col: DEPxxx ...".
# Line and column are therefore optional groups.
_DEPTRY_LINE = re.compile(
    r"^(?P<file>[^:]+):"
    r"(?:(?P<line>\d+):(?:(?P<col>\d+):)?)?"
    r"\s*(?P<code>DEP\d+)\s*"
    r"'(?P<name>[^']+)'\s*(?P<rest>.+)$"
)


class DeptryTool(Tool):
    name = "deptry"
    category = Category.DEPS
    languages = ["python"]
    installer = "pipx:deptry"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "pyproject.toml").exists()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("deptry") is None:
            return []
        out = subprocess.run(
            ["deptry", "."], cwd=repo, capture_output=True, text=True, timeout=300
        )
        # deptry exits non-zero when findings exist and prints them to
        # stderr (stdout carries progress notes only).
        return self._parse(out.stdout + "\n" + out.stderr)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        # deptry emits ANSI color codes by default; strip them.
        import re as _re
        ansi = _re.compile(r"\x1b\[[0-9;]*m")
        findings: list[Finding] = []
        for raw in text.splitlines():
            clean = ansi.sub("", raw).strip()
            m = _DEPTRY_LINE.match(clean)
            if not m:
                continue
            severity = {
                "DEP001": Severity.MEDIUM,  # missing
                "DEP002": Severity.LOW,     # unused
                "DEP003": Severity.LOW,     # dev-only
                "DEP004": Severity.LOW,     # optional-only
            }.get(m.group("code"), Severity.MEDIUM)
            line_text = m.group("line")
            col_text = m.group("col")
            findings.append(
                Finding(
                    tool="deptry",
                    rule=m.group("code"),
                    severity=severity,
                    category=Category.DEPS,
                    message=f"{m.group('name')}: {m.group('rest').strip()}",
                    file=m.group("file"),
                    line=int(line_text) if line_text else None,
                    column=int(col_text) if col_text else None,
                    fixable=False,
                    raw={"line": clean},
                )
            )
        return findings
