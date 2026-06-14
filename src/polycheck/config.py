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
        data = cls._read_config_file(path)
        cfg = cls()
        cfg.source = path
        cfg._apply_dict(data)
        return cfg

    @staticmethod
    def _read_config_file(path: Path) -> dict[str, Any]:
        """Read and parse a config file (YAML or TOML)."""
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".toml":
                return cls._parse_toml(text)
            return yaml.safe_load(text) or {}
        except (yaml.YAMLError, ValueError) as e:
            raise ConfigError(f"Could not parse {path}: {e}") from e

    @staticmethod
    def _parse_toml(text: str) -> dict[str, Any]:
        """Parse TOML text, handling Python 3.10 compatibility."""
        try:
            import tomllib  # py311+
        except ImportError:
            import tomli as tomllib
        return tomllib.loads(text)

    def _apply_dict(self, data: dict[str, Any]) -> None:
        """Apply config values from a parsed dictionary."""
        if "enable" in data:
            self.enable = list(data["enable"])
        if "disable" in data:
            self.disable = list(data["disable"])
        if "severity_threshold" in data:
            self.severity_threshold = str(data["severity_threshold"]).upper()
        if "timeout" in data:
            self.timeout = int(data["timeout"])
        if "extra_args" in data and isinstance(data["extra_args"], dict):
            self.extra_args = {
                str(k): list(v) if isinstance(v, list) else [str(v)]
                for k, v in data["extra_args"].items()
            }
        if "output" in data and isinstance(data["output"], dict):
            self._apply_output(data["output"])

    def _apply_output(self, out: dict[str, Any]) -> None:
        """Apply output configuration from a dictionary."""
        if "formats" in out:
            self.output.formats = list(out["formats"])
        if "report_dir" in out:
            self.output.report_dir = str(out["report_dir"])


class ConfigError(Exception):
    """Raised when a config file is malformed."""
