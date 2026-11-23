"""Consistency guards for facts that live in more than one place."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_changelog_mentions_current_version():
    from polycheck import __version__

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__}" in changelog, (
        f"CHANGELOG.md has no '## {__version__}' section; "
        "bump the changelog together with pyproject.toml"
    )


def test_workflow_templates_have_required_frontmatter():
    """Claude Code skills require YAML frontmatter; the other hosts
    tolerate it, so all templates carry one."""
    from polycheck.workflows import WORKFLOW_TEMPLATES

    for name, template in WORKFLOW_TEMPLATES.items():
        assert template.content.startswith("---"), f"{name} template lacks frontmatter"
        assert "description:" in template.content, f"{name} template lacks description"
