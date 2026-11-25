"""gitleaks gitignore exclusion — regression tests for the nested-.gitignore
leak found by external live test #6 (ionic-vue-new).

`_ignored_paths` collects `git ls-files -o -i --exclude-standard
--directory` and feeds them into the generated allowlist. The leak: the
adapter passed the repo root ABSOLUTE to `gitleaks --source`, so
gitleaks reported ABSOLUTE file paths — and the relative-anchored
allowlist regexes (`^client/android/...`) never matched, letting 1408
CRITICAL findings from gitignored build assets flood the report.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from polycheck.tools.gitleaks import GitleaksTool

_GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]

_REQUIRE_GITLEAKS = pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks binary not installed"
)


def _seed_nested_repo(tmp_path: Path) -> None:
    """client/android with a NESTED .gitignore ignoring the capacitor
    build assets — the exact shape from the live test."""
    (tmp_path / "client" / "android" / "app" / "src" / "main" / "assets" / "public" / "assets" / "js").mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n")
    (tmp_path / "client" / "android" / ".gitignore").write_text("public/\n")
    (tmp_path / "client" / "android" / "app" / "src" / "main" / "assets" / "public" / "assets" / "js" / "bundle.js").write_text(
        'var apiKey = "AKIAQW7YJ2KX9P3M4NB8";\n'
    )
    (tmp_path / "README.md").write_text("# repo\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run([*_GIT, "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run([*_GIT, "commit", "-qm", "base"], cwd=tmp_path, check=True)


def test_gitleaks_source_arg_is_relative(tmp_path: Path):
    """The allowlist is relative-anchored; an absolute --source makes
    gitleaks report absolute paths and the allowlist never matches."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    import unittest.mock as mock

    with mock.patch(
        "polycheck.tools.gitleaks.shutil.which",
        lambda name: "/usr/bin/gitleaks" if name == "gitleaks" else None,
    ), mock.patch(
        "polycheck.tools.gitleaks.subprocess.run", fake_run
    ):
        GitleaksTool().run(tmp_path)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--source") + 1] == "."


@_REQUIRE_GITLEAKS
def test_gitleaks_excludes_nested_gitignored_build_assets(tmp_path: Path):
    """The live-test leak: 1408 CRITICALs from gitignored capacitor
    assets flooding the report. The nested .gitignore must be honored."""
    _seed_nested_repo(tmp_path)

    findings = GitleaksTool().run(tmp_path)

    leaked = [f for f in findings if "assets/public" in (f.file or "")]
    assert leaked == [], [f.file for f in leaked]
