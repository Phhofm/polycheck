"""pip-audit — scan Python dependencies for known CVEs.

pip-audit's ``--format json`` output is a list of dependencies with
their vulnerabilities. We flatten to one Finding per CVE, with the
package name in the file field and a synthetic line of 0. This way
the dedupe / grouping logic in reporters treats them like any other
finding.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool


class PipAuditTool(Tool):
    name = "pip-audit"
    category = Category.CVE
    languages = ["python"]
    installer = "pipx:pip-audit"

    def is_applicable(self, repo: Path) -> bool:
        # pip-audit is applicable to any Python project that has a
        # lockable dependency manifest.
        return any(
            (repo / name).exists()
            for name in ("pyproject.toml", "requirements.txt", "Pipfile", "poetry.lock", "uv.lock")
        )

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("pip-audit") is None:
            return []

        # Prefer the project's own pyproject.toml/requirements.txt.
        if (repo / "requirements.txt").exists():
            cmd = ["pip-audit", "-r", "requirements.txt", "--format", "json", "--no-deps"]
        else:
            # Fall back to scanning the requirements we can extract from pyproject.toml.
            # pip-audit doesn't read pyproject.toml directly, so we generate a
            # minimal requirements file on the fly.
            reqs = self._extract_requirements(repo)
            if not reqs:
                return []
            tmp = repo / ".polycheck-pip-audit-reqs.txt"
            tmp.write_text("\n".join(reqs), encoding="utf-8")
            cmd = ["pip-audit", "-r", str(tmp.name), "--format", "json", "--no-deps"]

        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        # pip-audit exits 1 when vulnerabilities are found; 0 when clean.
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for dep in data.get("dependencies", []):
            seen_ids: set[str] = set()  # dedup aliases (pip-audit reports the same vuln twice sometimes)
            for vuln in dep.get("vulns", []):
                fix_versions = ",".join(vuln.get("fix_versions", []))
                rule_id = vuln.get("id", "CVE-UNKNOWN")
                if rule_id in seen_ids:
                    continue
                seen_ids.add(rule_id)
                findings.append(
                    Finding(
                    tool=self.name,
                    rule=rule_id,
                    severity=Severity.CRITICAL,
                        category=self.category,
                        message=(
                            f"{dep.get('name','?')} {dep.get('version','?')}: "
                            f"{vuln.get('description','')[:200]}"
                            + (f" (fix: {fix_versions})" if fix_versions else "")
                        ),
                        file=dep.get("name"),
                        line=0,
                        column=0,
                        fixable=bool(fix_versions),
                        fix_command=None,
                        doc_url=None,
                        raw={"dep": dep, "vuln": vuln},
                    )
                )
        return findings

    @staticmethod
    def _extract_requirements(repo: Path) -> list[str]:
        """Read ``dependencies`` and ``optional-dependencies`` from
        ``pyproject.toml`` and return a list of bare package specs.
        Returns ``[]`` if pyproject is missing or malformed.
        """
        pyproject = repo / "pyproject.toml"
        if not pyproject.exists():
            return []
        try:
            try:
                import tomllib  # py311+
            except ImportError:
                import tomli as tomllib
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

        project = data.get("project", {})
        reqs: list[str] = []
        for spec in project.get("dependencies", []):
            reqs.append(str(spec))
        for extras in project.get("optional-dependencies", {}).values():
            for spec in extras:
                reqs.append(str(spec))
        return reqs
