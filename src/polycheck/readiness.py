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
from pathlib import Path

from .profiles import PROFILES, is_skipped
from .tools.base import Tool

_PROFILE_ORDER = ("default", "pr", "deep")


def tool_profiles(cls: type[Tool]) -> list[str]:
    """The scan profiles a tool participates in once installed.

    The default scan and the deep profile run everything installed and
    applicable. The pr profile is the fast gate: no Docker/network-heavy
    tools, no structural adapters. Deep-only adapters (coverage) list
    ``deep`` only.
    """
    from .profiles import DEEP_ONLY_TOOLS
    from .verify import HEAVY_TOOLS

    if cls.name in DEEP_ONLY_TOOLS:
        return ["deep"]
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


def profile_plan(
    registry, repo: Path, config=None
) -> dict:
    """Per-profile applicable/ready/missing plan for one repo.

    Joins the tool registry with the repo's detected languages and each
    adapter's own ``is_applicable`` check, then splits by profile: a
    missing tool only counts where its profile would actually run it
    (a heavy tool absent from ``pr`` never blocks a pr gate). Each
    missing entry carries an ``executor`` tag — ``agent`` for
    package-manager installs polycheck can run after user approval,
    ``human`` for the installs policy reserves for the user (apt,
    remote scripts, Docker). 0.3.14: this is the data an agent needs to
    make a profile COMPLETE before running it, instead of discovering
    the gap from a report footer afterwards.
    """
    from .runner import candidate_tools

    candidates = candidate_tools(registry, repo, config)
    plan: dict = {}
    for name in _PROFILE_ORDER:
        spec = PROFILES.get(name)
        applicable = 0
        missing: list[dict] = []
        for cls in candidates:
            if is_skipped(cls, spec):
                continue
            inst = cls(config=config)
            if not _applicable_guard(inst, repo):
                continue
            applicable += 1
            if not inst.is_installed():
                missing.append({
                    "name": inst.name,
                    "install_hint": inst.install_hint(),
                    "executor": "agent" if inst.can_auto_install() else "human",
                })
        plan[name] = {
            "applicable": applicable,
            "ready": applicable - len(missing),
            "missing": missing,
        }
    return plan


def _applicable_guard(inst: Tool, repo: Path) -> bool:
    """``is_applicable`` with an exception guard — a broken adapter
    must not crash doctor (same policy as the CLI's missing-tool check)."""
    try:
        return inst.is_applicable(repo)
    except Exception:  # noqa: BLE001 — readiness checks should not crash
        return True


def readiness(registry, repo: Path | None = None, config=None) -> dict:
    """The full readiness payload for ``doctor --json`` and the MCP server.

    When ``repo`` is given, each tool gains an ``applicable`` flag and
    the payload gains a ``profile_plan`` — the per-profile verdict on
    which applicable tools are ready and which are missing."""
    tools: list[dict] = []
    installed = 0
    candidate_names: set[str] | None = None
    if repo is not None:
        from .runner import candidate_tools

        candidate_names = {
            cls.name for cls in candidate_tools(registry, repo, config)
        }
    for cls in sorted(registry.all(), key=lambda c: c.name):
        inst = cls()
        is_installed = inst.is_installed()
        installed += is_installed
        entry = {
            "name": inst.name,
            "installed": is_installed,
            "version": inst.version() if is_installed else None,
            "install_hint": None if is_installed else inst.install_hint(),
            "auto_installable": inst.can_auto_install(),
            "profiles": tool_profiles(cls),
        }
        if candidate_names is not None:
            entry["applicable"] = inst.name in candidate_names
        tools.append(entry)

    docker = docker_status()
    system_dependencies = [] if docker["status"] == "installed" else [docker]

    payload = {
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
    if repo is not None:
        payload["profile_plan"] = profile_plan(registry, repo, config)
    return payload




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
