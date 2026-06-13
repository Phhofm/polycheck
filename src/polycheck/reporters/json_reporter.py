"""JSON reporter — emits a single JSON file with the run summary and
all findings. This is the canonical machine-readable output and the
format the LLM-triage prompt is designed to consume."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..runner import ToolResult


def render(
    repo: Path,
    findings: list,
    results: list[ToolResult],
    *,
    report_dir: Path,
) -> list[Path]:
    """Write ``polycheck-report.json`` to ``report_dir``.

    Returns the list of files written.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / "polycheck-report.json"

    by_sev = Counter(f.severity.name for f in findings)
    by_cat = Counter(f.category.value for f in findings)
    by_tool = Counter(f.tool for f in findings)

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "summary": {
            "total_findings": len(findings),
            "by_severity": dict(by_sev),
            "by_category": dict(by_cat),
            "by_tool": dict(by_tool),
            "tools_run": len(results),
            "tools_failed": [r.tool for r in results if r.status in ("error", "timeout")],
        },
        "tools": [
            {
                "name": r.tool,
                "status": r.status,
                "duration_sec": round(r.duration_sec, 2),
                "finding_count": len(r.findings),
                "error": r.error,
            }
            for r in results
        ],
        "findings": [f.to_dict() for f in findings],
    }

    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return [out]
