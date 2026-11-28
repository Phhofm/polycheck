"""zizmor — GitHub Actions security analysis (CI/CD semantics).

Where actionlint checks workflow *syntax*, zizmor checks the security
semantics: template injection, credential persistence, excessive
permissions, impostor commits. pip-installable, JSON output via
``--format json``. Exit code 0 = no findings; findings produce a
non-zero exit with the JSON report on stdout.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

_SEVERITY = {
    "High": Severity.HIGH,
    "Medium": Severity.MEDIUM,
    "Low": Severity.LOW,
    "Informational": Severity.INFO,
}


class ZizmorTool(Tool):
    name = "zizmor"
    category = Category.SECURITY
    languages = ["github-actions"]
    installer = "pipx:zizmor"

    def is_applicable(self, repo: Path) -> bool:
        wf = repo / ".github" / "workflows"
        return wf.exists() and (any(wf.glob("*.yml")) or any(wf.glob("*.yaml")))

    def run(self, repo: Path) -> list[Finding]:
        # config may be None when instantiated directly (verify-tools)
        timeout = getattr(self.config, "timeout", None) or 300
        # Target "." with cwd=repo: zizmor echoes relative verbatim paths,
        # keeping Finding.file repo-relative (the reporters' contract).
        result = subprocess.run(
            ["zizmor", "--format", "json", "."],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if not result.stdout.strip():
            raise RuntimeError(
                f"zizmor exited {result.returncode}: "
                f"{(result.stderr or 'no output').strip()[:200]}"
            )
        findings: list[Finding] = []
        for issue in json.loads(result.stdout):
            if issue.get("ignored"):
                continue
            det = issue.get("determinations", {})
            location = ""
            row = None
            for loc in issue.get("locations", []):
                concrete = loc.get("concrete", {})
                if concrete:
                    location = concrete.get("location", {}).get(
                        "feature", ""
                    )
                    row = concrete.get("location", {}).get("start_point", {}).get("row")
                    break
            verbatim = ""
            for loc in issue.get("locations", []):
                key = loc.get("symbolic", {}).get("key", {})
                verbatim = key.get("Local", {}).get("verbatim_path", "")
                if verbatim:
                    break
            findings.append(
                Finding(
                    tool=self.name,
                    rule=str(issue.get("ident", "unknown")),
                    severity=_SEVERITY.get(
                        det.get("severity", "Low"), Severity.LOW
                    ),
                    category=self.category,
                    message=(
                        f"{issue.get('desc', 'workflow security issue')}"
                        f"{f' — {location}' if location else ''}"
                    ),
                    file=verbatim.removeprefix("./") or None,
                    line=(row + 1) if row is not None else None,
                    doc_url=issue.get("url"),
                    raw={"fixes": issue.get("fixes", [])},
                )
            )
        return findings
