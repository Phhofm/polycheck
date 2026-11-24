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
