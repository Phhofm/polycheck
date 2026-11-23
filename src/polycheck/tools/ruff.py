"""ruff — fast Python linter + formatter (lint mode for findings).

ruff emits JSON when given ``--output-format=json``. Each item has
``code`` (rule id), ``message``, ``location.row``/``column``, and
``filename``. Most rules are auto-fixable via ``ruff check --fix``.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# Bug-shaped rules that survive the default MEDIUM severity filter:
# F821 undefined name and F811 redefinition break at runtime.
_HIGH_RULES = {"F821", "F811"}
# Comparison/exception handling mistakes (== None, bare except, lambda
# assignment, ambiguous names): real bug shapes, but often intentional.
_MEDIUM_RULES = {"E711", "E712", "E713", "E714", "E722", "E731", "E741"}


def _severity_for(code: str) -> Severity:
    if code in _HIGH_RULES:
        return Severity.HIGH
    if code in _MEDIUM_RULES:
        return Severity.MEDIUM
    if code.startswith("N"):
        return Severity.INFO  # pep8-naming is style
    return Severity.LOW


class RuffTool(Tool):
    name = "ruff"
    category = Category.LINT
    languages = ["python"]
    installer = "pipx:ruff"

    def is_applicable(self, repo: Path) -> bool:
        return any(repo.glob("**/*.py")) or (repo / "pyproject.toml").exists()

    def run(self, repo: Path) -> list[Finding]:
        cmd = ["ruff", "check", "--output-format=json", "--no-fix", "."]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        # ruff returns non-zero when findings exist; that's normal.
        if not out.stdout.strip():
            return []
        try:
            items = json.loads(out.stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for item in items:
            loc = item.get("location", {})
            findings.append(
                Finding(
                    tool=self.name,
                    rule=item.get("code", "?"),
                    severity=_severity_for(item.get("code", "")),
                    category=self.category,
                    message=item.get("message", ""),
                    file=item.get("filename"),
                    line=loc.get("row"),
                    column=loc.get("column"),
                    fixable=item.get("fix") is not None,
                    fix_command="ruff check --fix ." if any(
                        it.get("fix") for it in items
                    ) else None,
                    doc_url=f"https://docs.astral.sh/ruff/rules/{item.get('code', '').lower()}",
                    raw=item,
                )
            )
        return findings

    def fix_command(self, repo: Path) -> str | None:
        return "ruff check --fix ."
