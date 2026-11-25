"""tach — Python module-boundary and circular-import checks.

tach (https://github.com/tach-org/tach) enforces the architecture the
user declared in ``tach.toml``: undeclared cross-module dependencies,
and — with ``forbid_circular_dependencies = true`` — dependency cycles.
It is the first structural adapter (0.3.4, deep-profile family).

Output: ``tach check --output json``. tach exits 1 both for violations
and for config errors; only the JSON parse distinguishes them, so a
non-JSON stdout raises instead of silently reading as "no findings".

The adapter runs only when the repo carries a tach.toml (or a
``[tool.tach]`` section in pyproject.toml) — architecture contracts are
user-defined; without one there is nothing to check.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool


class TachTool(Tool):
    name = "tach"
    category = Category.ARCHITECTURE
    languages = ["python"]
    structural = True
    installer = "pipx:tach"

    def is_applicable(self, repo: Path) -> bool:
        if (repo / "tach.toml").exists():
            return True
        pyproject = repo / "pyproject.toml"
        return pyproject.exists() and "[tool.tach]" in pyproject.read_text(
            encoding="utf-8", errors="replace"
        )

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("tach") is None:
            return []
        cmd = ["tach", "check", "--output", "json", *self.extra_args()]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        if out.returncode not in (0, 1):
            detail = (out.stderr or out.stdout).strip()[:200]
            raise RuntimeError(f"tach exited {out.returncode}: {detail}")
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            # Exit 1 with non-JSON stdout is a config/startup error —
            # surfacing it beats silently reporting a clean repo.
            detail = out.stdout.strip()[:200]
            raise RuntimeError(f"tach produced no JSON report: {detail}") from None
        return self._parse(data)

    def _parse(self, data) -> list[Finding]:
        findings: list[Finding] = []
        if isinstance(data, dict) and data.get("error") == "Circular dependency":
            cycle = " -> ".join(str(d) for d in data.get("dependencies", []))
            findings.append(Finding(
                tool=self.name,
                rule="circular-dependency",
                severity=Severity.MEDIUM,
                category=Category.ARCHITECTURE,
                message=f"Circular dependency: {cycle}",
                file=None,
                fixable=False,
                doc_url="https://docs.gauge.sh/usage/configuration",
                raw=data,
            ))
            return findings
        if not isinstance(data, list):
            return findings
        for item in data:
            located = item.get("Located") if isinstance(item, dict) else None
            if located:
                findings.append(self._parse_located(located))
        return findings

    def _parse_located(self, located: dict) -> Finding:
        severity = {
            "Error": Severity.MEDIUM,
            "Warning": Severity.LOW,
        }.get(located.get("severity", "Error"), Severity.MEDIUM)
        details = located.get("details", {})
        code = details.get("Code", {}) if isinstance(details, dict) else {}
        rule, message = self._describe(code)
        return Finding(
            tool=self.name,
            rule=rule,
            severity=severity,
            category=Category.ARCHITECTURE,
            message=message,
            file=located.get("file_path"),
            line=located.get("line_number"),
            fixable=False,
            doc_url="https://docs.gauge.sh/usage/configuration",
            raw=located,
        )

    @staticmethod
    def _describe(code: dict) -> tuple[str, str]:
        """Turn the Code variant payload into (rule, message)."""
        for name, payload in code.items():
            if name == "UndeclaredDependency" and isinstance(payload, dict):
                usage = payload.get("usage_module", "?")
                definition = payload.get("definition_module", "?")
                dep = payload.get("dependency", "?")
                return name, (
                    f"Module '{usage}' uses '{dep}' from '{definition}' "
                    "without declaring that dependency"
                )
            if name == "UnusedDependency" and isinstance(payload, dict):
                return name, f"Unused declared dependency: {payload}"
        # Unknown variant: keep the raw payload visible instead of dropping it.
        return "tach-violation", json.dumps(code, sort_keys=True)[:200]
