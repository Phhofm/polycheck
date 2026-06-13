"""knip — find unused files, exports, and dependencies in JS/TS.

Knip's JSON output is the cleanest of the JS tools: a list of issue
objects with a type (``files``, ``exports``, ``dependencies``,
``devDependencies``…), file path, and a short symbol name.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# Knip issue type → polycheck (category, severity)
_TYPE_MAP = {
    "files": (Category.DEAD_CODE, Severity.MEDIUM),
    "exports": (Category.DEAD_CODE, Severity.LOW),
    "types": (Category.DEAD_CODE, Severity.LOW),
    "nsExports": (Category.DEAD_CODE, Severity.LOW),
    "nsTypes": (Category.DEAD_CODE, Severity.LOW),
    "dependencies": (Category.DEPS, Severity.MEDIUM),
    "devDependencies": (Category.DEPS, Severity.LOW),
    "optionalPeerDependencies": (Category.DEPS, Severity.LOW),
    "unlisted": (Category.DEPS, Severity.MEDIUM),
    "binaries": (Category.DEPS, Severity.LOW),
    "duplicates": (Category.DEPS, Severity.LOW),
    "enumMembers": (Category.DEAD_CODE, Severity.LOW),
    "classMembers": (Category.DEAD_CODE, Severity.LOW),
    "namespaceMembers": (Category.DEAD_CODE, Severity.LOW),
}


class KnipTool(Tool):
    name = "knip"
    category = Category.DEAD_CODE
    languages = ["javascript", "typescript"]
    installer = "npm:knip"

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "package.json").exists()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("knip") is None and shutil.which("npx") is None:
            return []
        binary = "knip" if shutil.which("knip") else "npx"
        cmd = [binary, "knip", "--reporter=json", "--no-progress"]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        # Knip v5 schema: {"files": [...], "exports": [...], "dependencies": [...], ...}
        # Each entry is {"filePath": "...", "symbol": "...", "type": "..."}.
        for issue_type, items in data.items():
            if not isinstance(items, list):
                continue
            category, severity = _TYPE_MAP.get(issue_type, (Category.DEAD_CODE, Severity.LOW))
            for item in items:
                findings.append(
                    Finding(
                        tool=self.name,
                        rule=issue_type,
                        severity=severity,
                        category=category,
                        message=f"Unused {issue_type.rstrip('s')}: {item.get('symbol') or item.get('filePath')}",
                        file=item.get("filePath"),
                        line=item.get("line", 0),
                        column=item.get("col", 0),
                        fixable=False,
                        raw=item,
                    )
                )
        return findings
