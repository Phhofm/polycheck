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
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from ..finding import Category, Finding

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

    Walks the repo with pruning (excluded directories are never entered)
    and matches ``patterns`` with pathlib semantics, so both basename
    globs (``*.sh``) and dir-anchored patterns (``.github/workflows/*.yml``)
    work.
    """
    repo = Path(repo)
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
        base = Path(root).relative_to(repo)
        for name in sorted(files):
            rel = base / name if str(base) != "." else Path(name)
            rel_posix = PurePosixPath(rel.as_posix())
            if any(rel_posix.match(pattern) for pattern in patterns):
                yield rel


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
        if self.installer and self.installer.startswith("github-release:"):
            return f"auto-install {self.name} from the latest GitHub release"
        # For GitHub releases, show the releases page
        if self.installer and self.installer.startswith("github:"):
            repo_path = self.installer[len("github:"):]
            return f"download from https://github.com/{repo_path}/releases"
        return f"install {self.name} manually (no automatic installer available)"

    def can_auto_install(self) -> bool:
        """Return True if the base installer can install this tool."""
        if self.installer and self.installer.startswith("github-release:"):
            return _github_release_supported(self.installer)
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
        if self.installer and self.installer.startswith("github-release:"):
            return _install_github_release(self.installer, self.binary)
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


def _github_release_supported(installer: str) -> bool:
    """Return True if an OS/arch asset is known for this GitHub release."""
    repo = installer.removeprefix("github-release:")
    return _github_release_asset(repo, "0.0.0", platform.system(), platform.machine()) is not None


def _install_github_release(installer: str, binary: str) -> tuple[bool, str]:
    """Install a binary from the latest GitHub release for the current OS/arch."""
    repo = installer.removeprefix("github-release:")
    version, assets, fetch_error = _latest_github_release_assets(repo)
    if version is None:
        return False, f"could not fetch latest release for {repo}: {fetch_error}"

    asset_name = _github_release_asset(repo, version, platform.system(), platform.machine())
    if asset_name is None:
        return False, f"no release asset for {repo} on {platform.system()} {platform.machine()}"

    asset_url = next(
        (asset.get("browser_download_url") for asset in assets if asset.get("name") == asset_name),
        None,
    )
    if not asset_url:
        return False, f"release asset not found for {repo}: {asset_name}"

    try:
        target = _download_and_install_asset(asset_url, binary)
    except (OSError, tarfile.TarError, zipfile.BadZipFile, KeyError) as exc:
        return False, f"failed to install {binary} from {repo}: {exc}"

    path_note = ""
    if str(target.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        path_note = f" Add {target.parent} to PATH."
    return True, f"installed {binary} to {target}.{path_note}"


def _latest_github_release_assets(
    repo: str,
) -> tuple[str | None, list[dict[str, Any]], str]:
    """Fetch the latest release tag and asset metadata from GitHub.

    Returns ``(tag, assets, error)``; ``tag`` is None when the fetch
    failed and ``error`` carries the reason.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "polycheck",
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        return None, [], str(exc)
    if response.status_code != 200:
        return None, [], f"HTTP {response.status_code}: {response.text[:200]}"
    try:
        data = response.json()
    except ValueError as exc:
        return None, [], str(exc)
    tag = data.get("tag_name") or data.get("name")
    if not tag:
        return None, [], "release missing tag_name"
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        return None, [], "release assets missing"
    return tag.lstrip("v"), assets, ""


def _download_and_install_asset(asset_url: str, binary: str) -> Path:
    """Download a release asset, extract the binary, and install it."""
    asset_name = Path(asset_url).name
    suffix = "".join(Path(asset_name).suffixes)
    with tempfile.TemporaryDirectory(prefix="polycheck-github-release-") as tmp_name:
        tmp = Path(tmp_name)
        archive = tmp / asset_name
        _download_file(asset_url, archive)

        if suffix and (suffix.endswith(".zip") or suffix.endswith((".tar.gz", ".tgz", ".tar.xz"))):
            extract_dir = tmp / "extract"
            extract_dir.mkdir()
            if suffix.endswith(".zip"):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(extract_dir)
            else:
                with tarfile.open(archive, "r:*") as tf:
                    tf.extractall(extract_dir)
            source = _find_extracted_binary(extract_dir, binary)
        else:
            source = archive
        target_dir = _writable_install_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{binary}.exe" if platform.system() == "windows" else binary
        target = target_dir / target_name
        target.write_bytes(source.read_bytes())
        target.chmod(0o755)
        return target


def _download_file(url: str, path: Path) -> None:
    """Download a file using requests with a streaming response."""
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)


def _find_extracted_binary(root: Path, binary: str) -> Path:
    """Find the extracted binary file inside an archive."""
    names = {binary, f"{binary}.exe"}
    matches = [path for path in root.rglob("*") if path.is_file() and path.name in names]
    if matches:
        return sorted(matches, key=lambda p: len(p.parts))[0]
    raise FileNotFoundError(f"could not find {binary} in extracted archive")


def _writable_install_dir() -> Path:
    """Return a writable directory that is likely on PATH."""
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if not raw:
            continue
        path = Path(raw)
        if path.exists() and os.access(path, os.W_OK):
            return path
    return Path.home() / ".local" / "bin"


def _github_release_asset(
    repo: str,
    version: str,
    system: str,
    machine: str,
) -> str | None:
    """Return the expected GitHub release asset name for a repo/platform."""
    system = system.lower()
    arch = _normalize_arch(machine)
    if repo == "gitleaks/gitleaks":
        return _gitleaks_asset(version, system, arch)
    if repo == "rhysd/actionlint":
        return _actionlint_asset(version, system, arch)
    if repo == "hadolint/hadolint":
        return _hadolint_asset(version, system, arch)
    if repo == "koalaman/shellcheck":
        return _shellcheck_asset(version, system, arch)
    return None


def _normalize_arch(machine: str) -> str:
    """Normalize Python platform.machine() values."""
    machine = machine.lower()
    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine


def _gitleaks_asset(version: str, system: str, arch: str) -> str | None:
    if system == "windows":
        return f"gitleaks_{version}_windows_x64.zip" if arch == "x64" else None
    if system in {"linux", "darwin"}:
        suffix = "x64" if arch == "x64" else "arm64" if arch == "arm64" else None
        if suffix:
            return f"gitleaks_{version}_{system}_{suffix}.tar.gz"
    return None


def _actionlint_asset(version: str, system: str, arch: str) -> str | None:
    if system == "windows":
        return f"actionlint_{version}_windows_amd64.zip" if arch == "x64" else None
    if system in {"linux", "darwin"}:
        suffix = "amd64" if arch == "x64" else "arm64" if arch == "arm64" else None
        if suffix:
            return f"actionlint_{version}_{system}_{suffix}.tar.gz"
    return None


def _hadolint_asset(version: str, system: str, arch: str) -> str | None:
    suffix = "x86_64" if arch == "x64" else "arm64" if arch == "arm64" else None
    if not suffix:
        return None
    if system == "windows":
        return f"hadolint-windows-{suffix}.exe"
    if system == "darwin":
        return f"hadolint-macos-{suffix}"
    if system == "linux":
        return f"hadolint-linux-{suffix}"
    return None


def _shellcheck_asset(version: str, system: str, arch: str) -> str | None:
    if system == "windows":
        return f"shellcheck-v{version}.zip" if arch == "x64" else None
    if system == "darwin":
        suffix = "x86_64" if arch == "x64" else "aarch64" if arch == "arm64" else None
        if suffix:
            return f"shellcheck-v{version}.darwin.{suffix}.tar.xz"
    if system == "linux":
        suffix = "x86_64" if arch == "x64" else "aarch64" if arch == "arm64" else None
        if suffix:
            return f"shellcheck-v{version}.linux.{suffix}.tar.xz"
    return None


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
