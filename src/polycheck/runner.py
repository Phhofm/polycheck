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
import json
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .detect import detect
from .finding import Category, Finding, Severity
from .profiles import ProfileSpec, is_skipped
from .registry import ToolRegistry, default_registry
from .tools.base import Tool, annotate_track_status


@dataclass
class ToolResult:
    """Outcome of running one tool. Used for reporting in the markdown
    summary, so the LLM (or user) can see which tools failed vs. which
    tools reported zero findings."""

    tool: str
    status: str               # "ok" | "no-findings" | "not-applicable" | "error" | "timeout"
    findings: list[Finding] = field(default_factory=list)
    duration_sec: float = 0.0
    error: str | None = None
    message: str = ""         # e.g. why a tool was not applicable
    metrics: dict = field(default_factory=dict)  # scan-level metrics (e.g. SlopCodeBench composites)


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
        profile: ProfileSpec | None = None,
    ) -> tuple[list[Finding], list[ToolResult]]:
        """Run all applicable tools and return ``(findings, results)``.

        If ``tools`` is given, restrict to those tool names (after the
        enable/disable filter). Otherwise all applicable tools run.

        If ``profile`` is given, it presets tool selection (``pr`` skips
        heavy and structural adapters; ``deep`` keeps everything).

        If ``parallel`` is True, tools are run in a thread pool (one per
        tool). Tool subprocesses are independent; running in parallel is
        safe and roughly halves total wall time on a 4+ core machine.
        """
        applicable, not_applicable = self._eligibility_split(profile)
        if tools is not None:
            wanted = set(tools)
            applicable = [c for c in applicable if c.name in wanted]
            not_applicable = [row for row in not_applicable if row[0].name in wanted]

        # Not-applicable rows come first so the report answers "why did
        # tool X not run?" without a doctor cross-check (external live
        # test, 0.3.7).
        results: list[ToolResult] = [
            ToolResult(
                tool=cls.name,
                status="not-applicable",
                message=reason,
            )
            for cls, reason in not_applicable
        ]
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
        annotate_track_status(self.repo, findings)
        return findings, results

    def _applicable_tools(self, profile: ProfileSpec | None = None) -> list[type[Tool]]:
        """Filter registry → language-applicable → user enable/disable → profile → installed."""
        return self._eligibility_split(profile)[0]

    def _eligibility_split(
        self, profile: ProfileSpec | None = None
    ) -> tuple[list[type[Tool]], list[tuple[type[Tool], str]]]:
        """Split installed, enabled candidates into applicable tools and
        installed-but-not-applicable tools (with the adapter's reason,
        when it can state one)."""
        langs = detect(self.repo)
        lang_slugs = {lang.slug for lang in langs}

        # Build candidate set: anything universal, or that applies to a
        # detected language. A tool that declares a specific language
        # is NOT eligible when no language is detected (e.g. a fresh
        # empty repo where no analyzer is relevant).
        candidates: list[type[Tool]] = []
        for cls in self.registry.all():
            if cls.universal or (lang_slugs and any(slug in lang_slugs for slug in cls.languages)):
                candidates.append(cls)

        # Apply enable/disable filters.
        candidates = self._apply_filters(candidates)

        applicable: list[type[Tool]] = []
        not_applicable: list[tuple[type[Tool], str]] = []
        for cls in candidates:
            if is_skipped(cls, profile):
                continue
            inst = cls(config=self.config)
            if not inst.is_installed():
                continue
            if inst.is_applicable(self.repo):
                applicable.append(cls)
            else:
                reason = inst.not_applicable_reason(self.repo) or ""
                not_applicable.append((cls, reason))
        return applicable, not_applicable

    def _apply_filters(self, candidates: list[type[Tool]]) -> list[type[Tool]]:
        """Apply enable/disable config filters to candidate tools."""
        if self.config.enable:
            wanted = set(self.config.enable)
            candidates = [c for c in candidates if c.name in wanted]
        if self.config.disable:
            excluded = set(self.config.disable)
            candidates = [c for c in candidates if c.name not in excluded]
        return candidates

    def _run_one(self, tool_cls: type[Tool]) -> ToolResult:
        name = tool_cls.name
        inst = tool_cls(config=self.config)
        start = time.monotonic()
        try:
            findings = inst.run(self.repo)
            duration = time.monotonic() - start
            status = "ok" if findings else "no-findings"
            metrics = getattr(inst, "scan_metrics", None)
            return ToolResult(tool=name, status=status, findings=findings,
                              duration_sec=duration,
                              metrics=dict(metrics) if isinstance(metrics, dict) else {})
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


def apply_suppressions(
    findings: list[Finding], patterns: list[str]
) -> list[Finding]:
    """Drop findings matching a durable suppress entry.

    Entries are ``rule`` (suppress everywhere) or ``rule@file``
    (suppress in one file, repo-relative). This is how triage verdicts
    persist: an LLM (or user) marks a finding FALSE POSITIVE once and
    the entry keeps it out of every later run.
    """
    if not patterns:
        return findings
    rule_only: set[str] = set()
    rule_file: set[tuple[str, str]] = set()
    for pattern in patterns:
        entry = pattern.strip()
        if not entry:
            continue
        if "@" in entry:
            rule, file = entry.split("@", 1)
            rule_file.add((rule.strip(), file.strip()))
        else:
            rule_only.add(entry)
    out: list[Finding] = []
    for f in findings:
        if f.rule in rule_only:
            continue
        if f.file and (f.rule, f.file) in rule_file:
            continue
        out.append(f)
    return out


def filter_by_baseline(
    findings: list[Finding], baseline: set[str] | None
) -> list[Finding]:
    """Keep only findings whose fingerprint is not in the baseline.

    ``None`` (no baseline in play) is an identity function. Diff mode:
    a scan reports what is *new* since the baseline was taken.
    """
    if baseline is None:
        return findings
    return [f for f in findings if f.fingerprint() not in baseline]


# --- baseline ---------------------------------------------------------------

BASELINE_FILENAME = "polycheck-baseline.json"


def save_baseline(report_dir: Path, findings: list[Finding]) -> Path:
    """Write the fingerprint baseline for diff mode to ``report_dir``.

    The baseline holds only fingerprints — no messages or paths — so it
    stays small and stable across message wording changes.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / BASELINE_FILENAME
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fingerprints": sorted({f.fingerprint() for f in findings}),
    }
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return path


def load_baseline(report_dir: Path) -> set[str] | None:
    """Load the baseline fingerprint set, or ``None`` when absent.

    A malformed baseline is treated as absent (diff mode then reports
    everything) — it must never crash a scan or silently hide findings.
    """
    path = report_dir / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fps = data.get("fingerprints", [])
        if not isinstance(fps, list):
            return None
        return {str(x) for x in fps}
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


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
