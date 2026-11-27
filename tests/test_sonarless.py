"""Tests for sonarless install behavior."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from polycheck.tools import sonarless
from polycheck.tools.sonarless import SonarlessTool


def test_sonarless_missing_tool_dict_marks_manual_install(monkeypatch):
    from polycheck import mcp_server

    payload = mcp_server._missing_tool_to_dict(SonarlessTool)

    assert payload["name"] == "sonarless"
    assert payload["auto_installable"] is False
    assert "curl" in payload["install_hint"]


def test_sonarless_install_is_manual_hint_only(monkeypatch):
    """Installing by piping a remote script into bash is a supply-chain
    risk; polycheck declines and hands the user the command instead."""
    monkeypatch.setattr(SonarlessTool, "is_installed", lambda self: False)
    monkeypatch.setattr(sonarless.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected run"))

    ok, message = SonarlessTool().install()

    assert ok is False
    assert "no automatic installer" in message
    assert "curl -sSL" in message
    assert SonarlessTool().can_auto_install() is False


def test_sonarless_install_hint_is_official_script():
    assert SonarlessTool().install_hint() == (
        "curl -sSL https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash"
    )


# --- PATH-independent detection (0.3.14) ---------------------------------------


def test_sonarless_detected_at_well_known_location(monkeypatch, tmp_path):
    """The sonarless installer targets ~/.sonarless but does not promise
    a PATH entry — live test 2026-11-27: an installed sonarless was
    reported missing for months because only shutil.which() was probed."""
    monkeypatch.setattr(sonarless.shutil, "which", lambda name: None)
    monkeypatch.setattr(sonarless.Path, "home", staticmethod(lambda: tmp_path))
    tool = SonarlessTool()

    assert tool.is_installed() is False  # not installed yet

    launcher = tmp_path / ".sonarless" / "sonarless"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/bash\nexit 0\n")
    launcher.chmod(0o755)

    assert tool.is_installed() is True
    assert tool.binary == str(launcher)


def test_sonarless_run_invokes_resolved_path(monkeypatch, tmp_path):
    """A PATH-less install must still be runnable — the adapter invokes
    the resolved absolute path, never the bare name."""
    monkeypatch.setattr(sonarless.shutil, "which", lambda name: None)
    monkeypatch.setattr(sonarless.Path, "home", staticmethod(lambda: tmp_path))
    launcher = tmp_path / ".sonarless" / "sonarless"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/bash\nexit 0\n")
    launcher.chmod(0o755)

    captured = {}

    class _Proc:
        returncode = 0
        stdout = "issues: 0"
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _Proc()

    monkeypatch.setattr(sonarless.subprocess, "run", fake_run)
    monkeypatch.setattr(
        SonarlessTool, "_analysis_date",
        lambda self, name: datetime.now(timezone.utc).isoformat(),
    )
    monkeypatch.setattr(SonarlessTool, "_query_issues", lambda self, name: [])
    SonarlessTool().run(tmp_path)

    assert captured["argv"][0] == str(launcher)


def test_sonarless_not_installed_without_home_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(sonarless.shutil, "which", lambda name: None)
    monkeypatch.setattr(sonarless.Path, "home", staticmethod(lambda: tmp_path))
    assert SonarlessTool().is_installed() is False
