"""Runner — orchestrates the execution of every applicable tool.

Given a repo, a config, and a registry, the runner:

  1. Detects languages in the repo.
  2. Filters tools by language + applicability + config (enable/disable).
  3. Runs each tool in a subprocess with a per-tool timeout.
  4. Collects the parsed ``Finding`` objects.
  5. Optionally deduplicates across tools.
  6. Returns the final list.

The runner is the only module that touches subprocess. Tool adapters
are pure: they take a Path, return list[Finding].
"""
from __future__ import annotations

import concurrent.futures
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .detect import detect
from .finding import Category, Finding, Severity
from .registry import ToolRegistry, default_registry


@dataclass
class ToolResult:
    """Outcome of running one tool. Used for reporting in the markdown
    summary, so the LLM (or user) can see which tools failed vs. which
    tools reported zero findings."""

    tool: str
    status: str               # "ok" | "no-findings" | "skipped" | "error" | "timeout"
    findings: list[Finding] = field(default_factory=list)
    duration_sec: float = 0.0
    error: str | None = None


class Runner:
    """Run a set of tools against a repo and collect findings."""

    def __init__(
        self,
        repo: Path,
        config: Config,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.repo = Path(repo).resolve()
        self.config = config
        self.registry = registry or default_registry

    def run(
        self,
        parallel: bool = False,
        tools: Iterable[str] | None = None,
    ) -> tuple[list[Finding], list[ToolResult]]:
        """Run all applicable tools and return ``(findings, results)``.

        If ``tools`` is given, restrict to those tool names (after the
        enable/disable filter). Otherwise all applicable tools run.

        If ``parallel`` is True, tools are run in a thread pool (one per
        tool). Tool subprocesses are independent; running in parallel is
        safe and roughly halves total wall time on a 4+ core machine.
        """
        applicable = self._applicable_tools()
        if tools is not None:
            wanted = set(tools)
            applicable = [c for c in applicable if c.name in wanted]

        results: list[ToolResult] = []
        if parallel:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(self._run_one, c): c for c in applicable}
                for fut in concurrent.futures.as_completed(futures):
                    results.append(fut.result())
        else:
            for cls in applicable:
                results.append(self._run_one(cls))

        # Stable order for the report: by tool name.
        results.sort(key=lambda r: r.tool)
        findings = [f for r in results for f in r.findings]
        return findings, results

    def _applicable_tools(self) -> list[type]:
        """Filter registry → language-applicable → user enable/disable → installed."""
        langs = detect(self.repo)
        lang_slugs = {lang.slug for lang in langs}

        # Build candidate set: anything universal, or that applies to a
        # detected language. A tool that declares a specific language
        # is NOT eligible when no language is detected (e.g. a fresh
        # empty repo where no analyzer is relevant).
        candidates: list[type] = []
        for cls in self.registry.all():
            if cls.universal:
                candidates.append(cls)
            elif lang_slugs and any(slug in lang_slugs for slug in cls.languages):
                candidates.append(cls)

        # Apply enable/disable.
        if self.config.enable:
            wanted = set(self.config.enable)
            candidates = [c for c in candidates if c.name in wanted]
        if self.config.disable:
            excluded = set(self.config.disable)
            candidates = [c for c in candidates if c.name not in excluded]

        # Filter to installed + applicable.
        out: list[type] = []
        for cls in candidates:
            inst = cls()
            if not inst.is_installed():
                continue
            if not inst.is_applicable(self.repo):
                continue
            out.append(cls)
        return out

    def _run_one(self, tool_cls: type) -> ToolResult:
        name = tool_cls.name
        inst = tool_cls()
        start = time.monotonic()
        try:
            findings = inst.run(self.repo)
            duration = time.monotonic() - start
            status = "ok" if findings else "no-findings"
            return ToolResult(tool=name, status=status, findings=findings,
                              duration_sec=duration)
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return ToolResult(tool=name, status="timeout", duration_sec=duration,
                              error=f"exceeded {self.config.timeout}s")
        except Exception as e:  # noqa: BLE001 — we want to capture *any* tool failure
            duration = time.monotonic() - start
            return ToolResult(tool=name, status="error", duration_sec=duration,
                              error=f"{type(e).__name__}: {e}")


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop findings with the same fingerprint.

    In practice this rarely fires (different tools use different file
    paths / line numbers), but the hook is here for tools that wrap the
    same underlying analyzer under different names (e.g. an MCP server
    that proxies another tool).
    """
    seen: set[str] = set()
    out: list[Finding] = []
    for f in findings:
        if f.fingerprint() in seen:
            continue
        seen.add(f.fingerprint())
        out.append(f)
    return out


def filter_by_severity(
    findings: list[Finding], threshold: str
) -> list[Finding]:
    """Drop findings below the given severity.

    ``threshold`` is one of: INFO, LOW, MEDIUM, HIGH, CRITICAL.
    """
    threshold = threshold.upper()
    if threshold not in Severity.__members__:
        return findings
    cutoff = Severity[threshold]
    return [f for f in findings if f.severity >= cutoff]


def group_by_category(
    findings: list[Finding],
) -> dict[Category, list[Finding]]:
    """Bucket findings by category. Useful for the markdown report."""
    out: dict[Category, list[Finding]] = {c: [] for c in Category}
    for f in findings:
        out.setdefault(f.category, []).append(f)
    return out
