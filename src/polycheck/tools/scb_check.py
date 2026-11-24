"""scb-check — SlopCodeBench verbosity and erosion metrics.

We run ``scb-check check .`` (human-readable output) and parse the
finding blocks. scb-check detects duplicated AST blocks (DRY slop),
ast-grep slop patterns (``range(len(x))``, ``dict.get(k, None)``,
trivial wrappers, ...), and erosion: functions whose complexity mass
concentrates above the complexity threshold — the measurable proxies
for AI code slop (see https://www.scbench.ai).

Exit codes: 0 = clean, 1 = findings (normal), 2 = usage error.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool, iter_source_files

_LOC = re.compile(r"^\s*┌─\s*(?P<file>[^:]+):(?P<line>\d+)(?::(?P<col>\d+))?\s*$")
_SLOP = re.compile(r"^warning\[(?P<rule>[^\]]+)\]:\s*(?P<msg>.*)$")
_EROSION = re.compile(r"^erosion: function `(?P<name>[^`]+)` exceeds (?P<kind>cognitive )?complexity threshold")
_DUP = re.compile(r"^duplicate-structure: duplicated block \((?P<lines>\d+) lines, (?P<n>\d+) instances\)")
_METRIC = re.compile(r"^=\s*(?P<kind>cognitive complexity|complexity): (?P<value>\d+)")

_SEV = {"warning": Severity.LOW}


class ScbCheckTool(Tool):
    name = "scb-check"
    category = Category.DUPLICATION
    languages = ["python"]  # slop rules are Python-only; clones/erosion are cross-language
    universal = False
    installer = "pipx:scb-check"

    def is_applicable(self, repo: Path) -> bool:
        return next(iter_source_files(repo, ("*.py",)), None) is not None

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("scb-check") is None:
            return []
        out = subprocess.run(
            ["scb-check", "check", ".", *self.extra_args()],
            cwd=repo, capture_output=True, text=True, timeout=600,
        )
        # Exit 1 = findings exist (normal); 2 = usage error.
        if out.returncode >= 2:
            raise RuntimeError(
                f"scb-check exited {out.returncode}: {(out.stderr or out.stdout).strip()[:200]}"
            )
        return self._parse(out.stdout)

    def _parse(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        pending: dict | None = None

        def flush() -> None:
            nonlocal pending
            if pending and pending.get("file"):
                findings.append(self._finding(**pending))
            pending = None

        for raw in text.splitlines():
            m = _SLOP.match(raw)
            if m:
                flush()
                pending = {
                    "rule": m.group("rule"),
                    "message": m.group("msg"),
                    "severity": Severity.LOW,
                    "category": Category.LINT,
                }
                continue

            m = _EROSION.match(raw)
            if m:
                flush()
                pending = {
                    "rule": (
                        "cognitive-erosion" if m.group("kind") else "cyclomatic-erosion"
                    ),
                    "message": f"function `{m.group('name')}` exceeds "
                    f"{'cognitive ' if m.group('kind') else ''}complexity threshold",
                    "severity": Severity.MEDIUM,
                    "category": Category.COMPLEXITY,
                    "await_metric": True,
                }
                continue

            m = _DUP.match(raw)
            if m:
                flush()
                pending = {
                    "rule": "duplicate-structure",
                    "message": (
                        f"duplicated block ({m.group('lines')} lines, "
                        f"{m.group('n')} instances)"
                    ),
                    "severity": Severity.MEDIUM,
                    "category": Category.DUPLICATION,
                }
                continue

            loc = _LOC.match(raw)
            if loc:
                # Attach the first location of the pending finding; extra
                # boxes (secondary duplicate instances) are ignored.
                if pending and "file" not in pending:
                    pending["file"] = loc.group("file")
                    pending["line"] = int(loc.group("line"))
                    if loc.group("col"):
                        pending["column"] = int(loc.group("col"))
                continue

            m = _METRIC.match(raw)
            if m and pending and pending.get("await_metric"):
                pending["message"] += f" ({m.group('kind')}: {m.group('value')})"
                flush()
                continue

        flush()
        return findings

    @staticmethod
    def _finding(**kw) -> Finding:
        return Finding(
            tool="scb-check",
            rule=kw["rule"],
            severity=kw["severity"],
            category=kw["category"],
            message=kw["message"],
            file=kw.get("file"),
            line=kw.get("line"),
            column=kw.get("column"),
            fixable=False,
        )
