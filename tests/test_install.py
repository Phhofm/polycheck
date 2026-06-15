"""Tests for the install machinery in polycheck.tools.base."""
from __future__ import annotations

from pathlib import Path

from polycheck.finding import Category
from polycheck.tools.base import Tool, build_install_command


class _FakeTool(Tool):
    name = "fake"
    category = Category.LINT
    languages = ["python"]
    installer = "pipx:fake-pkg"

    def is_applicable(self, repo):
        return True

    def run(self, repo):
        return []


class _GithubTool(Tool):
    name = "gh-tool"
    category = Category.LINT
    languages = ["python"]
    installer = "github:owner/repo"

    def is_applicable(self, repo):
        return True

    def run(self, repo):
        return []


class _NoInstallerTool(Tool):
    name = "manual"
    category = Category.LINT
    languages = ["python"]
    installer = None

    def is_applicable(self, repo):
        return True

    def run(self, repo):
        return []


def test_build_install_command_pipx():
    assert build_install_command("pipx:ruff", "ruff") == "pipx install ruff"


def test_build_install_command_npm():
    assert build_install_command("npm:eslint", "eslint") == "npm install -g eslint"


def test_build_install_command_brew():
    assert build_install_command("brew:gitleaks", "gitleaks") == "brew install gitleaks"


def test_build_install_command_apt():
    assert build_install_command("apt:shellcheck", "shellcheck") == "sudo apt install shellcheck"


def test_build_install_command_github_returns_url():
    out = build_install_command("github:gitleaks/gitleaks", "gitleaks")
    # GitHub releases can't be auto-installed, so returns None
    assert out is None


def test_build_install_command_unknown_kind():
    assert build_install_command("snap:foo", "foo") is None


def test_build_install_command_none():
    assert build_install_command(None, "foo") is None


def test_install_hint_uses_installer():
    assert _FakeTool().install_hint() == "pipx install fake-pkg"


def test_install_hint_fallback_when_no_installer():
    hint = _NoInstallerTool().install_hint()
    assert "manual" in hint
    assert "no automatic installer" in hint


def test_install_returns_already_installed(tmp_path: Path, monkeypatch):
    """If is_installed returns True, install() is a no-op success."""
    t = _FakeTool()
    monkeypatch.setattr(t, "is_installed", lambda: True)
    ok, msg = t.install()
    assert ok is True
    assert "already installed" in msg


def test_install_no_installer_returns_hint():
    t = _NoInstallerTool()
    ok, msg = t.install()
    assert ok is False
    assert "no automatic installer" in msg


def test_install_github_returns_url_not_shell_command():
    """github: installers are not runnable shell commands; install() should
    decline and tell the user the URL."""
    t = _GithubTool()
    ok, msg = t.install()
    assert ok is False
    assert "github.com/owner/repo" in msg
