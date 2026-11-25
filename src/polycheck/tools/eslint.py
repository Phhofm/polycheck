"""eslint — JS/TS linter (with JSON output via --format=json).

We treat ESLint findings as LOW severity by default (style). The
LLM-triage step usually wants to focus on bugs and security, so we
keep ESLint informational. Users can bump the severity in
``.polycheck.yml`` if they prefer.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool, iter_source_files


class EslintTool(Tool):
    name = "eslint"
    category = Category.LINT
    languages = ["javascript", "typescript"]
    installer = "npm:eslint"

    def is_applicable(self, repo: Path) -> bool:
        # Any of: eslint.config.* (flat config), .eslintrc.*, or the
        # eslint dep in package.json.
        flat = list(repo.glob("eslint.config.*"))
        old = list(repo.glob(".eslintrc*"))
        pkg = repo / "package.json"
        has_dep = False
        if pkg.exists():
            try:
                import json as _j
                data = _j.loads(pkg.read_text(encoding="utf-8"))
                for k in ("devDependencies", "dependencies"):
                    if "eslint" in data.get(k, {}):
                        has_dep = True
            except (OSError, ValueError):
                pass
        return bool(flat or old or has_dep)

    def not_applicable_reason(self, repo: Path) -> str | None:
        return ("no eslint config (eslint.config.*, .eslintrc*, or "
                "eslint in package.json)")

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("eslint") is None and shutil.which("npx") is None:
            return []
        # Explicit project file list: eslint's default ignores cover
        # node_modules but not .venv/dist, so linting "." reports
        # vendored code.
        files = [
            str(p)
            for p in iter_source_files(
                repo, ("*.js", "*.jsx", "*.mjs", "*.cjs", "*.ts", "*.tsx")
            )
        ]
        if not files:
            return []
        # Prefer the local binary if it exists; fall back to npx (which
        # needs the module name as its first argument).
        if shutil.which("eslint"):
            cmd = ["eslint", "--format=json", "--no-warn-ignored", *self.extra_args(), *files]
        else:
            cmd = ["npx", "eslint", "--format=json", "--no-warn-ignored", *self.extra_args(), *files]
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
        for file_result in data:
            for msg in file_result.get("messages", []):
                # Map ESLint severity (1=warn, 2=error) to ours.
                severity = {
                    1: Severity.LOW,
                    2: Severity.MEDIUM,
                }.get(msg.get("severity"), Severity.LOW)
                rule_id = msg.get("ruleId") or "unknown"
                findings.append(
                    Finding(
                        tool=self.name,
                        rule=rule_id,
                        severity=severity,
                        category=self.category,
                        message=msg.get("message", ""),
                        file=file_result.get("filePath"),
                        line=msg.get("line"),
                        column=msg.get("column"),
                        fixable=msg.get("fix") is not None,
                        fix_command="eslint --fix ." if any(
                            m.get("fix") for fr in data for m in fr.get("messages", [])
                        ) else None,
                        doc_url=f"https://eslint.org/docs/rules/{rule_id}" if rule_id != "unknown" else None,
                        raw=msg,
                    )
                )
        return findings
