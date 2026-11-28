"""hadolint — Dockerfile linter.

hadolint is a single binary; default output is one finding per line
in the same gcc-like format as shellcheck.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool, iter_source_files
from .ghrelease import install_github_release

_HADOLINT_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+)\s*"
    r"(?P<severity>error|warning|info|style):\s*"
    r"(?P<message>.*?)(?:\s*\[(?P<code>[^\]]+)\])?\s*$"
)


class HadolintTool(Tool):
    name = "hadolint"
    category = Category.LINT
    languages = []   # applies to Dockerfiles
    universal = False
    installer = "github-release:hadolint/hadolint"

    def is_applicable(self, repo: Path) -> bool:
        return any(repo.glob("**/Dockerfile*")) or (repo / "Dockerfile").exists()

    def can_auto_install(self) -> bool:
        # Checksums.sha256 ships with every hadolint release, so the
        # verified-or-refused download path applies on Linux.
        return self._asset_slug() is not None

    def _asset_slug(self) -> tuple[str, str] | None:
        import platform

        if platform.system() != "Linux":
            return None
        machine = platform.machine().lower()
        arch = {"x86_64": "x86_64", "aarch64": "arm64"}.get(machine)
        return ("linux", arch) if arch else None

    def install(self) -> tuple[bool, str]:
        if self.is_installed():
            return True, "hadolint is already installed"
        slug = self._asset_slug()
        if slug is None:
            return False, (
                "no verified GitHub-release install for this platform - "
                "install manually: brew install hadolint (macOS) or fetch "
                "a binary from https://github.com/hadolint/hadolint/releases"
            )
        os_slug, arch = slug
        return install_github_release(
            "hadolint/hadolint",
            f"hadolint-{os_slug}-{arch}",
            "checksums.sha256",
            "hadolint",
            Path.home() / ".local" / "bin",
        )

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("hadolint") is None:
            return []
        # Collect project Dockerfiles only; hadolint takes files, not
        # dirs, and node_modules packages ship their own Dockerfiles.
        paths = [
            str(p)
            for p in iter_source_files(
                repo, ("Dockerfile*", "*.dockerfile")
            )
        ]
        if not paths:
            return []
        cmd = ["hadolint", "--no-fail", "--format", "gnu", *self.extra_args()] + paths
        out = subprocess.run(
            cmd, cwd=repo, capture_output=True, text=True, timeout=120
        )
        return self._parse(out.stdout + "\n" + out.stderr)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _HADOLINT_LINE.match(raw.strip())
            if not m:
                continue
            severity = {
                "error": Severity.HIGH,
                "warning": Severity.MEDIUM,
                "info": Severity.LOW,
                "style": Severity.INFO,
            }.get(m.group("severity"), Severity.LOW)
            findings.append(
                Finding(
                    tool="hadolint",
                    rule=m.group("code") or m.group("severity"),
                    severity=severity,
                    category=Category.LINT,
                    message=m.group("message").strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=0,
                    fixable=False,
                    doc_url=f"https://github.com/hadolint/hadolint/wiki/{m.group('code') or ''}",
                    raw={"line": raw},
                )
            )
        return findings
