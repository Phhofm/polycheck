"""gitleaks — find secrets in git history and working tree.

We run ``gitleaks detect --report-format json --no-git`` which only
scans the working tree (faster, no clone dependency). gitleaks emits
a JSON array of findings.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool


class GitleaksTool(Tool):
    name = "gitleaks"
    category = Category.SECRETS
    languages = []            # applies to any git repo
    universal = True
    installer = "github:gitleaks/gitleaks"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / ".git").exists() or (repo / ".git").is_dir()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("gitleaks") is None:
            return []
        cmd = [
            "gitleaks", "detect",
            "--report-format=json",
            "--no-banner",
            "--source", str(repo),
        ]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        # gitleaks exits 1 when leaks are found; that's normal.
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for item in data:
            findings.append(
                Finding(
                    tool=self.name,
                    rule=item.get("RuleID", "secret"),
                    severity=Severity.CRITICAL,   # any secret is critical
                    category=Category.SECRETS,
                    message=item.get("Description") or item.get("Match", "")[:120],
                    file=item.get("File"),
                    line=item.get("StartLine"),
                    column=item.get("StartColumn"),
                    fixable=False,
                    doc_url="https://github.com/gitleaks/gitleaks#rules",
                    raw=item,
                )
            )
        return findings
