"""vulture — find dead Python code.

vulture has no JSON output; the default text format is
``file:line: unused function 'name' (60% confidence)``.

Note: vulture has a *high* false-positive rate on Python protocol
methods (``__getattr__``, ``__dir__``, ``forward`` in nn.Module
subclasses) and on cross-file call sites in ``tests/``. The whitelist
file ``.vulture-whitelist.py`` at the repo root (when present) is
passed to vulture to silence those.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

_VULTURE_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):\s*"
    r"unused (?P<kind>\w+)\s+'(?P<name>[^']+)'\s*"
    r"\((?P<confidence>\d+)%\s*confidence\)\s*$"
)


class VultureTool(Tool):
    name = "vulture"
    category = Category.DEAD_CODE
    languages = ["python"]
    installer = "pipx:vulture"

    def is_applicable(self, repo: Path) -> bool:
        return any(repo.glob("**/*.py"))

    def run(self, repo: Path) -> list[Finding]:
        # vulture has a JSON output too, but the text format is easier
        # to read in the report. We use the text format.
        import shutil
        if shutil.which("vulture") is None:
            return []

        cmd = ["vulture", "."]
        # If the user has a whitelist at the repo root, pass it too.
        for name in (".vulture-whitelist.py", "vulture_whitelist.py"):
            wl = repo / name
            if wl.exists():
                cmd.append(str(wl.relative_to(repo)))

        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        # vulture exits 1 when findings exist; 0 when none; 2 on error.
        if out.returncode >= 2:
            return []
        return self._parse(out.stdout)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _VULTURE_LINE.match(raw.strip())
            if not m:
                continue
            findings.append(
                Finding(
                    tool="vulture",
                    rule=f"unused-{m.group('kind')}",
                    severity=Severity.LOW,
                    category=Category.DEAD_CODE,
                    message=f"Unused {m.group('kind')} '{m.group('name')}'",
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=None,
                    fixable=False,
                    raw={"line": raw, "confidence": int(m.group("confidence"))},
                )
            )
        return findings
