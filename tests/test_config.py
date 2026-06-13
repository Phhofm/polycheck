"""Tests for the config loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from polycheck.config import Config, ConfigError


def test_defaults(tmp_path: Path):
    cfg = Config.load(tmp_path)
    assert cfg.severity_threshold == "INFO"
    assert cfg.timeout == 300
    assert cfg.enable == []
    assert cfg.disable == []


def test_load_yml(tmp_path: Path):
    (tmp_path / ".polycheck.yml").write_text(textwrap.dedent("""
        enable: [ruff, mypy]
        severity_threshold: MEDIUM
        timeout: 120
        output:
          formats: [json, sarif]
    """))
    cfg = Config.load(tmp_path)
    assert cfg.enable == ["ruff", "mypy"]
    assert cfg.severity_threshold == "MEDIUM"
    assert cfg.timeout == 120
    assert cfg.output.formats == ["json", "sarif"]


def test_load_yaml_alt_name(tmp_path: Path):
    (tmp_path / ".polycheck.yaml").write_text("enable: [ruff]\n")
    cfg = Config.load(tmp_path)
    assert cfg.enable == ["ruff"]


def test_load_toml(tmp_path: Path):
    (tmp_path / ".polycheck.toml").write_text(textwrap.dedent("""
        enable = ["ruff", "mypy"]
        severity_threshold = "HIGH"
    """))
    cfg = Config.load(tmp_path)
    assert cfg.enable == ["ruff", "mypy"]
    assert cfg.severity_threshold == "HIGH"


def test_load_malformed_raises(tmp_path: Path):
    (tmp_path / ".polycheck.yml").write_text(": : :\n  - [unterminated")
    with pytest.raises(ConfigError):
        Config.load(tmp_path)


def test_source_set_on_load(tmp_path: Path):
    p = tmp_path / ".polycheck.yml"
    p.write_text("enable: [ruff]\n")
    cfg = Config.load(tmp_path)
    assert cfg.source == p
