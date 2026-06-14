"""Markdown reporter — human-readable summary + per-category tables.

This is the format the LLM-triage prompt is designed to read. The
``findings:markdown`` MCP resource will return the same content, so
agents can ``read_file()`` the report rather than re-walk the JSON.
"""
from __future__ import annotations

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
) -> list[Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / "polycheck-report.md"

    lines: list[str] = []
    lines.extend(_header(repo, findings, results))
    lines.extend(_severity_section(findings))
    lines.extend(_category_section(findings))
    lines.extend(_tool_execution_section(results))
    lines.extend(_findings_sections(findings))

    out.write_text("\n".join(lines), encoding="utf-8")
    return [out]


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


def _category_findings_table(cat: Category, items: list, cap: int) -> list[str]:
    """Generate a findings table for a single category."""
    lines = [
        f"## {cat.value} ({len(items)})",
        "",
        "| Severity | Tool | Rule | Location | Message |",
        "|----------|------|------|----------|---------|",
    ]
    for f in items[:cap]:
        sev = _SEV_BADGE.get(f.severity, "?")
        loc = f.file or "?"
        if f.line:
            loc += f":{f.line}"
        msg = f.message.replace("|", "\\|")[:120]
        lines.append(f"| {sev} | `{f.tool}` | `{f.rule}` | `{loc}` | {msg} |")
    if len(items) > cap:
        lines.extend([
            "",
            f"_…and {len(items) - cap} more. See "
            f"`polycheck-report.json` for the full list._",
        ])
    lines.append("")
    return lines
