"""gitleaks — find secrets in the working tree.

We run ``gitleaks detect --no-git`` which scans the working tree only
(faster, no clone dependency), writing its JSON report to a temp file
via ``--report-path`` (stdout behavior differs between gitleaks
versions). gitleaks exits 1 when leaks are found; that's normal.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool


class GitleaksTool(Tool):
    name = "gitleaks"
    category = Category.SECRETS
    languages = []            # applies to any git repo
    universal = True
    installer = "github-release:gitleaks/gitleaks"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / ".git").exists() or (repo / ".git").is_dir()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("gitleaks") is None:
            return []
        with tempfile.TemporaryDirectory(prefix="polycheck-gitleaks-") as tmp_name:
            report_path = Path(tmp_name) / "gitleaks-report.json"
            cmd = [
                "gitleaks", "detect",
                "--report-format", "json",
                "--report-path", str(report_path),
                "--no-banner",
                "--no-git",
                "--source", str(repo),
            ]
            out = subprocess.run(
                cmd, cwd=repo, capture_output=True, text=True, timeout=300
            )
            # Exit 1 = leaks found, 0 = clean. Anything else is a real
            # failure — surface it so the runner reports an error instead
            # of silently reporting "no findings".
            if out.returncode not in (0, 1):
                detail = (out.stderr or out.stdout).strip()[:200]
                raise RuntimeError(f"gitleaks exited {out.returncode}: {detail}")
            if not report_path.exists():
                return []
            try:
                data = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
            if not isinstance(data, list):
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
