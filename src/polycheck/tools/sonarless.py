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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..finding import Category, Finding, Severity
from .base import Tool

# SonarQube severity → polycheck severity
# SonarQube runs analyses asynchronously (Compute Engine) — poll for
# the fresh lastAnalysis instead of checking once.
_CE_POLL_INTERVAL_S = 5.0
_CE_POLL_TIMEOUT_S = 120.0

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
        # Removed on purpose: installing by piping a remote script into
        # bash from inside a tool is a supply-chain risk. The hint stays;
        # the user runs it consciously.
        return False

    def install(self) -> tuple[bool, str]:
        """Decline automatic installation with the manual command."""
        if self.is_installed():
            return True, "sonarless is already installed"
        return False, (
            f"no automatic installer for sonarless (manual install recommended); "
            f"run: {self.install_hint()} — Docker is required afterwards"
        )

    def run(self, repo: Path) -> list[Finding]:
        """Scan and query issues — raising instead of reporting clean.

        External live test #7: sonarless printed "SonarQube scanning
        failed!" and exited 0 (the SonarQube Java analyzer aborted on
        Capacitor's uncompiled .java files); polycheck read the empty
        issue list as no-findings. A run whose analysis did not land
        on the SonarQube server must raise, never pass silently.
        """
        scan_started = datetime.now(timezone.utc)
        props_path = repo / "sonar-project.properties"
        created_props = False
        if not props_path.exists():
            # The SonarScanner reads sonar-project.properties when
            # present; without it the Java analyzer aborts on
            # Capacitor's uncompiled .java stubs (and node_modules is
            # scanned wholesale) — external live test #7. Written only
            # when the repo has none, removed after the scan.
            props_path.write_text(
                "sonar.exclusions="
                "**/node_modules/**,**/dist/**,**/build/**,"
                "**/android/**,**/ios/**\n"
                "sonar.sourceEncoding=UTF-8\n",
                encoding="utf-8",
            )
            created_props = True
        try:
            result = subprocess.run(
                ["sonarless", "scan"],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise RuntimeError(f"sonarless scan failed to run: {exc}") from exc
        finally:
            if created_props:
                props_path.unlink(missing_ok=True)
        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 or "scanning failed" in combined.lower():
            detail = combined.strip()[:200] or f"exit {result.returncode}"
            raise RuntimeError(f"sonarless scan failed: {detail}")

        # SonarQube runs the analysis asynchronously on its Compute
        # Engine: lastAnalysis updates only after the CE task finishes,
        # so poll instead of checking once (external live test #7 —
        # a one-shot check read a still-running analysis as "no
        # analysis landed").
        deadline = datetime.now(timezone.utc) + timedelta(
            seconds=_CE_POLL_TIMEOUT_S
        )
        last: str | None = None
        fresh = False
        while datetime.now(timezone.utc) < deadline:
            last = self._analysis_date(repo.name)
            if last:
                parsed = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed >= scan_started - timedelta(minutes=5):
                    fresh = True
                    break
            time.sleep(_CE_POLL_INTERVAL_S)

        if not fresh:
            state = "no analysis landed" if last is None else f"analysis stale ({last})"
            raise RuntimeError(
                "sonarless scan reported success but the SonarQube "
                f"analysis did not complete within {_CE_POLL_TIMEOUT_S}s "
                f"(project '{repo.name}': {state}) — inspect the scan "
                "output above the API call"
            )

        findings = self._query_issues(repo.name)
        return findings

    def _analysis_date(self, project_name: str) -> str | None:
        """The project's analysis timestamp from the SonarQube API.

        Field verified against SonarQube Community Build 26.4:
        `api/navigation/component` returns `analysisDate`, while
        `components/show.lastAnalysis` and `projects/search.lastAnalysis`
        are always null on this build (live test #7 — the reviewer hit
        the same wrong-field trap).
        """
        import requests
        from requests.auth import HTTPBasicAuth

        url = f"http://localhost:{SONAR_PORT}/api/navigation/component"
        try:
            resp = requests.get(
                url,
                params={"component": project_name},
                auth=HTTPBasicAuth(SONAR_USER, SONAR_PASS),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("analysisDate")
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"sonarless: could not read the project's analysis date "
                f"from the SonarQube API: {exc}"
            ) from exc

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
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise RuntimeError(f"sonarless: issues API failed: {exc}") from exc

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
