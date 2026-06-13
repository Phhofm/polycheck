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
                    severity=Severity.INFO if item.get("code", "").startswith("N")
                    else Severity.LOW,
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
