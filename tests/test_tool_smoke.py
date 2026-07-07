"""Smoke tests for installed analyzer wrappers.

These tests do not install tools and do not require Docker or network. They
verify that every installed, non-heavy tool can run against the synthetic
repositories created by the verifier without crashing.
"""
from __future__ import annotations

import os
from pathlib import Path

from polycheck.registry import default_registry
from polycheck.verify import verify_tools


def test_installed_tools_do_not_crash_on_synthetic_repos(tmp_path: Path):
    default_registry.discover()
    include_heavy = os.environ.get("POLYCHECK_INCLUDE_HEAVY_TOOLS") == "1"
    results = verify_tools(
        default_registry,
        work_dir=tmp_path,
        include_heavy=include_heavy,
    )
    errors = [result for result in results if result.status == "error"]

    assert errors == []
