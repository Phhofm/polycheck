"""gitleaks — find secrets in the working tree.

We run ``gitleaks detect --no-git`` which scans the working tree only
(faster, no clone dependency), writing its JSON report to a temp file
via ``--report-path`` (stdout behavior differs between gitleaks
versions). gitleaks exits 1 when leaks are found; that's normal.

A generated config allowlist excludes polycheck's own artifacts
(``polycheck-reports/``, ``.polycheck/``) plus vendored/build dirs —
without it, gitleaks re-scans our report files and flags finding texts
from the previous run (self-referential noise).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import EXCLUDED_DIRS, Tool

_ALLOWLIST = "\n".join(
    f"    '''{re.escape(d)}/'''," for d in sorted(EXCLUDED_DIRS)
)

_CONFIG = (
    # --config REPLACES gitleaks' default ruleset; extend it so our
    # allowlist applies on top of the standard rules.
    "[extend]\n"
    "useDefault = true\n\n"
    "[allowlist]\n"
    '  description = "polycheck internal and vendored exclusions"\n'
    "  paths = [\n"
    f"{_ALLOWLIST}\n"
    "  ]\n"
)


def _config_with_ignores(repo: Path) -> str:
    """The exclusion config plus the repo's gitignored paths. Gitignored
    artifacts (build outputs, traces with throwaway tokens, backups)
    cannot enter the repo via push, so they stay out of the scan."""
    ignored = _ignored_paths(repo)
    extra = "\n".join(
        # re.escape also escapes '-', which breaks literal matching on
        # names like "test-results" — outside character classes the
        # hyphen is a plain literal, so un-escape it.
        f"    '''^{re.escape(p).replace(chr(92) + '-', '-')}(/.*)?$''',"
        for p in ignored if p
    )
    paths_block = f"{_ALLOWLIST}\n{extra}\n" if extra else _ALLOWLIST
    return (
        "[extend]\n"
        "useDefault = true\n\n"
        "[allowlist]\n"
        '  description = "polycheck internal, vendored, and gitignored exclusions"\n'
        "  paths = [\n"
        f"{paths_block}"
        "  ]\n"
    )


def _ignored_paths(repo: Path) -> list[str]:
    """Gitignored paths of the repo, collapsed to directories where
    possible (``git ls-files -o -i --exclude-standard --directory``).
    Non-git repos return nothing."""
    if not (repo / ".git").exists():
        return []
    try:
        out = subprocess.run(
            ["git", "ls-files", "-o", "-i", "--exclude-standard", "--directory"],
            cwd=repo, capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return []
        return [line.rstrip("/") for line in out.stdout.splitlines() if line]
    except (subprocess.TimeoutExpired, OSError):
        return []


class GitleaksTool(Tool):
    name = "gitleaks"
    category = Category.SECRETS
    languages = []            # applies to any git repo
    universal = True
    installer = "github-release:gitleaks/gitleaks"

    def can_auto_install(self) -> bool:
        # gitleaks releases ship gitleaks_<v>_checksums.txt, so the
        # verified-or-refused download path applies on Linux.
        return self._asset_slug() is not None

    def _asset_slug(self) -> tuple[str, str] | None:
        import platform

        if platform.system() != "Linux":
            return None
        machine = platform.machine().lower()
        arch = {"x86_64": "x64", "aarch64": "arm64"}.get(machine)
        return ("linux", arch) if arch else None

    def install(self) -> tuple[bool, str]:
        if self.is_installed():
            return True, "gitleaks is already installed"
        slug = self._asset_slug()
        if slug is None:
            return False, (
                "no verified GitHub-release install for this platform - "
                "install manually: brew install gitleaks (macOS) or fetch "
                "a binary from https://github.com/gitleaks/gitleaks/releases"
            )
        os_slug, arch = slug
        from .ghrelease import install_github_release

        return install_github_release(
            "gitleaks/gitleaks",
            "gitleaks_{version}_{os}_{arch}.tar.gz",
            "gitleaks_{version}_checksums.txt",
            "gitleaks",
            Path.home() / ".local" / "bin",
        )

    def is_applicable(self, repo: Path) -> bool:
        return (repo / ".git").exists() or (repo / ".git").is_dir()

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("gitleaks") is None:
            return []
        with tempfile.TemporaryDirectory(prefix="polycheck-gitleaks-") as tmp_name:
            report_path = Path(tmp_name) / "gitleaks-report.json"
            config_path = Path(tmp_name) / "gitleaks.toml"
            config_path.write_text(_config_with_ignores(repo), encoding="utf-8")
            cmd = [
                "gitleaks", "detect",
                "--config", str(config_path),
                "--report-format", "json",
                "--report-path", str(report_path),
                "--no-banner",
                "--no-git",
                *self.extra_args(),
                # Relative source: gitleaks then reports repo-relative
                # file paths, which (a) match the relative-anchored
                # gitignore allowlist and (b) keep fingerprints and
                # track buckets portable (absolute paths broke both —
                # live test #6: 1408 CRITICALs from ignored build
                # assets flooding the report, tracked files bucketed
                # untracked).
                "--source", ".",
            ]
            out = subprocess.run(
                cmd, cwd=repo, capture_output=True, text=True, timeout=300
            )
            # Exit 1 = leaks found, 0 = clean. Anything else is a real
            # failure — surface it so the runner reports an error instead
            # of silently reporting "no findings".
            if out.returncode not in (0, 1):
                detail = (out.stderr or out.stdout).strip()[:200]
                raise RuntimeError(f"gitleaks exited {out.returncode}: {detail}")
            if not report_path.exists():
                return []
            try:
                data = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
            if not isinstance(data, list):
                return []

        findings: list[Finding] = []
        for item in data:
            findings.append(
                Finding(
                    tool=self.name,
                    rule=item.get("RuleID", "secret"),
                    severity=Severity.CRITICAL,   # any secret is critical
                    category=Category.SECRETS,
                    message=item.get("Description") or item.get("Match", "")[:120],
                    file=item.get("File"),
                    line=item.get("StartLine"),
                    column=item.get("StartColumn"),
                    fixable=False,
                    doc_url="https://github.com/gitleaks/gitleaks#rules",
                    raw=item,
                )
            )
        return findings
