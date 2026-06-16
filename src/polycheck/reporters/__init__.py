"""Reporter registry.

Maps a format name to a renderer. The CLI uses this to dispatch.
"""

from __future__ import annotations

from pathlib import Path

from ..finding import Finding
from ..runner import ToolResult
from . import json_reporter, markdown_reporter, sarif_reporter

REPORTERS = {
    "json": json_reporter.render,
    "markdown": markdown_reporter.render,
    "sarif": sarif_reporter.render,
}


def render(
    fmt: str,
    repo: Path,
    findings: list[Finding],
    results: list[ToolResult],
    *,
    report_dir: Path,
) -> list[Path]:
    """Dispatch to the right renderer. Unknown format → empty list."""
    fn = REPORTERS.get(fmt)
    if fn is None:
        return []
    return fn(repo, findings, results, report_dir=report_dir)
