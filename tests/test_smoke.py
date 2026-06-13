"""Smoke test: run polycheck on a real repo (the LUCID project) and
make sure the pipeline doesn't crash end-to-end.

This is a *slow* test (skipped by default). Enable with::

    pytest -m slow

It exists to prove the wiring is right; the unit tests cover the
behavior.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from polycheck.config import Config
from polycheck.runner import Runner

LUCID = Path(os.environ.get("LUCID_PATH", "/home/phips/Documents/GitHub/KiloApp2/kiloapp/lucid"))


@pytest.mark.skipif(not LUCID.exists(), reason="LUCID_PATH not set or repo missing")
def test_run_on_lucid(tmp_path: Path):
    runner = Runner(repo=LUCID, config=Config())
    findings, results = runner.run(parallel=False)
    # At least one tool should have run (ruff, mypy, gitleaks are all
    # in the pipx venv used in the dev environment).
    assert len(results) >= 1, "no tools ran; is your lint venv on PATH?"
    # Every result has a status and a (possibly empty) finding list.
    for r in results:
        assert r.status in ("ok", "no-findings", "error", "timeout", "skipped")
