"""Test-coverage measurement — the one quality signal no static tool sees.

Static analyzers read code; only the test suite can say which code the
tests actually exercise. This adapter runs the project's own suite
under ``coverage``, then reports per-file coverage gaps: untested
modules (MEDIUM) and partially covered ones (LOW), plus a
``coverage_percent`` scan metric for the report's metric table.

Deliberately deep-only: it executes the user's test suite, which is
far too slow for the default scan and pointless in the fast pr gate
(``DEEP_ONLY_TOOLS`` in profiles). It is also deliberately tolerant of
failing tests — test failures are pytest's business; this adapter
reports coverage only. Requires ``coverage`` and ``pytest`` in the
environment polycheck runs from (the user's, not polycheck's venv).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool


class CoverageTool(Tool):
    name = "coverage"
    category = Category.TEST_COVERAGE
    languages = ["python"]

    def is_applicable(self, repo: Path) -> bool:
        """Applicable when the repo has tests to measure."""
        return (
            (repo / "tests").is_dir()
            or (repo / "test").is_dir()
            or "tool.pytest" in (repo / "pyproject.toml").read_text(
                encoding="utf-8", errors="ignore"
            )
        )

    def is_installed(self) -> bool:
        """The suite runs in polycheck's invocation environment: both
        ``coverage`` and ``pytest`` must be importable there."""
        return shutil.which("coverage") is not None and shutil.which(
            "pytest"
        ) is not None

    def install_hint(self) -> str:
        return (
            "pip install coverage pytest (in the environment you run "
            "polycheck from - this adapter executes YOUR test suite)"
        )

    def can_auto_install(self) -> bool:
        # Installing test tooling into the user's environment from a
        # static-analysis run is a consent-class decision, not a
        # package fetch - the guided flow asks instead.
        return False

    def run(self, repo: Path) -> list[Finding]:
        findings: list[Finding] = []
        tmp = Path(tempfile.mkdtemp(prefix="polycheck-cov-"))
        data_file = repo / ".coverage"
        # config may be None when the adapter is instantiated directly
        # (verify-tools, smoke tests): fall back to the runner default.
        timeout = getattr(self.config, "timeout", None) or 600
        try:
            suite = subprocess.run(
                ["coverage", "run", "--source", str(repo), "-m", "pytest", "-q"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if suite.returncode not in (0, 1, 5):
                raise RuntimeError(
                    f"coverage run -m pytest exited {suite.returncode}: "
                    f"{(suite.stderr or suite.stdout).strip()[:200]}"
                )

            report = tmp / "coverage.json"
            subprocess.run(
                ["coverage", "json", "-o", str(report)],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            data = json.loads(report.read_text(encoding="utf-8"))

            totals = data.get("totals", {})
            self.scan_metrics = {
                "coverage_percent": round(
                    float(totals.get("percent_covered", 0.0)), 1
                ),
                "files_uncovered": sum(
                    1
                    for f in data.get("files", {}).values()
                    if f.get("summary", {}).get("missing_lines", 0) > 0
                ),
            }

            for rel, entry in sorted(data.get("files", {}).items()):
                summary = entry.get("summary", {})
                missing = summary.get("missing_lines", 0)
                if missing <= 0:
                    continue
                statements = summary.get("num_statements", 0)
                first_missing = (entry.get("missing_lines") or [1])[0]
                if summary.get("covered_lines", 0) == 0:
                    severity = Severity.MEDIUM
                    message = (
                        f"untested module: {missing}/{statements} statements "
                        "have no test coverage"
                    )
                else:
                    severity = Severity.LOW
                    message = (
                        f"{missing}/{statements} statements uncovered "
                        f"({summary.get('percent_covered', 0):.0f}% covered)"
                    )
                findings.append(
                    Finding(
                        tool=self.name,
                        rule="COV-UNCOVERED",
                        severity=severity,
                        category=self.category,
                        file=rel,
                        line=max(int(first_missing), 1),
                        message=message,
                    )
                )
            return findings
        finally:
            data_file.unlink(missing_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)
