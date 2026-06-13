"""mypy — Python static type checker.

mypy doesn't have a stable JSON output yet (the ``--output json`` flag
was experimental). We use plain text and parse the well-known
``path:line: severity: message [code]`` format. This format has been
stable across mypy 0.x and 1.x.

mypy has no auto-fix; type errors are reported and the LLM triages.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# mypy's "file:line: severity: message" line. The optional error code
# in brackets is parsed separately.
_MYPY_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?:\s*)?(?P<severity>error|warning|note):\s*"
    r"(?P<message>.*?)(?:\s*\[(?P<code>[^\]]+)\])?\s*$"
)


class MypyTool(Tool):
    name = "mypy"
    category = Category.TYPE
    languages = ["python"]
    installer = "pipx:mypy"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "pyproject.toml").exists() or any(repo.glob("**/*.py"))

    def run(self, repo: Path) -> list[Finding]:
        cmd = ["mypy", "--no-error-summary", "--show-column", "."]
        # Allow mypy itself to be missing (linter venvs may not have it).
        import shutil
        if shutil.which("mypy") is None:
            return []
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        # mypy exits non-zero on findings; we ignore the exit code.
        text = out.stdout + "\n" + out.stderr
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _MYPY_LINE.match(raw.strip())
            if not m:
                continue
            severity = {
                "error": Severity.HIGH,
                "warning": Severity.MEDIUM,
                "note": Severity.INFO,
            }.get(m.group("severity"), Severity.MEDIUM)
            # "import not found" / "library stubs not installed" are
            # environment noise, not code defects. Mark them LOW so
            # they sort below real type errors.
            msg = m.group("message")
            if "Cannot find implementation" in msg or "Library stubs not installed" in msg:
                severity = Severity.LOW
            findings.append(
                Finding(
                    tool="mypy",
                    rule=m.group("code") or "unknown",
                    severity=severity,
                    category=Category.TYPE,
                    message=msg,
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=None,
                    fixable=False,
                    doc_url=f"https://mypy.readthedocs.io/en/stable/_refs.html#code-{m.group('code') or 'unknown'}",
                    raw={"line": raw},
                )
            )
        return findings
