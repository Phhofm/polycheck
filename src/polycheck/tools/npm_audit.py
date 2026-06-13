"""npm audit — scan JS/TS dependencies for known CVEs.

Calls ``npm audit --json``. The output shape is stable across npm
versions 7+: a top-level object with ``vulnerabilities`` (per-package
details) and ``metadata`` (counts). We flatten to one Finding per
vuln×package combo.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# npm's severity string → our Severity
_NPM_SEV = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "moderate": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
}


class NpmAuditTool(Tool):
    name = "npm-audit"
    category = Category.CVE
    languages = ["javascript", "typescript"]
    installer = "brew:npm"   # comes with Node.js itself

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "package.json").exists()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("npm") is None:
            return []
        out = subprocess.run(
            ["npm", "audit", "--json"],
            cwd=repo, capture_output=True, text=True, timeout=300
        )
        # npm audit exits non-zero on findings; we ignore that.
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for pkg_name, info in data.get("vulnerabilities", {}).items():
            severity = _NPM_SEV.get(info.get("severity"), Severity.MEDIUM)
            for via in info.get("via", []):
                if not isinstance(via, dict):
                    continue
                findings.append(
                    Finding(
                        tool=self.name,
                        rule=via.get("source") or "CVE-UNKNOWN",
                        severity=severity,
                        category=self.category,
                        message=f"{pkg_name} {info.get('range','')}: {via.get('title','')}",
                        file=pkg_name,
                        line=0,
                        column=0,
                        fixable=bool(info.get("fixAvailable")),
                        fix_command=f"npm install {pkg_name}@latest",
                        doc_url=via.get("url"),
                        raw=info,
                    )
                )
        return findings
