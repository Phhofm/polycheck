"""Tests for polycheck session logging."""
from __future__ import annotations

import json
from pathlib import Path

from polycheck.session import append_event, write_run_summary, write_session_summary


def test_session_logging_writes_run_and_latest_files(tmp_path: Path):
    summary = {
        "repo": str(tmp_path),
        "status": "completed",
        "next_action": "none",
        "total_findings": 0,
        "by_severity": {},
        "tools_run": [],
        "reports": [str(tmp_path / "polycheck-reports" / "polycheck-report.md")],
    }

    append_event(tmp_path, "run-1", {"event": "scan_started"})
    write_run_summary(tmp_path, "run-1", summary)
    session = write_session_summary(tmp_path, summary)

    assert (tmp_path / ".polycheck" / "runs" / "run-1" / "run.jsonl").exists()
    assert (tmp_path / ".polycheck" / "runs" / "run-1" / "summary.md").exists()
    assert Path(session["markdown"]).exists()
    assert Path(session["json"]).exists()
    assert Path(session["latest_markdown"]).exists()
    assert Path(session["latest_json"]).exists()

    payload = json.loads(Path(session["json"]).read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
