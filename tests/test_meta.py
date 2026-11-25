"""Consistency guards for facts that live in more than one place."""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_version_is_consistent_across_pyproject_init_and_changelog():
    import polycheck

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    version = pyproject["project"]["version"]
    assert polycheck.__version__ == version, (
        "src/polycheck/__init__.py __version__ and pyproject.toml version "
        "must match (the published wheel and `polycheck --version` disagree otherwise)"
    )
    assert f"## {version}" in changelog, (
        f"CHANGELOG.md has no '## {version}' section; "
        "bump the changelog together with pyproject.toml"
    )


def test_workflow_templates_have_required_frontmatter():
    """Claude Code skills require YAML frontmatter; the other hosts
    tolerate it, so all templates carry one."""
    from polycheck.workflows import WORKFLOW_TEMPLATES

    for name, template in WORKFLOW_TEMPLATES.items():
        assert template.content.startswith("---"), f"{name} template lacks frontmatter"
        assert "description:" in template.content, f"{name} template lacks description"


def test_agent_templates_have_required_frontmatter_and_contract():
    """Reviewer agents must be subagent-scoped and carry the checklist
    contract so the main chat stays clean."""
    from polycheck.workflows import AGENT_TEMPLATES

    for name, template in AGENT_TEMPLATES.items():
        assert template.content.startswith("---"), f"{name} agent lacks frontmatter"
        assert "description:" in template.content, f"{name} agent lacks description"
        assert "polycheck-review-checklist.md" in template.content, (
            f"{name} agent does not write the checklist artifact"
        )
        assert "mode: subagent" in template.content or "tools:" in template.content, (
            f"{name} agent is not scoped as a subagent"
        )
        # The return contract keeps the main chat clean.
        assert "Nothing else" in template.content
        assert "REAL BUG" in template.content and "FALSE POSITIVE" in template.content


def test_agent_template_has_action_quality_rules():
    """From the bigger-repo live test: invented config values (wrong key,
    wrong unit, wrong ecosystem) and actions contradicting the cited code
    must be structurally prevented."""
    from polycheck.workflows import AGENT_TEMPLATES

    for name, template in AGENT_TEMPLATES.items():
        body = template.content
        assert "doc-verified" in body, f"{name}: no doc-verification rule"
        assert "applicability" in body, f"{name}: no applicability-condition rule"
        assert "cited lines" in body, f"{name}: no read-cited-lines rule"
        assert "Coverage gaps" in body, f"{name}: return format lacks coverage line"


def test_workflow_templates_mention_profile_modes():
    """0.3.4: /polycheck gains a mode argument — default dev scan,
    deep on onboarding, pr for pre-push gates."""
    from polycheck.workflows import _SHARED_STEPS

    assert "profile" in _SHARED_STEPS
    assert "deep" in _SHARED_STEPS
    assert "pr" in _SHARED_STEPS


def test_workflow_templates_mention_readiness_preflight():
    """0.3.6: before the first deep run, the agent checks readiness and
    proposes prerequisites — sonarless needs Docker, and polycheck never
    installs Docker or pipes remote scripts itself."""
    from polycheck.workflows import _SHARED_STEPS

    assert "doctor --json" in _SHARED_STEPS
    assert "Docker" in _SHARED_STEPS and "sonarless" in _SHARED_STEPS


def test_agent_templates_carry_quality_questions_section():
    """The deep profile adds questions the static tools cannot answer —
    as checklist QUESTIONS, never fabricated findings."""
    from polycheck.workflows import AGENT_TEMPLATES

    anchors = ("Quality questions", "SRP", "Law of Demeter", "deep profile")
    for name, template in AGENT_TEMPLATES.items():
        body = template.content
        for anchor in anchors:
            assert anchor in body, f"{name}: missing '{anchor}'"
        assert "never" in body and "findings" in body, (
            f"{name}: quality questions must not become fabricated findings"
        )
