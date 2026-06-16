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
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding


class Tool(abc.ABC):
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

    def install_hint(self) -> str:
        """One-line shell command to install the tool. Shown to the user
        via ``polycheck list-tools`` / ``polycheck doctor`` when the
        tool is missing."""
        cmd = build_install_command(self.installer, self.name)
        if cmd is not None:
            return cmd
        # For GitHub releases, show the releases page
        if self.installer and self.installer.startswith("github:"):
            repo_path = self.installer[len("github:"):]
            return f"download from https://github.com/{repo_path}/releases"
        return f"install {self.name} manually (no automatic installer available)"

    def can_auto_install(self) -> bool:
        """Return True if the base installer can install this tool."""
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
            # Check if this is a github: installer to give better message
            if self.installer and self.installer.startswith("github:"):
                repo_path = self.installer[len("github:"):]
                return False, (
                    f"no automatic installer for {self.name}; "
                    f"download from https://github.com/{repo_path}/releases"
                )
            return False, f"no automatic installer for {self.name}; see {self.install_hint()}"
        cmd = build_install_command(self.installer, self.name)
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


# Map from ``installer`` strings to one-line shell commands.
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
