"""Configuration loader.

The user can drop a ``.polycheck.yml`` or ``.polycheck.toml`` at the
repo root. The file is optional — sensible defaults are used otherwise.

Example ``.polycheck.yml``:

    enable:
      - ruff
      - mypy
      - gitleaks
    disable:
      - pylint
    severity_threshold: LOW
    timeout: 600
    output:
      - markdown
      - json
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class OutputConfig:
    formats: list[str] = field(default_factory=lambda: ["markdown", "json"])
    report_dir: str = "polycheck-reports"


@dataclass
class Config:
    """User-tunable configuration. Loaded from ``.polycheck.yml``.

    All fields are optional; the defaults are sensible for most repos.
    """

    enable: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)
    severity_threshold: str = "INFO"   # minimum severity to keep
    timeout: int = 300                 # per-tool seconds
    output: OutputConfig = field(default_factory=OutputConfig)
    extra_args: dict[str, list[str]] = field(default_factory=dict)
    source: Path | None = None         # path to the file the config was loaded from

    @classmethod
    def load(cls, repo: Path) -> Config:
        """Look for ``.polycheck.yml`` / ``.polycheck.toml`` at ``repo``;
        return a Config. Missing file → defaults. Malformed file →
        raise ``ConfigError`` with the parser error."""
        repo = Path(repo).resolve()
        for name in (".polycheck.yml", ".polycheck.yaml", ".polycheck.toml"):
            path = repo / name
            if path.exists():
                return cls._parse(path)
        return cls()

    @classmethod
    def _parse(cls, path: Path) -> Config:
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".toml":
                # Lazy import: tomli/tomllib are stdlib in 3.11+, but we
                # support 3.10 via the tomli backport.
                try:
                    import tomllib  # py311+
                except ImportError:
                    import tomli as tomllib
                data: dict[str, Any] = tomllib.loads(text)
            else:
                data = yaml.safe_load(text) or {}
        except (yaml.YAMLError, ValueError) as e:
            raise ConfigError(f"Could not parse {path}: {e}") from e

        cfg = cls()
        cfg.source = path
        if "enable" in data:
            cfg.enable = list(data["enable"])
        if "disable" in data:
            cfg.disable = list(data["disable"])
        if "severity_threshold" in data:
            cfg.severity_threshold = str(data["severity_threshold"]).upper()
        if "timeout" in data:
            cfg.timeout = int(data["timeout"])
        if "extra_args" in data and isinstance(data["extra_args"], dict):
            cfg.extra_args = {
                str(k): list(v) if isinstance(v, list) else [str(v)]
                for k, v in data["extra_args"].items()
            }
        if "output" in data and isinstance(data["output"], dict):
            out = data["output"]
            if "formats" in out:
                cfg.output.formats = list(out["formats"])
            if "report_dir" in out:
                cfg.output.report_dir = str(out["report_dir"])
        return cfg


class ConfigError(Exception):
    """Raised when a config file is malformed."""
