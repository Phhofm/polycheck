"""Markdown reporter — human-readable summary + per-category tables.

This is the format the LLM-triage prompt is designed to read. The
``findings:markdown`` MCP resource will return the same content, so
agents can ``read_file()`` the report rather than re-walk the JSON.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..finding import Category, Severity
from ..runner import ToolResult

# Severity → emoji + label, used in the summary table.
_SEV_BADGE = {
    Severity.CRITICAL: "CRIT",
    Severity.HIGH: "HIGH",
    Severity.MEDIUM: "MED ",
    Severity.LOW: "LOW ",
    Severity.INFO: "INFO",
}


def render(
    repo: Path,
    findings: list,
    results: list[ToolResult],
    *,
    report_dir: Path,
    coverage: dict | None = None,
) -> list[Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / "polycheck-report.md"

    lines: list[str] = []
    lines.extend(_header(repo, findings, results))
    if coverage is not None and not coverage.get("complete", True):
        lines.extend(_incomplete_banner(coverage))
    lines.extend(_severity_section(findings))
    lines.extend(_category_section(findings))
    lines.extend(_track_section(findings))
    if coverage is not None:
        lines.extend(_coverage_section(coverage))
    lines.extend(_tool_execution_section(results))
    lines.extend(_metrics_section(results))
    lines.extend(_findings_sections(findings))

    out.write_text("\n".join(lines), encoding="utf-8")
    return [out]


def _incomplete_banner(coverage: dict) -> list[str]:
    """The headline a reader cannot miss: this profile did not run in
    full. 0.3.14 — a deep report without an installed heavy tool used
    to present itself as complete."""
    profile = str(coverage.get("profile", "default")).upper()
    ran = coverage.get("ran", 0)
    candidates = coverage.get("candidates", 0)
    rows = coverage.get("tools", [])
    missing = [t["name"] for t in rows if t.get("status") == "missing"]
    failed = [t["name"] for t in rows if t.get("status") == "failed"]
    not_applicable = sum(1 for t in rows if t.get("status") == "not-applicable")
    parts = [
        f"⚠ **{profile} SCAN INCOMPLETE** — {ran} of {candidates} "
        "candidate tools ran"
    ]
    if not_applicable:
        parts.append(f"; {not_applicable} not applicable to this repo")
    parts.append(". ")
    if missing:
        parts.append(f"Missing (not installed): {', '.join(missing)}.")
    if failed:
        parts.append(f"Failed: {', '.join(failed)}.")
    parts.append("This report must NOT be treated as a complete scan of its profile.")
    return [f"> {' '.join(parts)}", ""]


def _coverage_section(coverage: dict) -> list[str]:
    """The per-tool truth about what ran and what did not. Ran tools
    are already listed under Tool execution; this section lists the
    rest with the reason and, for missing tools, the install command
    and who should run it."""
    verdict = ("complete" if coverage.get("complete", False)
               else "**INCOMPLETE**")
    lines = [
        "## Coverage",
        "",
        f"Profile `{coverage.get('profile', 'default')}`: {verdict} — "
        f"{coverage.get('ran', 0)} of {coverage.get('candidates', 0)} "
        "candidate tools produced a result.",
        "",
        "| Tool | Status | Note |",
        "|------|--------|------|",
    ]
    for row in coverage.get("tools", []):
        if row.get("status") == "ran":
            continue
        note = str(row.get("reason", "")).replace("|", "\\|")
        if row.get("status") == "missing" and row.get("install_hint"):
            executor = row.get("executor", "human")
            hint = str(row["install_hint"]).replace("|", "\\|")
            note = f"{note} — install ({executor}): `{hint}`"
        lines.append(f"| `{row['name']}` | {row.get('status', '?')} | {note} |")
    lines.append("")
    return lines


def _header(repo: Path, findings: list, results: list) -> list[str]:
    """Generate the report header."""
    return [
        f"# polycheck report — `{repo.name}`",
        "",
        f"**Total findings:** {len(findings)} | "
        f"**Tools run:** {len(results)} | "
        f"**Tools failed:** "
        f"{sum(1 for r in results if r.status in ('error', 'timeout'))}",
        "",
    ]


def _severity_section(findings: list) -> list[str]:
    """Generate the severity breakdown table."""
    by_sev = Counter(f.severity for f in findings)
    lines = ["## By severity", "", "| Severity | Count |", "|----------|-------|"]
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO):
        n = by_sev.get(sev, 0)
        if n:
            lines.append(f"| {_SEV_BADGE[sev]} | {n} |")
    lines.append("")
    return lines


def _track_section(findings: list) -> list[str]:
    """Git track buckets. The headline is the tracked sum: gitignored
    files cannot reach the repo via push, so they must not read as
    repo-wide alarms (bigger-repo live test: 1717 raw, ~1690 ignored)."""
    tracks = [f.track for f in findings]
    if not any(t for t in tracks):
        return []
    by_track: Counter = Counter(t for t in tracks if t)
    tracked_sev = Counter(f.severity for f in findings if f.track == "tracked")
    tracked_above_medium = sum(
        n for sev, n in tracked_sev.items() if sev >= Severity.MEDIUM
    )
    lines = [
        "## By git track status",
        "",
        "| Bucket | Count |",
        "|--------|-------|",
    ]
    for label in ("tracked", "untracked", "ignored"):
        n = by_track.get(label, 0)
        if n:
            lines.append(f"| {label} | {n} |")
    lines.extend([
        "",
        f"Severity ≥ MEDIUM in **tracked** files: {tracked_above_medium} "
        "— that is what a push carries. Gitignored files cannot reach the repo.",
    ])
    lines.append("")
    return lines


def _category_section(findings: list) -> list[str]:
    """Generate the category breakdown table."""
    by_cat = Counter(f.category for f in findings)
    lines = ["## By category", "", "| Category | Count |", "|----------|-------|"]
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        if n:
            lines.append(f"| {cat.value} | {n} |")
    lines.append("")
    return lines


def _tool_execution_section(results: list) -> list[str]:
    """Generate the tool execution table."""
    lines = [
        "## Tool execution",
        "",
        "| Tool | Status | Duration (s) | Findings |",
        "|------|--------|--------------|----------|",
    ]
    for r in results:
        lines.append(
            f"| `{r.tool}` | {r.status} | {r.duration_sec:.1f} | {len(r.findings)} |"
        )
    if any(r.error for r in results):
        lines.extend(["", "### Tool errors", ""])
        for r in results:
            if r.error:
                lines.append(f"- **{r.tool}**: `{r.error}`")
    lines.append("")
    return lines


def _metrics_section(results: list) -> list[str]:
    """Scan-level metrics section (e.g. scb-check's SlopCodeBench
    composites) — trendable across runs."""
    sources = [r for r in results if r.metrics]
    if not sources:
        return []
    lines = ["## Scan metrics", ""]
    for r in sources:
        lines.append(f"**{r.tool}**:")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for key, value in r.metrics.items():
            if isinstance(value, dict):  # e.g. syntax_by_language
                lines.append(f"| {key} | `{json.dumps(value, sort_keys=True)}` |")
            else:
                lines.append(f"| {key} | {value} |")
        lines.append("")
    return lines


def _findings_sections(findings: list) -> list[str]:
    """Generate per-category findings sections."""
    per_cat_cap = 50
    grouped: dict[Category, list] = {c: [] for c in Category}
    for f in findings:
        grouped[f.category].append(f)

    lines: list[str] = []
    for cat in Category:
        items = sorted(grouped[cat], key=lambda f: (-f.severity.value, f.tool, f.file or ""))
        if not items:
            continue
        lines.extend(_category_findings_table(cat, items, per_cat_cap))
    return lines


_RULE_EXAMPLE_CAP = 5


def _category_findings_table(cat: Category, items: list, cap: int) -> list[str]:
    """Generate a findings table for a single category.

    Rows are capped twice: per rule (a rule repeated 50 times is one
    insight, not 50 rows) and per category. Both notes carry the exact
    hidden count so nothing is silently dropped.
    """
    lines = [
        f"## {cat.value} ({len(items)})",
        "",
        "| Severity | Tool | Rule | Location | Message |",
        "|----------|------|------|----------|---------|",
    ]
    per_rule: Counter = Counter()
    shown = 0
    for f in items:
        if shown >= cap:
            break
        if per_rule[f.rule] >= _RULE_EXAMPLE_CAP:
            continue
        per_rule[f.rule] += 1
        shown += 1
        sev = _SEV_BADGE.get(f.severity, "?")
        loc = f.file or "?"
        if f.line:
            loc += f":{f.line}"
        msg = f.message.replace("|", "\\|")[:120]
        lines.append(f"| {sev} | `{f.tool}` | `{f.rule}` | `{loc}` | {msg} |")
    hidden = len(items) - shown
    if hidden:
        lines.extend([
            "",
            f"_…and {hidden} more (capped at {_RULE_EXAMPLE_CAP} examples "
            f"per rule, {cap} per category). See `polycheck-report.json` "
            f"for the full list._",
        ])
    lines.append("")
    return lines
