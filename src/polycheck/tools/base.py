"""Tool plugin abstract base class.

A tool is a wrapper around an external analyzer (ruff, eslint, gitleaks,
etc.). To add a new tool, subclass ``Tool`` and implement:

  * ``name``           — short slug, e.g. "ruff"
  * ``category``       — Finding.Category value
  * ``languages``      — list of language slugs this tool applies to, or
                          ``["*"]`` if it applies to any repo
  * ``is_applicable()`` — does this tool make sense for the repo? E.g.
                          "is there a package.json?"
  * ``run()``          — execute the tool, return ``list[Finding]``

Optionally override:

  * ``install_hint()``  — one-line shell command to install the tool
  * ``version()``       — installed version string, or None
  * ``fix_command()``   — exact shell command to apply auto-fixes
"""
from __future__ import annotations

import abc
import os
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from ..finding import Category, Finding


def npx_command() -> list[str]:
    """argv prefix that runs ``npx`` portably.

    On Windows, npm's shims are ``.cmd`` files that CreateProcess
    cannot execute directly (the smoke test caught WinError 2 there);
    route them through ``cmd /c``. Elsewhere the PATH shim is enough.
    """
    if os.name == "nt":
        return ["cmd", "/c", "npx"]
    return ["npx"]


def npm_command() -> list[str]:
    """argv prefix that runs ``npm`` portably — see :func:`npx_command`."""
    if os.name == "nt":
        return ["cmd", "/c", "npm"]
    return ["npm"]


if TYPE_CHECKING:
    from ..config import Config

# Directories that hold generated, vendored, or dependency code. Scanning
# them produces false positives from other people's code — the exact
# failure mode polycheck exists to prevent — so file-collecting adapters
# route their discovery through iter_source_files().
EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".tox", ".nox", ".eggs",
    ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", "bower_components",
    "dist", "build", "target", "out", "vendor",
    "coverage", "htmlcov", ".next", ".nuxt",
    "site-packages", "polycheck-reports", ".polycheck",
})


def iter_source_files(
    repo: Path, patterns: Iterable[str]
) -> Iterator[Path]:
    """Yield repo-relative source files matching any pattern.

    Git repos: discovery comes from ``git ls-files -co --exclude-standard``,
    so ``.gitignore``d files (foreign harness code, logs, generated trees)
    are never scanned — the #1 source of false positives. Non-git repos
    fall back to a pruned os.walk. ``EXCLUDED_DIRS`` applies in both paths.
    """
    repo = Path(repo)
    if (repo / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "ls-files", "-co", "--exclude-standard"],
                cwd=repo, capture_output=True, text=True, timeout=60,
            )
            if out.returncode == 0:
                yield from _matching(repo, (line for line in out.stdout.splitlines() if line), patterns)
                return
        except (subprocess.TimeoutExpired, OSError):
            pass  # fall through to the walker
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        base = Path(root).relative_to(repo)
        for name in sorted(files):
            rel = base / name if str(base) != "." else Path(name)
            rel_posix = PurePosixPath(rel.as_posix())
            if any(rel_posix.match(pattern) for pattern in patterns):
                yield rel


def _matching(
    repo: Path, rel_names: Iterable[str], patterns: Iterable[str]
) -> Iterator[Path]:
    for name in rel_names:
        rel = Path(name)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        rel_posix = PurePosixPath(rel.as_posix())
        if any(rel_posix.match(pattern) for pattern in patterns):
            yield rel


def annotate_track_status(repo: Path, findings: list[Finding]) -> list[Finding]:
    """Annotate each finding with its git track status.

    ``tracked`` = in the index/history (reaches the repo via push),
    ``ignored`` = matched by ignore rules (never pushed),
    ``untracked`` = in the working tree, not yet committed (can be added),
    ``None`` = not applicable (no git repo, or the "file" is not a real
    path — e.g. a package name from depcheck).

    One ``git ls-files`` call plus one batched ``git check-ignore`` call;
    no per-finding process spawns.
    """
    repo = Path(repo)
    if not (repo / ".git").exists() or not findings:
        return findings

    tracked: set[str] = set()
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=repo, capture_output=True, text=True, timeout=60
        )
        if out.returncode != 0:
            return findings
        tracked = {line for line in out.stdout.splitlines() if line}

        candidates = [
            f.file for f in findings
            if f.file and f.file not in tracked and (repo / f.file).exists()
        ]
        ignored: set[str] = set()
        if candidates:
            ci = subprocess.run(
                ["git", "check-ignore", "--stdin", "-z"],
                cwd=repo, input="\0".join(candidates) + "\0",
                capture_output=True, text=True, timeout=60,
            )
            if ci.returncode in (0, 1):
                ignored = {line for line in ci.stdout.split("\0") if line}
    except (subprocess.TimeoutExpired, OSError):
        return findings

    for f in findings:
        if not f.file:
            continue
        if f.file in tracked:
            f.track = "tracked"
        elif f.file in ignored:
            f.track = "ignored"
        elif (repo / f.file).exists():
            f.track = "untracked"
        # else: pseudo-path (package name etc.) → stays None
    return findings


