"""Tests for the machine-readable LLM readiness surface (0.3.6).

polycheck is designed to be driven by LLM coding assistants (vibecode
skills, /polycheck workflows). The readiness surface answers, in one
structured payload, what an agent needs to know BEFORE its first full
scan: which tools exist and which profiles they participate in, the
system prerequisites (sonarless runs the SonarQube engine in a Docker
container managed by the sonarless CLI), profile guidance, and the
install policy.
"""
from __future__ import annotations

import json
import subprocess

from typer.testing import CliRunner

from polycheck.finding import Category
from polycheck.registry import ToolRegistry
from polycheck.tools.base import Tool


class _FastTool(Tool):
    name = "fast-stub"
    category = Category.LINT
    languages = []
    universal = True

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return []


class _HeavyTool(_FastTool):
    name = "pip-audit"  # a HEAVY_TOOLS name


class _StructuralTool(_FastTool):
    name = "tach"
    structural = True


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    for cls in (_FastTool, _HeavyTool, _StructuralTool):
        reg.register(cls)
    return reg


# --- tool_profiles -----------------------------------------------------------


def test_tool_profiles_fast_tool_runs_in_every_profile():
    from polycheck.readiness import tool_profiles

    assert tool_profiles(_FastTool) == ["default", "pr", "deep"]


def test_tool_profiles_heavy_and_structural_skip_pr():
    from polycheck.readiness import tool_profiles

    assert tool_profiles(_HeavyTool) == ["default", "deep"]
    assert tool_profiles(_StructuralTool) == ["default", "deep"]


# --- docker_status ------------------------------------------------------------


def test_docker_status_states(monkeypatch):
    from polycheck import readiness

    def run_ok(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0)

    def run_fail(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(
        readiness.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )
    monkeypatch.setattr(readiness.subprocess, "run", run_ok)
    assert readiness.docker_status()["status"] == "installed"

    monkeypatch.setattr(readiness.subprocess, "run", run_fail)
    assert readiness.docker_status()["status"] == "exists but not running"

    monkeypatch.setattr(
        readiness.shutil, "which", lambda name: None
    )
    assert readiness.docker_status()["status"] == "not-installed"

    # The docker block always names its consumer.
    assert "sonarless" in readiness.docker_status()["needed_for"]


# --- profile_guidance ----------------------------------------------------------


def test_profile_guidance_covers_all_three_modes():
    from polycheck.profiles import PROFILES
    from polycheck.readiness import profile_guidance

    guidance = profile_guidance()

    assert set(guidance) == {"default", *PROFILES}
    # Agents must learn the deep profile pulls the heavy tools and the
    # sonarless/Docker requirement.
    assert "heavy" in guidance["deep"]
    assert "changed" in guidance["pr"]


# --- readiness payload ----------------------------------------------------------


def test_readiness_payload_shape(monkeypatch):
    from polycheck import readiness

    monkeypatch.setattr(readiness.shutil, "which", lambda name: None)
    payload = readiness.readiness(_registry())

    by_name = {t["name"]: t for t in payload["tools"]}
    assert by_name["fast-stub"]["installed"] is True
    assert by_name["fast-stub"]["profiles"] == ["default", "pr", "deep"]
    assert by_name["pip-audit"]["profiles"] == ["default", "deep"]

    docker = [d for d in payload["system_dependencies"] if d["name"] == "docker"]
    assert docker and "sonarless" in docker[0]["needed_for"]

    assert set(payload["profile_guidance"]) == {"default", "pr", "deep"}
    assert payload["summary"]["installed"] == 3
    assert payload["install_policy"]["never"]  # the no-curl|bash rule


def test_missing_tool_carries_install_hint_and_risk(monkeypatch):
    from polycheck import readiness

    class _Missing(_FastTool):
        name = "missing-stub"

        def is_installed(self):
            return False

    reg = ToolRegistry()
    reg.register(_Missing)
    payload = readiness.readiness(reg)

    entry = payload["tools"][0]
    assert entry["installed"] is False
    assert entry["install_hint"]
    assert payload["summary"]["missing"] == 1


# --- doctor --json ---------------------------------------------------------------


def test_doctor_json_is_machine_readable(monkeypatch):
    from polycheck.cli import app

    reg = _registry()
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {t["name"] for t in payload["tools"]} == {
        "fast-stub", "pip-audit", "tach",
    }
    assert payload["profile_guidance"]["deep"]


def test_doctor_json_fail_on_missing_exits_nonzero(monkeypatch):
    from polycheck.cli import app

    reg = ToolRegistry()

    class _Missing(_FastTool):
        name = "missing-stub"

        def is_installed(self):
            return False

    reg.register(_Missing)
    monkeypatch.setattr("polycheck.cli.default_registry", reg)

    result = CliRunner().invoke(app, ["doctor", "--json", "--fail-on-missing"])

    assert result.exit_code == 1


def test_doctor_json_embeds_skill_block(monkeypatch):
    """External live test: an agent drove polycheck purely via
    doctor --json + polycheck://setup. The readiness payload now points
    straight at the full skill so every host reaches it in one hop."""
    from polycheck import readiness

    payload = readiness.readiness(_registry())

    skill = payload["skill"]
    assert skill["resource"] == "polycheck://setup"
    assert skill["url"].endswith("polycheck-skill.md")
    assert "SKILL.md" in skill["install_hint"]
