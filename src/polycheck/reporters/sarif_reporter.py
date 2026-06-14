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

    rules, results_sarif = _build_sarif_results(repo, findings, results)
    sarif = _build_sarif_document(rules, results_sarif)

    out.write_text(json.dumps(sarif, indent=2), encoding="utf-8")
    return [out]


def _build_sarif_results(repo: Path, findings: list, results: list[ToolResult]) -> tuple[dict, list]:
    """Build SARIF rules and results from findings."""
    rules: dict[str, dict] = {}
    results_sarif: list[dict] = []

    for f in findings:
        rule_id = f"{f.tool}/{f.rule}"
        if rule_id not in rules:
            rules[rule_id] = _make_rule(rule_id, f)
        results_sarif.append(_make_result(repo, f, rule_id))

    return rules, results_sarif


def _make_rule(rule_id: str, f) -> dict:
    """Create a SARIF rule definition."""
    return {
        "id": rule_id,
        "name": f.rule,
        "shortDescription": {"text": f"{f.tool}: {f.rule}"},
        "defaultConfiguration": {"level": _SARIF_LEVEL.get(f.severity, "warning")},
    }


def _make_result(repo: Path, f, rule_id: str) -> dict:
    """Create a SARIF result for a finding."""
    result: dict = {
        "ruleId": rule_id,
        "level": _SARIF_LEVEL.get(f.severity, "warning"),
        "message": {"text": f.message},
    }
    if f.file:
        result["locations"] = [_make_location(repo, f)]
    if f.doc_url:
        result["properties"] = {"helpUri": f.doc_url}
    return result


def _make_location(repo: Path, f) -> dict:
    """Create a SARIF location for a finding."""
    uri = f.file if f.file.startswith("/") else f"{repo.name}/{f.file}"
    region: dict = {}
    if f.line:
        region["startLine"] = f.line
    if f.column:
        region["startColumn"] = f.column
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": uri},
            "region": region,
        }
    }


def _build_sarif_document(rules: dict, results_sarif: list) -> dict:
    """Build the complete SARIF document."""
    return {
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