class Tool(abc.ABC):
    """Base class for all polycheck tool adapters."""

    def __init__(self, config: Config | None = None):
        # Optional config injection: adapters that support per-tool CLI
        # customization read `.polycheck.yml` `extra_args` through
        # self.extra_args(). Everything keeps working when config is
        # absent (constructed as `cls()`).
        self.config = config

    def extra_args(self) -> list[str]:
        """Per-tool extra CLI args from `.polycheck.yml` ``extra_args``."""
        if self.config is None:
            return []
        return [str(a) for a in self.config.extra_args.get(self.name, [])]
    """Base class for analyzer wrappers."""

    #: Short identifier. Used in Finding.tool, in CLI output, in the
    #: ``.polycheck.yml`` enable/disable config.
    name: str = ""

    #: Top-level category. Tools producing different findings should
    #: declare multiple subclasses.
    category: Category = Category.OTHER

    #: Languages this tool applies to. ``["python"]`` or
    #: ``["javascript", "typescript"]`` or ``["*"]`` for any.
    languages: list[str] = []

    #: Whether the tool is multi-language (e.g. semgrep, gitleaks).
    #: When True, the tool runs on every repo regardless of language.
    universal: bool = False

    #: Scan-level metrics a tool can publish alongside its findings
    #: (e.g. scb-check's SlopCodeBench composites: verbosity, erosion,
    #: cog_erosion). Set as an instance attribute during run(); the
    #: runner copies it into the ToolResult and the JSON report embeds
    #: it under ``metrics``. None = no metrics.
    scan_metrics: dict | None = None

    #: Structural adapters (architecture contracts, module boundaries)
    #: are deep-profile tools: fast, but only meaningful when the user
    #: opted in via their config file, and out of the pr fast path.
    structural: bool = False

    #: How to install the tool. One of:
    #:   * ``"pipx:<package>"`` — ``pipx install <package>``
    #:   * ``"pip:<package>"``   — ``pip install --user <package>``
    #:   * ``"npm:<package>"``   — ``npm install -g <package>``
    #:   * ``"brew:<formula>"``  — ``brew install <formula>``
    #:   * ``"apt:<package>"``   — ``apt install <package>``
    #:   * ``"github:<owner>/<repo>"`` — download from GitHub releases
    #:   * ``None``              — no automatic install available
    installer: str | None = None

    @abc.abstractmethod
    def is_applicable(self, repo: Path) -> bool:
        """Return True if the tool makes sense to run on ``repo``.

        Examples:
          * ruff returns True iff ``pyproject.toml`` or ``*.py`` exists.
          * eslint returns True iff ``package.json`` exists.
          * gitleaks always returns True (universal).
        """
        ...

    @abc.abstractmethod
    def run(self, repo: Path) -> list[Finding]:
        """Execute the tool and return normalized findings.

        Implementations should:
          * Locate the binary via ``shutil.which(self.binary)``; if absent
            return an empty list (runner will report it as not installed).
          * Set a sane timeout (default 300s in Runner).
          * Parse the tool's native output (JSON where possible) and
            convert each entry to a ``Finding`` with consistent severity.
        """
        ...

    # ----- Optional hooks -----

    @property
    def binary(self) -> str:
        """The on-disk binary name to look up via shutil.which. Default
        is the tool's ``name`` attribute. Override if the executable
        differs (e.g. ``node_modules/.bin/eslint``)."""
        return self.name

    def is_installed(self) -> bool:
        """True if the underlying binary exists in PATH."""
        return shutil.which(self.binary) is not None

    def not_applicable_reason(self, repo: Path) -> str | None:
        """Why this installed tool does not apply to ``repo``.

        Shown in the run table for tools that are installed and eligible
        but skipped (external live test, 0.3.7: a deep run silently
        dropped tach/pip-audit/dependency-cruiser because their config
        or dependency manifest was absent — understanding that required
        a doctor cross-check). Return None when there is nothing
        meaningful to say; the run table then shows the bare
        ``not-applicable`` status.
        """
        return None

    def install_hint(self) -> str:
        """One-line shell command to install the tool. Shown to the user
        via ``polycheck list-tools`` / ``polycheck doctor`` when the
        tool is missing."""
        cmd = build_install_command(self.installer, self.name)
        if cmd is not None:
            return cmd
        if self.installer and self.installer.startswith("github-release:"):
            repo_path = self.installer.removeprefix("github-release:")
            return (
                f"install {self.name} via your package manager or from "
                f"https://github.com/{repo_path}/releases"
            )
        if self.installer and self.installer.startswith("github:"):
            repo_path = self.installer[len("github:"):]
            return f"download from https://github.com/{repo_path}/releases"
        return f"install {self.name} manually (no automatic installer available)"

    def can_auto_install(self) -> bool:
        """Return True if the base installer can install this tool.

        GitHub-release downloads were removed on purpose: polycheck
        would fetch arbitrary binaries without checksum verification.
        Package-manager-mediated installs (pipx/pip/npm/brew/apt) stay.
        """
        return build_install_command(self.installer, self.name) is not None

    def install(self) -> tuple[bool, str]:
        """Attempt to install the tool. Returns ``(success, message)``.

        Uses the ``installer`` class attribute. Falls back to printing
        the install hint if no installer is registered. We avoid
        ``shell=True`` and split the command ourselves with
        :func:`shlex.split` so we don't introduce a shell-injection
        surface (and so semgrep's ``subprocess-shell-true`` doesn't
        fire on this very file).
        """
        if self.is_installed():
            return True, f"{self.name} is already installed"
        if not self.can_auto_install():
            # Check if this is a github-release installer to give a
            # concrete pointer instead of a generic line.
            if self.installer and self.installer.startswith("github-release:"):
                repo_path = self.installer.removeprefix("github-release:")
                return False, (
                    f"no automatic installer for {self.name}; install via "
                    f"your package manager or from https://github.com/{repo_path}/releases"
                )
            if self.installer and self.installer.startswith("github:"):
                repo_path = self.installer[len("github:"):]
                return False, (
                    f"no automatic installer for {self.name}; "
                    f"download from https://github.com/{repo_path}/releases"
                )
            return False, f"no automatic installer for {self.name}; see {self.install_hint()}"
        cmd = build_install_command(self.installer, self.name)
        if cmd is None:
            return False, f"no automatic installer for {self.name}; see {self.install_hint()}"
        # Check if required package manager is available
        if not self._check_package_manager(cmd):
            return False, f"required package manager not found for {self.name}"
        # shlex.split honours quotes, so "brew install hadolint" stays
        # as two argv entries and a quoted install is preserved.
        import shlex
        argv = shlex.split(cmd)
        try:
            out = subprocess.run(
                argv, capture_output=True, text=True, timeout=300
            )
            if out.returncode != 0:
                return False, f"`{cmd}` failed: {(out.stderr or out.stdout).strip()[:200]}"
        except subprocess.TimeoutExpired:
            return False, f"`{cmd}` timed out after 300s"
        except OSError as e:
            return False, f"`{cmd}` could not run: {e}"
        # Verify it actually got installed.
        if self.is_installed():
            return True, f"installed {self.name}"
        return False, f"`{cmd}` returned 0 but `{self.binary}` is still not on PATH"

    def _check_package_manager(self, cmd: str) -> bool:
        """Check if the required package manager is available."""
        if "brew " in cmd:
            return shutil.which("brew") is not None
        if "npm " in cmd:
            return shutil.which("npm") is not None
        if "pipx " in cmd:
            return shutil.which("pipx") is not None
        if "apt " in cmd:
            return shutil.which("apt") is not None
        return True

    def version(self) -> str | None:
        """Return the installed tool's version string, or None if it
        can't be determined without running a heavyweight command.

        We try ``--version`` first; on failure we try ``version``.
        Anything else (Go tools that print usage, etc.) returns None
        silently — the doctor command just shows ``?``.
        """
        if not self.is_installed():
            return None
        for flag in ("--version", "version"):
            try:
                out = subprocess.run(
                    [self.binary, flag],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
                continue
            if out.returncode == 0 and (out.stdout or out.stderr).strip():
                return (out.stdout or out.stderr).strip().split("\n")[0]
        return None

    def fix_command(self, repo: Path) -> str | None:
        """The exact shell command to run to apply auto-fixes for this
        tool, or None if the tool has no auto-fix mode."""
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} langs={self.languages}>"



_INSTALLERS = {
    "pipx":  "pipx install {pkg}",
    "pip":   "pip install --user {pkg}",
    "npm":   "npm install -g {pkg}",
    "brew":  "brew install {pkg}",
    "apt":   "sudo apt install {pkg}",
}


def build_install_command(installer: str | None, name: str) -> str | None:
    """Render an installer string into a concrete shell command.

    Returns None if the installer kind is unknown or no installer is
    set. ``github:<owner>/<repo>`` returns None because the right
    tarball URL depends on the OS + arch; the user is shown the
    project page instead.
    """
    if not installer:
        return None
    if installer.startswith("github:"):
        # Can't auto-install from GitHub releases — show manual instructions
        return None
    kind, _, pkg = installer.partition(":")
    template = _INSTALLERS.get(kind)
    if template is None:
        return None
    return template.format(pkg=pkg or name)
