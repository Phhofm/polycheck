"""SARIF reporter — emits SARIF 2.1.0 JSON for IDE integration.

SARIF is the OASIS standard that GitHub Code Scanning, VS Code, and
most CI dashboards consume. This is *optional* output — most users
will only want the markdown + JSON pair.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..finding import Severity
from ..runner import ToolResult

# SARIF severity mapping
_SARIF_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def render(
    repo: Path,
    findings: list,
    results: list[ToolResult],
    *,
    report_dir: Path,
) -> list[Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / "polycheck-report.sarif"

    # One tool per underlying analyzer; URI is the polycheck version.
    rules: dict[str, dict] = {}
    results_sarif: list[dict] = []

    for f in findings:
        rule_id = f"{f.tool}/{f.rule}"
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": f.rule,
                "shortDescription": {"text": f"{f.tool}: {f.rule}"},
                "defaultConfiguration": {"level": _SARIF_LEVEL.get(f.severity, "warning")},
            }
        result: dict = {
            "ruleId": rule_id,
            "level": _SARIF_LEVEL.get(f.severity, "warning"),
            "message": {"text": f.message},
        }
        if f.file:
            uri = f.file
            if not uri.startswith("/"):
                uri = f"{repo.name}/{uri}"
            loc: dict = {
                "physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {},
                }
            }
            if f.line:
                loc["physicalLocation"]["region"]["startLine"] = f.line
            if f.column:
                loc["physicalLocation"]["region"]["startColumn"] = f.column
            result["locations"] = [loc]
        if f.doc_url:
            result["properties"] = {"helpUri": f.doc_url}
        results_sarif.append(result)

    sarif = {
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "polycheck",
                        "informationUri": "https://github.com/KiloApp2/polycheck",
                        "version": "0.1.0",
                        "rules": list(rules.values()),
                    }
                },
                "results": results_sarif,
            }
        ],
    }
    out.write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    return [out]
