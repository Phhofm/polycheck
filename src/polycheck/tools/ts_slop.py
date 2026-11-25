"""ts-slop — polycheck-authored ast-grep slop rules for TypeScript.

The first polycheck-owned structural rule set, built because scb-check
0.2.0 ships 197 rules, all `language: python` (verified; its
`SCB_CHECK_EXTRA_SLOP_RULES` env mechanism does not reach the analysis
pipeline). The SlopCodeBench degradation forms are agent behavior, not
Python behavior — so the *intent* of the paper's slop patterns ports to
TypeScript even though every ast-grep pattern is written fresh.

Rules live in ``resources/ts_slop_rules.yaml`` (package data) and
target the TypeScript habits LLM assistants leave behind:

- index `for` loops over arrays instead of `for-of`/`map()`
- escape hatches: `as any`, `as unknown as T`, `@ts-ignore`,
  empty-object casts — the visible markers of type-system erosion
- swallowed errors (empty catch blocks)
- mechanical verbosity (`!!x`, if/else returning booleans)

Every rule was verified against a seeded TypeScript defect and against
real ast-grep output (0.51.3); the seeded verifier expects two findings
from the synthetic repo. ast-grep's `--json` lines are 0-indexed; the
Finding schema is 1-indexed.

Vue SFCs (`.vue`) are NOT covered yet: ast-grep 0.51 silently skips
them (no builtin language; verified — a spike file produced zero
matches with and without `--language vue`). Coverage needs ast-grep's
external-language config (tree-sitter-vue); `.ts` files — NestJS
backends, Ionic services — are the bulk of a TS codebase and are
covered fully.

ast-grep itself ships via ``npm:@ast-grep/cli``; the npx fallback uses
the package name (``npx -p @ast-grep/cli ast-grep``) because
``npx ast-grep`` cannot resolve the bin from the package name.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool, iter_source_files, npx_command

_RULES_FILE = "ts_slop_rules.yaml"

_SEVERITY_MAP = {
    "error": Severity.MEDIUM,
    "warning": Severity.LOW,
    "hint": Severity.INFO,
    "info": Severity.INFO,
}


def _rules_path() -> Path:
    """The shipped rule file as a real filesystem path."""
    return Path(str(resources.files("polycheck.tools") / "resources" / _RULES_FILE))


class TsSlopTool(Tool):
    name = "ts-slop"
    category = Category.LINT
    languages = ["typescript"]
    installer = "npm:@ast-grep/cli"

    def is_applicable(self, repo: Path) -> bool:
        return any(
            file.suffix in (".ts", ".tsx")
            for file in iter_source_files(repo, ("*.ts", "*.tsx"))
        )

    def is_installed(self) -> bool:
        # Usable without a global install: npx can fetch and run the
        # CLI package (the runner skips tools that report not-installed).
        return (
            shutil.which(self.binary) is not None
            or shutil.which("npx") is not None
        )

    def _command(self, repo: Path) -> list[str]:
        if shutil.which("ast-grep"):
            return ["ast-grep", "scan", "--rule", str(_rules_path()), "--json"]
        return [
            *npx_command(), "-p", "@ast-grep/cli", "ast-grep",
            "scan", "--rule", str(_rules_path()), "--json",
        ]

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("ast-grep") is None and shutil.which("npx") is None:
            return []
        cmd = [*self._command(repo), *self.extra_args(), "."]
        # The scan path is "." (relative, with cwd=repo): an absolute
        # path makes ast-grep report ABSOLUTE file paths, which broke
        # the track buckets (tracked files bucketed untracked), the
        # pr change-scope matching, and fingerprint portability
        # (live test #6).
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=300
        )
        # ast-grep scan exits 1 when findings exist (like grep); only
        # worse exits are errors.
        if out.returncode >= 2:
            detail = (out.stderr or out.stdout).strip()[:200]
            raise RuntimeError(
                f"ts-slop (ast-grep) exited {out.returncode}: {detail}"
            )
        if not out.stdout.strip():
            return []
        try:
            data = json.loads(out.stdout)
        except json.JSONDecodeError:
            detail = out.stdout.strip()[:200] or out.stderr.strip()[:200]
            raise RuntimeError(
                f"ts-slop (ast-grep) produced no JSON report: {detail}"
            ) from None
        if not isinstance(data, list):
            return []
        return [self._parse_hit(hit) for hit in data if isinstance(hit, dict)]

    def _parse_hit(self, hit: dict) -> Finding:
        rule_id = hit.get("ruleId", "ts-slop-violation")
        severity = _SEVERITY_MAP.get(
            hit.get("severity", "warning"), Severity.LOW
        )
        start = hit.get("range", {}).get("start", {}) or {}
        # ast-grep --json is 0-indexed; the Finding schema is 1-indexed.
        line = (start.get("line") or 0) + 1
        column = (start.get("column") or 0) + 1
        return Finding(
            tool=self.name,
            rule=rule_id,
            severity=severity,
            category=Category.LINT,
            message=hit.get("message", ""),
            file=hit.get("file"),
            line=line,
            column=column,
            fixable=False,
            doc_url="https://ast-grep.github.io/guide/rule-config.html",
            raw=hit,
        )
