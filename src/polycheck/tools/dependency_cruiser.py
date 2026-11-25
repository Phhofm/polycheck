"""dependency-cruiser — JS/TS module-boundary and circular-dependency checks.

dependency-cruiser (https://github.com/sverweij/dependency-cruiser)
validates the rules the user declared in a dependency-cruiser config:
circular dependencies (``no-circular``), path/layer rules, orphans, and
more. Second structural adapter (0.3.6, deep-profile family, the JS/TS
counterpart to tach).

Quirks pinned against real 18.x output (see tests):
  * the npm package installs a binary named ``depcruise``; ``npx
    depcruise`` resolves a placeholder package, so the npx fallback must
    pass the package name ``dependency-cruiser``;
  * violations do not change the exit code — the parser never trusts it;
  * the JSON reporter nests violations under ``summary.violations``
    (``output.violations`` is tolerated as an alias);
  * a non-JSON stdout raises instead of silently reading as "no
    findings".

The adapter runs only when the repo carries a dependency-cruiser config
— rules are user-defined; without one there is nothing to check.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool, npx_command

_CONFIG_NAMES = (
    ".dependency-cruiser.cjs",
    ".dependency-cruiser.js",
    ".dependency-cruiser.mjs",
    ".dependency-cruiser.ts",
    ".dependency-cruiser.cts",
    ".dependency-cruiser.mts",
    ".dependency-cruiser.json",
    ".dependency-cruiser.yaml",
    ".dependency-cruiser.yml",
)

_SEVERITY_MAP = {
    "error": Severity.MEDIUM,
    "warn": Severity.LOW,
    "info": Severity.INFO,
}


class DependencyCruiserTool(Tool):
    name = "dependency-cruiser"
    category = Category.ARCHITECTURE
    languages = ["javascript", "typescript"]
    structural = True
    installer = "npm:dependency-cruiser"

    @property
    def binary(self) -> str:
        # The npm package's bin is "depcruise", not the package name.
        return "depcruise"

    def is_installed(self) -> bool:
        # Usable without a global install: npx can fetch and run the
        # package (the runner skips tools that report not-installed).
        return (
            shutil.which(self.binary) is not None
            or shutil.which("npx") is not None
        )

    def is_applicable(self, repo: Path) -> bool:
        return any((repo / name).exists() for name in _CONFIG_NAMES)
    def not_applicable_reason(self, repo: Path) -> str | None:
        return "no dependency-cruiser config (.dependency-cruiser.*)"

    def _command(self) -> list[str]:
        if shutil.which(self.binary):
            return [self.binary]
        return [*npx_command(), "--yes", "dependency-cruiser"]

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which(self.binary) is None and shutil.which("npx") is None:
            return []
        cmd = [
            *self._command(),
            "--output-type", "json",
            *self.extra_args(),
            ".",
        ]
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=600
        )
        # Violations do not change the exit code in 18.x — parse the
        # output regardless; only a non-JSON stdout is an error.
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            detail = out.stdout.strip()[:200] or out.stderr.strip()[:200]
            raise RuntimeError(
                f"dependency-cruiser produced no JSON report: {detail}"
            ) from None
        return self._parse(data)

    def _parse(self, data: dict) -> list[Finding]:
        if not isinstance(data, dict):
            return []
        raw_output = data.get("output")
        # 18.x nests violations under summary; some reporters/documenta-
        # tion use an output.violations envelope — read both.
        output: dict = raw_output if isinstance(raw_output, dict) else data
        summary = output.get("summary")
        violations = (
            summary.get("violations") if isinstance(summary, dict) else None
        ) or output.get("violations")
        if not isinstance(violations, list):
            return []
        findings: list[Finding] = []
        for v in violations:
            if not isinstance(v, dict):
                continue
            findings.append(self._parse_violation(v))
        return findings

    def _parse_violation(self, v: dict) -> Finding:
        raw_rule = v.get("rule")
        rule: dict = raw_rule if isinstance(raw_rule, dict) else {}
        name = rule.get("name") or v.get("type", "violation")
        severity = _SEVERITY_MAP.get(rule.get("severity") or "", Severity.MEDIUM)
        message = (
            f"{name}: {v.get('from', '?')} -> {v.get('to', '?')}"
            f" ({v.get('type', 'violation')})"
        )
        return Finding(
            tool=self.name,
            rule=name,
            severity=severity,
            category=Category.ARCHITECTURE,
            message=message,
            file=v.get("from"),
            line=None,
            fixable=False,
            doc_url="https://github.com/sverweij/dependency-cruiser/blob/main/doc/rules-reference.md",
            raw=v,
        )
