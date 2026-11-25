"""Named scan profiles — presets over existing primitives.

Two profiles plus the unchanged default (design decision, 2026-11-25):

* ``pr``   — pre-push/PR gate: fast tools only (heavy and structural
  adapters off), scoped to changed tracked files, gate HIGH.
* ``deep`` — onboarding / periodic full pass: every tool including
  heavy ones, no gate by default; output feeds triage → baseline.
* default — the whole-repo fast scan with the MEDIUM gate, unchanged.

A profile never adds a new engine; it only presets tool selection,
scoping, and the gate that already exist.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .finding import Finding
from .verify import HEAVY_TOOLS


@dataclass(frozen=True)
class ProfileSpec:
    """What one named profile presets."""

    name: str
    description: str
    skip_heavy: bool        # skip Docker/network-heavy tools (sonarless, …)
    skip_structural: bool   # skip structural adapters (tach, …)
    scoped_to_changes: bool # only findings in changed tracked files
    fail_on: str | None     # gate preset; None = no gate / caller default


PROFILES: dict[str, ProfileSpec] = {
    "pr": ProfileSpec(
        name="pr",
        description=(
            "pre-push/PR gate: fast tools only, findings scoped to changed "
            "tracked files, fails on HIGH+"
        ),
        skip_heavy=True,
        skip_structural=True,
        scoped_to_changes=True,
        fail_on="HIGH",
    ),
    "deep": ProfileSpec(
        name="deep",
        description=(
            "onboarding/periodic full pass: every tool including heavy "
            "ones, no gate — feed the report into triage, then baseline"
        ),
        skip_heavy=False,
        skip_structural=False,
        scoped_to_changes=False,
        fail_on=None,
    ),
}


class ProfileError(ValueError):
    """Raised for an unknown --profile value."""


def resolve_profile(name: str | None) -> ProfileSpec | None:
    """Resolve a CLI/MCP profile name, or None for the default scan."""
    if name is None:
        return None
    spec = PROFILES.get(name)
    if spec is None:
        raise ProfileError(
            f"unknown profile '{name}'. Available: {', '.join(sorted(PROFILES))}"
        )
    return spec


def effective_fail_on(
    profile: ProfileSpec | None, explicit: str | None
) -> str | None:
    """The gate the run should use.

    An explicit --fail-on always wins. Otherwise: pr presets HIGH,
    deep presets "no gate" (None), the default scan keeps MEDIUM.
    """
    if explicit is not None:
        return explicit
    if profile is None:
        return "MEDIUM"
    return profile.fail_on


def default_severity(profile: ProfileSpec | None) -> str:
    """The severity floor matching the profile's intent.

    The pr gate is HIGH, so findings below HIGH are noise there; deep
    and the default keep the MEDIUM floor so the report stays complete.
    """
    if profile is None or profile.fail_on is None:
        return "MEDIUM"
    return profile.fail_on


def is_skipped(cls, profile: ProfileSpec | None) -> bool:
    """Whether a tool class is outside the profile's tool selection.

    ``pr`` keeps the fast tools only: no Docker/network-heavy tools
    (sonarless, semgrep, pip-audit, npm-audit) and no structural
    adapters. ``deep`` and the default keep everything that is
    installed and applicable.
    """
    if profile is None:
        return False
    if profile.skip_heavy and cls.name in HEAVY_TOOLS:
        return True
    if profile.skip_structural and getattr(cls, "structural", False):
        return True
    return False


def changed_files(repo: Path) -> set[str] | None:
    """The repo-relative POSIX paths of changed tracked files.

    Scope = uncommitted tracked changes (vs HEAD) plus, when an upstream
    exists, everything HEAD is ahead of the merge-base — the push and
    the PR, not the whole repo. ``None`` when ``repo`` is not a git
    repo (the caller decides whether that is fatal).

    Deleted files appear in the set too; they simply produce no findings.
    """
    repo = Path(repo)
    if not (repo / ".git").exists():
        return None
    files = _git_lines(repo, ["diff", "--name-only", "HEAD"])
    if files is None:
        # No commits yet: everything staged in the index is "new".
        return {line for line in (_git_lines(repo, ["ls-files"]) or set()) if line}
    files = {line for line in files if line}

    upstream = _git_lines(
        repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    if upstream:
        upstream_name = sorted(upstream)[0]
        merge_base = _git_lines(repo, ["merge-base", "HEAD", upstream_name])
        if merge_base:
            ahead = _git_lines(
                repo, ["diff", "--name-only", f"{sorted(merge_base)[0]}..HEAD"]
            )
            if ahead is not None:
                files |= {line for line in ahead if line}
    return files


def _git_lines(repo: Path, argv: list[str]) -> set[str] | None:
    """Run a git command in ``repo``; None signals "command failed"."""
    try:
        out = subprocess.run(
            ["git", *argv], cwd=repo, capture_output=True, text=True, timeout=60
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return set(out.stdout.splitlines())


def filter_by_scope(
    findings: list[Finding], files: set[str] | None
) -> list[Finding]:
    """Drop findings in files that did not change.

    ``None`` (no scoping in play) is an identity function. Findings
    without a file — repo-level concerns like CVEs and package-level
    dependency findings — stay in scope: a vulnerable dependency matters
    even when its manifest was not touched.
    """
    if files is None:
        return findings
    return [f for f in findings if f.file is None or f.file in files]
