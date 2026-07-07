"""Heavy smoke tests for installed analyzer wrappers.

Run explicitly with:

    pytest -m heavy

These tests include Docker/network-heavy tools and are intentionally excluded
from the default test run.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polycheck.registry import default_registry
from polycheck.verify import verify_tools

pytestmark = pytest.mark.heavy


def test_all_supported_tools_work_with_heavy_tools_enabled(tmp_path: Path):
    default_registry.discover()
    results = verify_tools(default_registry, work_dir=tmp_path, include_heavy=True)
    errors = [result for result in results if result.status == "error"]
    verified_tools = {result.tool for result in results}
    registered_tools = {cls.name for cls in default_registry.all()}

    assert verified_tools == registered_tools
    assert errors == []
