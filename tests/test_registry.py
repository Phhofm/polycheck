"""Tests for the tool registry."""
from __future__ import annotations

from polycheck.finding import Category
from polycheck.registry import ToolRegistry
from polycheck.tools.base import Tool


class _FakeTool(Tool):
    name = "fake"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def run(self, repo):
        return []


class _UniversalTool(Tool):
    name = "everywhere"
    category = Category.LINT
    languages = []
    universal = True

    def is_applicable(self, repo):
        return True

    def run(self, repo):
        return []


def test_register_and_lookup():
    reg = ToolRegistry()
    reg.register(_FakeTool)
    assert reg.get("fake") is _FakeTool
    assert "fake" in [cls.name for cls in reg.all()]


def test_universal_always_in_for_language():
    reg = ToolRegistry()
    reg.register(_UniversalTool)
    reg.register(_FakeTool)
    py = reg.for_language("python")
    assert _UniversalTool in py
    assert _FakeTool in py
    go = reg.for_language("go")
    assert _UniversalTool in go
    assert _FakeTool not in go


def test_discover_picks_up_real_tools():
    # The default registry auto-discovers via pkgutil. At least the
    # 5 Python tools we ship should be there.
    from polycheck.registry import default_registry
    default_registry.discover()
    names = {cls.name for cls in default_registry.all()}
    for expected in ("ruff", "mypy", "vulture", "pip-audit", "deptry", "gitleaks"):
        assert expected in names, f"missing tool: {expected}"


def test_applicable_filters_by_installed():
    # _FakeTool.is_installed defaults to True (the base class checks
    # shutil.which on the binary named after self.name).
    reg = ToolRegistry()
    reg.register(_FakeTool)
    # The fake tool's "is_installed" probes "fake" on PATH, which
    # almost certainly doesn't exist; it should be filtered out.
    from pathlib import Path
    applicable = reg.applicable(Path("."))
    assert _FakeTool not in applicable
