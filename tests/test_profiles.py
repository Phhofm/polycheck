"""Tests for the named scan profiles (0.3.4).

Profiles are presets over existing primitives — tool selection (heavy
and structural tools), scoping (changed tracked files), and the gate
(exit-code threshold). The default scan stays unchanged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from polycheck.finding import Category, Finding, Severity


def _f(rule: str, file: str | None, line: int = 1) -> Finding:
    return Finding(
        tool="t", rule=rule, severity=Severity.MEDIUM,
        category=Category.LINT, message=f"{rule}", file=file, line=line,
    )


# --- resolve_profile --------------------------------------------------------


def test_resolve_profile_returns_pr_and_deep_specs():
    from polycheck.profiles import resolve_profile

    pr = resolve_profile("pr")
    deep = resolve_profile("deep")
    assert pr is not None and deep is not None

    assert pr.skip_heavy and pr.skip_structural and pr.scoped_to_changes
    assert pr.fail_on == "HIGH"
    assert not deep.skip_heavy and not deep.scoped_to_changes
    assert deep.fail_on is None  # no gate by default


def test_resolve_profile_rejects_unknown():
    from polycheck.profiles import ProfileError, resolve_profile

    with pytest.raises(ProfileError, match="pr"):
        resolve_profile("turbo")


# --- effective_fail_on ------------------------------------------------------


def test_effective_fail_on_matrix():
    from polycheck.profiles import effective_fail_on, resolve_profile

    assert effective_fail_on(None, None) == "MEDIUM"          # unchanged default
    assert effective_fail_on(resolve_profile("pr"), None) == "HIGH"
    assert effective_fail_on(resolve_profile("deep"), None) is None  # no gate
    # An explicit --fail-on always wins over the profile preset.
    assert effective_fail_on(resolve_profile("pr"), "LOW") == "LOW"
    assert effective_fail_on(resolve_profile("deep"), "HIGH") == "HIGH"


def test_default_severity_matches_profile_intent():
    from polycheck.profiles import default_severity, resolve_profile

    assert default_severity(None) == "MEDIUM"
    assert default_severity(resolve_profile("pr")) == "HIGH"
    assert default_severity(resolve_profile("deep")) == "MEDIUM"


# --- changed_files ----------------------------------------------------------


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *argv],
        cwd=repo, check=True, capture_output=True,
    )


def test_changed_files_covers_uncommitted_and_upstream_ahead(tmp_path: Path):
    from polycheck.profiles import changed_files

    (tmp_path / "base.py").write_text("x = 1\n")
    (tmp_path / "other.py").write_text("y = 2\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    # A local "upstream" one commit behind HEAD.
    _git(tmp_path, "branch", "upstream-main")
    (tmp_path / "committed.py").write_text("z = 3\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "ahead")
    (tmp_path / "dirty.py").write_text("d = 4\n")
    _git(tmp_path, "add", "dirty.py")
    # Point the branch at the local upstream marker (no real remote needed).
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "upstream-main")
    _git(tmp_path, "config", "remote.origin.url", str(tmp_path))
    _git(tmp_path, "config", "remote.origin.fetch",
         "+refs/heads/*:refs/remotes/origin/*")
    _git(tmp_path, "config", "branch.main.remote", "origin")
    _git(tmp_path, "config", "branch.main.merge", "refs/heads/main")
    _git(tmp_path, "config", "branch.master.remote", "origin")
    _git(tmp_path, "config", "branch.master.merge", "refs/heads/main")

    changed = changed_files(tmp_path)

    assert changed is not None
    assert "committed.py" in changed   # commit ahead of merge-base
    assert "dirty.py" in changed       # staged working-tree change
    assert "base.py" not in changed    # untouched file is out of scope
    assert "other.py" not in changed


def test_changed_files_fresh_repo_without_commits_lists_index(tmp_path: Path):
    from polycheck.profiles import changed_files

    _git(tmp_path, "init", "-q")
    (tmp_path / "first.py").write_text("x = 1\n")
    _git(tmp_path, "add", "first.py")

    changed = changed_files(tmp_path)

    assert changed == {"first.py"}


def test_changed_files_non_git_repo_returns_none(tmp_path: Path):
    from polycheck.profiles import changed_files

    assert changed_files(tmp_path) is None


# --- filter_by_scope --------------------------------------------------------


def test_filter_by_scope_drops_unchanged_files():
    from polycheck.profiles import filter_by_scope

    findings = [_f("R1", "changed.py"), _f("R2", "untouched.py")]

    out = filter_by_scope(findings, {"changed.py", "staged.py"})

    assert [f.rule for f in out] == ["R1"]


def test_filter_by_scope_keeps_fileless_findings():
    """Repo-level findings (CVEs, package-level deps) have no file —
    they cannot be scoped away by a file diff."""
    from polycheck.profiles import filter_by_scope

    cve = _f("GHSA-xxxx", None)

    assert filter_by_scope([cve], {"other.py"}) == [cve]


def test_filter_by_scope_none_is_identity():
    from polycheck.profiles import filter_by_scope

    findings = [_f("R1", "a.py")]
    assert filter_by_scope(findings, None) == findings


def test_changed_files_without_upstream_gates_everything_pushable(tmp_path: Path):
    """First push to a fresh remote: no upstream exists, so the merge-base
    logic cannot scope. Everything tracked (committed + staged) can be
    carried by that push — the gate must see it, or the very first push
    bypasses the HIGH gate entirely (0.3.5)."""
    from polycheck.profiles import changed_files

    _git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "b.py").write_text("y = 2\n")
    _git(tmp_path, "add", "b.py")

    changed = changed_files(tmp_path)

    assert changed == {"a.py", "b.py"}
