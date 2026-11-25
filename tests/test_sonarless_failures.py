"""sonarless failure-detection tests (external live test #7).

The field failure: `sonarless scan` printed "SonarQube scanning
failed!" and exited 0 (the SonarQube Java analyzer aborted on
Capacitor's uncompiled .java files). polycheck saw rc 0, queried the
issues API, got zero issues and reported **no-findings** — a failed
scan reading as a clean bill of health (the D1 failure mode).

Rule after this block: a sonarless run that did not produce a fresh
analysis on the SonarQube server raises instead of reporting clean.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from polycheck.tools import sonarless
from polycheck.tools.sonarless import SonarlessTool

_NOW = datetime.now(timezone.utc)


def _fast_poll(monkeypatch) -> None:
    monkeypatch.setattr(sonarless, "_CE_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(sonarless, "_CE_POLL_TIMEOUT_S", 0.05)


def _fake_scan(stdout: str = "SonarQube scanning done", returncode: int = 0):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return fake_run


def _api_with_last_analysis(last: str | None):
    """Fake the two API calls: components/show (lastAnalysis) and
    issues/search (payload)."""

    def fake_get(url, **kwargs):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                if "navigation/component" in url:
                    return {"analysisDate": last}
                return {"issues": [], "facets": []}

        return _Resp()

    return fake_get


def test_scan_failure_marker_raises(monkeypatch, tmp_path: Path):
    """The live failure: sonarless prints 'SonarQube scanning failed!'
    and exits 0 — polycheck must raise, never report clean."""
    tool = SonarlessTool()
    monkeypatch.setattr("polycheck.tools.sonarless.subprocess.run", _fake_scan(
        stdout="ERROR Error during SonarScanner Engine execution\n"
               "SonarQube scanning failed!",
        returncode=0,
    ))
    monkeypatch.setattr(
        "requests.get", _api_with_last_analysis(None),
    )

    with pytest.raises(RuntimeError, match="failed"):
        tool.run(tmp_path)


def test_missing_analysis_on_server_raises(monkeypatch, tmp_path: Path):
    _fast_poll(monkeypatch)
    """Project exists but lastAnalysis is null — the scan never landed
    (Loop 5: 'lastAnalysis=undefined and null scan tasks')."""
    tool = SonarlessTool()
    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run",
        _fake_scan(stdout="SonarQube scanning done"),
    )
    monkeypatch.setattr("requests.get", _api_with_last_analysis(None))

    with pytest.raises(RuntimeError, match="analysis"):
        tool.run(tmp_path)


def test_stale_analysis_raises(monkeypatch, tmp_path: Path):
    _fast_poll(monkeypatch)
    """A PREVIOUS scan's lastAnalysis must not pass for a fresh run:
    the timestamp has to be newer than the scan start."""
    tool = SonarlessTool()
    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run",
        _fake_scan(stdout="SonarQube scanning done"),
    )
    stale = (_NOW - timedelta(hours=2)).isoformat()
    monkeypatch.setattr("requests.get", _api_with_last_analysis(stale))

    with pytest.raises(RuntimeError, match="stale|analysis"):
        tool.run(tmp_path)


def test_fresh_analysis_proceeds_to_issues(monkeypatch, tmp_path: Path):
    """Happy path: rc 0, fresh lastAnalysis after the scan start, and
    the issues API returns hits — findings flow as before."""
    tool = SonarlessTool()
    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run",
        _fake_scan(stdout="SonarQube scanning done"),
    )
    fresh = (_NOW + timedelta(seconds=10)).isoformat()

    def fake_get(url, **kwargs):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                if "navigation/component" in url:
                    return {"analysisDate": fresh}
                return {"issues": [{
                    "rule": "python:S930",
                    "severity": "BLOCKER",
                    "type": "BUG",
                    "component": "demo:app.py",
                    "line": 3,
                    "message": "bug",
                }]}

        return _Resp()

    monkeypatch.setattr("requests.get", fake_get)

    findings = tool.run(tmp_path)

    assert len(findings) == 1
    assert findings[0].severity.name == "CRITICAL"


def test_issues_api_failure_raises_instead_of_clean(monkeypatch, tmp_path: Path):
    """A scan that landed but whose issues API call fails must raise —
    not read as zero findings."""
    tool = SonarlessTool()
    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run",
        _fake_scan(stdout="SonarQube scanning done"),
    )
    fresh = (_NOW + timedelta(seconds=10)).isoformat()

    import requests

    def fake_get(url, **kwargs):
        if "navigation/component" in url:
            class _Ok:
                status_code = 200

                def raise_for_status(self):
                    return None

                def json(self):
                    return {"analysisDate": fresh}

            return _Ok()
        raise requests.RequestException("connection reset")

    monkeypatch.setattr("requests.get", fake_get)

    with pytest.raises(RuntimeError):
        tool.run(tmp_path)


def test_nonzero_scan_exit_raises(monkeypatch, tmp_path: Path):
    tool = SonarlessTool()
    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run",
        _fake_scan(stdout="boom", returncode=3),
    )

    with pytest.raises(RuntimeError, match="sonarless scan failed"):
        tool.run(tmp_path)


def test_scanner_properties_written_and_removed(monkeypatch, tmp_path: Path):
    """The SonarScanner reads sonar-project.properties; the adapter
    writes default exclusions (node_modules, capacitor android/ios)
    when the repo has none — and removes the file after the scan."""
    tool = SonarlessTool()
    seen: dict = {}

    def fake_run(cmd, **kw):
        props = tmp_path / "sonar-project.properties"
        seen["existed_during_scan"] = props.exists()
        seen["content"] = props.read_text(encoding="utf-8") if props.exists() else ""
        return subprocess.CompletedProcess(cmd, 0, stdout="SonarQube scanning done", stderr="")

    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run", fake_run
    )
    fresh = (_NOW + timedelta(seconds=10)).isoformat()
    monkeypatch.setattr("requests.get", _api_with_last_analysis(fresh))

    tool.run(tmp_path)

    assert seen["existed_during_scan"] is True
    assert "node_modules" in seen["content"]
    assert "android" in seen["content"]
    assert not (tmp_path / "sonar-project.properties").exists()


def test_existing_scanner_properties_left_alone(monkeypatch, tmp_path: Path):
    tool = SonarlessTool()
    (tmp_path / "sonar-project.properties").write_text("sonar.exclusions=**/custom/**\n")
    before = (tmp_path / "sonar-project.properties").read_text(encoding="utf-8")

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="SonarQube scanning done", stderr="")

    monkeypatch.setattr(
        "polycheck.tools.sonarless.subprocess.run", fake_run
    )
    fresh = (_NOW + timedelta(seconds=10)).isoformat()
    monkeypatch.setattr("requests.get", _api_with_last_analysis(fresh))

    tool.run(tmp_path)

    assert (tmp_path / "sonar-project.properties").read_text(encoding="utf-8") == before
