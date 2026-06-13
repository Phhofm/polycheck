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

    by_sev = Counter(f.severity for f in findings)
    by_cat = Counter(f.category for f in findings)

    lines: list[str] = []
    lines.append(f"# polycheck report — `{repo.name}`")
    lines.append("")
    lines.append(
        f"**Total findings:** {len(findings)} | "
        f"**Tools run:** {len(results)} | "
        f"**Tools failed:** "
        f"{sum(1 for r in results if r.status in ('error', 'timeout'))}"
    )
    lines.append("")

    # Severity breakdown
    lines.append("## By severity")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|----------|-------|")
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO):
        n = by_sev.get(sev, 0)
        if n:
            lines.append(f"| {_SEV_BADGE[sev]} | {n} |")
    lines.append("")

    # Category breakdown
    lines.append("## By category")
    lines.append("")
    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        if n:
            lines.append(f"| {cat.value} | {n} |")
    lines.append("")

    # Tool execution
    lines.append("## Tool execution")
    lines.append("")
    lines.append("| Tool | Status | Duration (s) | Findings |")
    lines.append("|------|--------|--------------|----------|")
    for r in results:
        lines.append(
            f"| `{r.tool}` | {r.status} | {r.duration_sec:.1f} | {len(r.findings)} |"
        )
    if any(r.error for r in results):
        lines.append("")
        lines.append("### Tool errors")
        lines.append("")
        for r in results:
            if r.error:
                lines.append(f"- **{r.tool}**: `{r.error}`")
    lines.append("")

    # Per-category sections, capped at 50 findings per category so the
    # report doesn't explode. The LLM prompt tells the agent to read
    # the full JSON if it needs more.
    per_cat_cap = 50
    grouped: dict[Category, list] = {c: [] for c in Category}
    for f in findings:
        grouped[f.category].append(f)

    for cat in Category:
        items = sorted(grouped[cat], key=lambda f: (-f.severity.value, f.tool, f.file or ""))
        if not items:
            continue
        lines.append(f"## {cat.value} ({len(items)})")
        lines.append("")
        lines.append("| Severity | Tool | Rule | Location | Message |")
        lines.append("|----------|------|------|----------|---------|")
        for f in items[:per_cat_cap]:
            sev = _SEV_BADGE.get(f.severity, "?")
            loc = f.file or "?"
            if f.line:
                loc += f":{f.line}"
            msg = f.message.replace("|", "\\|")[:120]
            lines.append(f"| {sev} | `{f.tool}` | `{f.rule}` | `{loc}` | {msg} |")
        if len(items) > per_cat_cap:
            lines.append("")
            lines.append(
                f"_…and {len(items) - per_cat_cap} more. See "
                f"`polycheck-report.json` for the full list._"
            )
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return [out]
