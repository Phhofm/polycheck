"""actionlint — GitHub Actions workflow linter.

actionlint is a single-binary tool. Default output is a one-line
diagnostic per finding. It exits 1 when findings exist.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool
from .ghrelease import install_github_release

# actionlint output:
#   .github/workflows/ci.yml:10:5: unexpected key "runs" in workflow ... [syntax_check]
_ACTIONLINT_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*"
    r"(?P<message>.*?)(?:\s*\[(?P<code>[^\]]+)\])?\s*$"
)


class ActionlintTool(Tool):
    name = "actionlint"
    category = Category.LINT
    languages = ["github-actions"]  # was [] — the empty list silently
    # excluded actionlint from every run's candidate filter.
    universal = False
    installer = "github-release:rhysd/actionlint"

    def is_applicable(self, repo: Path) -> bool:
        wf = repo / ".github" / "workflows"
        return wf.exists() and any(wf.glob("*.yml")) or any(wf.glob("*.yaml"))

    def can_auto_install(self) -> bool:
        # Every actionlint release ships actionlint_<v>_checksums.txt, so
        # the verified-or-refused download path applies on Linux.
        return self._asset_slug() is not None

    def _asset_slug(self) -> tuple[str, str] | None:
        import platform

        if platform.system() != "Linux":
            return None
        machine = platform.machine().lower()
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
        return ("linux", arch) if arch else None

    def install(self) -> tuple[bool, str]:
        if self.is_installed():
            return True, "actionlint is already installed"
        slug = self._asset_slug()
        if slug is None:
            return False, (
                "no verified GitHub-release install for this platform - "
                "install manually: brew install actionlint (macOS) or fetch "
                "a binary from https://github.com/rhysd/actionlint/releases"
            )
        os_slug, arch = slug
        return install_github_release(
            "rhysd/actionlint",
            "actionlint_{version}_{os}_{arch}.tar.gz",
            "actionlint_{version}_checksums.txt",
            "actionlint",
            Path.home() / ".local" / "bin",
        )

    def run(self, repo: Path) -> list[Finding]:
        if shutil.which("actionlint") is None:
            return []
        out = subprocess.run(
            ["actionlint", "-no-color"],
            cwd=repo, capture_output=True, text=True, timeout=120
        )
        text = out.stdout + "\n" + out.stderr
        return self._parse(text)

    @staticmethod
    def _parse(text: str) -> list[Finding]:
        findings: list[Finding] = []
        for raw in text.splitlines():
            m = _ACTIONLINT_LINE.match(raw.strip())
            if not m:
                continue
            findings.append(
                Finding(
                    tool="actionlint",
                    rule=m.group("code") or "syntax_check",
                    severity=Severity.MEDIUM,
                    category=Category.LINT,
                    message=m.group("message").strip(),
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(m.group("col")),
                    fixable=False,
                    raw={"line": raw},
                )
            )
        return findings
