"""Machine-readable readiness and setup guidance for LLM agents.

polycheck is designed to be driven by LLM coding assistants (vibecode
skills, /polycheck workflows). This module is the single source that
both the CLI (``polycheck doctor --json``) and the MCP server read, so
an agent learns BEFORE its first full run:

  * which tools exist, which are installed, and which scan profiles
    each tool participates in;
  * the system prerequisites — sonarless runs the SonarQube engine in a
    Docker container that the sonarless CLI manages (start, web UI on
    port 9234, ``sonarless docker-clean`` to remove it);
  * what the scan profiles mean and when to use them;
  * the install policy: what polycheck installs automatically (after
    the user approves), and what it never does itself.
"""
from __future__ import annotations

import shutil
import subprocess

from .profiles import PROFILES
from .tools.base import Tool

_PROFILE_ORDER = ("default", "pr", "deep")


def tool_profiles(cls: type[Tool]) -> list[str]:
    """The scan profiles a tool participates in once installed.

    The default scan and the deep profile run everything installed and
    applicable. The pr profile is the fast gate: no Docker/network-heavy
    tools, no structural adapters.
    """
    from .verify import HEAVY_TOOLS

    heavy_or_structural = (
        cls.name in HEAVY_TOOLS or getattr(cls, "structural", False)
    )
    if heavy_or_structural:
        return ["default", "deep"]
    return list(_PROFILE_ORDER)


def profile_guidance() -> dict[str, str]:
    """Compact profile help for agents — name → one-line description."""
    guidance = {
        "default": "whole-repo fast scan, MEDIUM gate — the everyday scan",
    }
    guidance.update(
        {name: spec.description for name, spec in PROFILES.items()}
    )
    return {name: guidance[name] for name in _PROFILE_ORDER}


def docker_status() -> dict:
    """Docker presence and daemon health.

    sonarless needs Docker: it runs a local SonarQube server in a
    container it manages itself — no separate server setup — and polycheck
    reads the SonarQube API for per-file issues.
    """
    docker_present = shutil.which("docker") is not None
    docker_running = False
    if docker_present:
        try:
            out = subprocess.run(
                ["docker", "info"], capture_output=True, timeout=5
            )
            docker_running = out.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            pass

    if docker_running:
        status = "installed"
    elif docker_present:
        status = "exists but not running"
    else:
        status = "not-installed"

    note = "" if docker_running else (
        "Docker is needed for sonarless (SonarQube analysis). "
        "Install Docker: https://docs.docker.com/get-docker/"
    )
    return {
        "name": "docker",
        "kind": "system",
        "status": status,
        "needed_for": ["sonarless"],
        "note": note,
    }


INSTALL_POLICY: dict[str, str] = {
    "auto_install": (
        "analyzers marked auto-installable are installed via pipx/npm "
        "AFTER the user approves (polycheck install, or the MCP guided "
        "flow with install_mode=tools_only)"
    ),
    "ask_first": (
        "the guided flow always returns needs_user_input before any "
        "install — never install without asking"
    ),
    "never": (
        "polycheck never pipes remote scripts into a shell (sonarless is "
        "a manual `curl -sSL … | bash` the USER runs consciously) and "
        "never installs Docker itself — propose the official installer "
        "and let the user do it"
    ),
}


def readiness(registry) -> dict:
    """The full readiness payload for ``doctor --json`` and the MCP server."""
    tools: list[dict] = []
    installed = 0
    for cls in sorted(registry.all(), key=lambda c: c.name):
        inst = cls()
        is_installed = inst.is_installed()
        installed += is_installed
        tools.append({
            "name": inst.name,
            "installed": is_installed,
            "version": inst.version() if is_installed else None,
            "install_hint": None if is_installed else inst.install_hint(),
            "auto_installable": inst.can_auto_install(),
            "profiles": tool_profiles(cls),
        })

    docker = docker_status()
    system_dependencies = [] if docker["status"] == "installed" else [docker]

    return {
        "tools": tools,
        "system_dependencies": system_dependencies,
        "profile_guidance": profile_guidance(),
        "install_policy": INSTALL_POLICY,
        "summary": {
            "installed": installed,
            "missing": len(tools) - installed,
        },
        "skill": {
            "resource": "polycheck://setup",
            "url": (
                "https://raw.githubusercontent.com/Phhofm/polycheck/"
                "main/polycheck-skill.md"
            ),
            "install_hint": (
                "mkdir -p ~/.kilo/skills/polycheck && curl -fsSL "
                "https://raw.githubusercontent.com/Phhofm/polycheck/main/"
                "polycheck-skill.md -o ~/.kilo/skills/polycheck/SKILL.md"
            ),
        },
    }




def _setup_guide() -> str:
    guidance = "\n".join(
        f"  * **{name}** — {text}" for name, text in profile_guidance().items()
    )
    policy = "\n".join(
        f"  * **{key}**: {text}" for key, text in INSTALL_POLICY.items()
    )
    return f"""\
# polycheck — setup and operations guide for LLM coding assistants

polycheck runs the applicable static analyzers on a repository and
writes LLM-friendly reports (`polycheck-reports/polycheck-report.md`).
Two MCP tools: `polycheck.run` (guided) and `polycheck.audit_run`
(low-level). CLI equivalent: `polycheck run .`.

## Readiness check first

Run `polycheck doctor --json` before the first scan: it lists every
bundled analyzer with `installed`, `install_hint`, `auto_installable`,
and the scan `profiles` it participates in, plus system prerequisites
and the install policy.

## Scan profiles

{guidance}

`polycheck init --git-hook pre-push` installs a pre-push gate that runs
the pr profile automatically.

## System prerequisites

* **sonarless** (SonarQube: bugs, vulnerabilities, code smells across
  30+ languages) is the one tool that needs **Docker**: it starts a
  local SonarQube server in a Docker container that the sonarless CLI
  manages itself (web UI on port 9234, `sonarless docker-clean` to
  remove the container afterwards). No separate server setup. If Docker
  is missing, propose the official Docker installer to the user and
  continue without sonarless — the scan stays useful without it.
* sonarless itself is a manual install by design
  (`curl -sSL https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash`
  — the USER runs this consciously). Installing it is the opt-in.

## Install policy

{policy}

## The daily loop

1. `polycheck run .` (or the MCP `polycheck.run`) — reports land in
   `polycheck-reports/`.
2. Triage the markdown report (REAL BUG / REAL SMELL / FALSE POSITIVE /
   DEFERRED) — ideally via the `polycheck-reviewer` subagent written by
   `polycheck init`.
3. FALSE POSITIVES → `suppress:` in `.polycheck.yml` (durable).
4. `polycheck baseline` once the repo is at an accepted state; later
   runs with `diff: true` report only NEW findings.
5. Verify analyzer wrappers after changes: `polycheck verify-tools`.
"""


SETUP_GUIDE: str = _setup_guide()
