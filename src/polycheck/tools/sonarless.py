"""sonarless — SonarQube analysis via Docker (no server setup required).

Runs a local SonarQube instance in Docker, scans the repo, and queries
the SonarQube API for per-file issues. Covers 30+ languages (bugs,
vulnerabilities, code smells, security hotspots).

Requires Docker to be installed. Skips silently if Docker is absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# SonarQube severity → polycheck severity
_SEVERITY_MAP = {
    "BLOCKER": Severity.CRITICAL,
    "CRITICAL": Severity.HIGH,
    "MAJOR": Severity.MEDIUM,
    "MINOR": Severity.LOW,
    "INFO": Severity.INFO,
}

# SonarQube issue type → polycheck category
_TYPE_MAP = {
    "BUG": Category.SECURITY,
    "VULNERABILITY": Category.SECURITY,
    "SECURITY_HOTSPOT": Category.SECURITY,
    "CODE_SMELL": Category.LINT,
}

# SonarQube issue type → human-readable label for the rule field
_TYPE_LABEL = {
    "BUG": "sonar:bug",
    "VULNERABILITY": "sonar:vulnerability",
    "SECURITY_HOTSPOT": "sonar:hotspot",
    "CODE_SMELL": "sonar:smell",
}

SONAR_PORT = 9234
SONAR_USER = "admin"
SONAR_PASS = "Son@rless123"
SONARLESS_INSTALL_URL = "https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh"


class SonarlessTool(Tool):
    name = "sonarless"
    category = Category.SECURITY
    languages = ["*"]
    universal = True
    installer = "github:gitricko/sonarless"

    def is_applicable(self, repo: Path) -> bool:
        # Always applicable — SonarQube covers every language.
        # But skip if Docker is not available.
        if not _docker_available():
            return False
        return True

    def is_installed(self) -> bool:
        """Check if sonarless CLI is available."""
        return shutil.which("sonarless") is not None

    def install_hint(self) -> str:
        return f"curl -sSL {SONARLESS_INSTALL_URL} | bash"

    def can_auto_install(self) -> bool:
        return _docker_available() and shutil.which("curl") is not None

    def install(self) -> tuple[bool, str]:
        """Install sonarless when Docker is available."""
        if self.is_installed():
            return True, "sonarless is already installed"
        if not _docker_available():
            return False, (
                "Docker is required for sonarless. Ask your LLM coding "
                "assistant to help install Docker for this OS, then rerun polycheck."
            )
        if shutil.which("curl") is None:
            return False, "curl is required to install sonarless"

        cmd = f"curl -sSL {SONARLESS_INSTALL_URL} | bash"
        try:
            result = subprocess.run(
                ["bash", "-lc", cmd],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return False, "sonarless install timed out after 300s"
        except OSError as e:
            return False, f"sonarless install could not run: {e}"

        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()[:300]
            return False, f"sonarless install failed: {output}"
        if self.is_installed():
            return True, "installed sonarless"
        return False, (
            "sonarless install finished, but sonarless was not found on PATH. "
            "Add ~/.sonarless to PATH or create the wrapper script from the README."
        )

    def run(self, repo: Path) -> list[Finding]:
        # 1. Run sonarless scan
        try:
            result = subprocess.run(
                ["sonarless", "scan"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                # scan failed — return empty, runner will report it
                return []
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        # 2. Query SonarQube API for individual issues
        project_name = repo.name
        findings = self._query_issues(project_name)
        return findings

    def _query_issues(self, project_name: str) -> list[Finding]:
        """Query the SonarQube REST API for per-file issues."""
        import requests
        from requests.auth import HTTPBasicAuth

        url = f"http://localhost:{SONAR_PORT}/api/issues/search"  # nosemgrep
        params = {"componentKeys": project_name, "resolved": "false", "ps": "500"}

        try:
            resp = requests.get(url, params=params, auth=HTTPBasicAuth(SONAR_USER, SONAR_PASS), timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            return []

        issues = data.get("issues", [])
        findings: list[Finding] = []

        for issue in issues:
            findings.append(self._parse_issue(issue))

        return findings

    def _parse_issue(self, issue: dict) -> Finding:
        """Parse a single SonarQube issue into a Finding."""
        severity_str = issue.get("severity", "INFO")
        severity = _SEVERITY_MAP.get(severity_str, Severity.INFO)
        issue_type = issue.get("type", "CODE_SMELL")
        category = _TYPE_MAP.get(issue_type, Category.LINT)

        component = issue.get("component", "")
        file_path = component.split(":", 1)[1] if ":" in component else component

        line = issue.get("line")
        if line is not None:
            try:
                line = int(line)
            except (ValueError, TypeError):
                line = None

        rule_key = issue.get("rule", "")
        type_label = _TYPE_LABEL.get(issue_type, "sonar:issue")
        rule = f"{type_label}:{rule_key}" if rule_key else type_label

        message = issue.get("message", "").strip().split("\n")[0]

        return Finding(
            tool=self.name,
            rule=rule,
            severity=severity,
            category=category,
            message=message,
            file=file_path,
            line=line,
            fixable=False,
            doc_url=f"https://rules.sonarsource.com/{issue_type.lower()}/RSPEC-{rule_key.split(':')[0]}/" if rule_key else None,
            raw=issue,
        )

    def fix_command(self, repo: Path) -> str | None:
        return None  # SonarQube issues require manual fixes


def _docker_available() -> bool:
    """Check if Docker is installed and accessible."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
