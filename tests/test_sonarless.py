"""Tests for sonarless install behavior."""
from __future__ import annotations

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
