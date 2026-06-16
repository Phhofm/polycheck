"""Tests for sonarless install behavior."""
from __future__ import annotations

import subprocess

import pytest

from polycheck.tools import sonarless
from polycheck.tools.sonarless import SonarlessTool


def test_sonarless_missing_tool_dict_marks_auto_installable(monkeypatch):
    from polycheck import mcp_server

    monkeypatch.setattr(sonarless, "_docker_available", lambda: True)
    monkeypatch.setattr(sonarless.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    payload = mcp_server._missing_tool_to_dict(SonarlessTool)

    assert payload["name"] == "sonarless"
    assert payload["auto_installable"] is True


def test_sonarless_install_requires_docker(monkeypatch):
    monkeypatch.setattr(sonarless, "_docker_available", lambda: False)
    monkeypatch.setattr(sonarless.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected run"))

    ok, message = SonarlessTool().install()

    assert ok is False
    assert "Docker is required" in message


def test_sonarless_install_runs_official_script(monkeypatch):
    state = {"installed": False, "calls": []}

    def fake_which(name: str) -> str | None:
        return "/usr/bin/curl" if name == "curl" else None

    def fake_is_installed(self) -> bool:
        return state["installed"]

    def fake_run(argv, **kwargs):
        state["calls"].append(argv)
        state["installed"] = True
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(sonarless, "_docker_available", lambda: True)
    monkeypatch.setattr(sonarless.shutil, "which", fake_which)
    monkeypatch.setattr(SonarlessTool, "is_installed", fake_is_installed)
    monkeypatch.setattr(sonarless.subprocess, "run", fake_run)

    ok, message = SonarlessTool().install()

    assert ok is True
    assert message == "installed sonarless"
    assert state["calls"][0] == [
        "bash",
        "-lc",
        "curl -sSL https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash",
    ]


def test_sonarless_install_without_curl_fails(monkeypatch):
    monkeypatch.setattr(sonarless, "_docker_available", lambda: True)
    monkeypatch.setattr(sonarless.shutil, "which", lambda name: None)

    ok, message = SonarlessTool().install()

    assert ok is False
    assert "curl is required" in message


def test_sonarless_can_auto_install_requires_docker_and_curl(monkeypatch):
    monkeypatch.setattr(sonarless, "_docker_available", lambda: True)
    monkeypatch.setattr(sonarless.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    assert SonarlessTool().can_auto_install() is True

    monkeypatch.setattr(sonarless, "_docker_available", lambda: False)
    assert SonarlessTool().can_auto_install() is False


def test_sonarless_install_hint_is_official_script():
    assert SonarlessTool().install_hint() == (
        "curl -sSL https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash"
    )
