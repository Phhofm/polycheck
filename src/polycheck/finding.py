"""Unified Finding schema — the lingua franca between tools, reporters, and LLMs.

Every tool adapter normalizes its raw output into ``Finding`` objects. This
means:

  * Reporters (JSON, markdown, SARIF) only have to know one shape.
  * Cross-tool deduplication can compare Findings on (file, line, message).
  * An LLM triaging a report sees a consistent input regardless of which
    tool produced each finding.
"""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any


class Severity(enum.IntEnum):
    """Coarse severity ordering. Tools that emit their own severities are
    mapped to one of these by the tool adapter."""

    INFO = 1   # style, formatting, docstring
    LOW = 2    # minor smell, dead code, missing dep
    MEDIUM = 3 # type warning, complexity, duplication
    HIGH = 4   # real bug, unused error, missing error handling
    CRITICAL = 5  # security, secrets, CVE

    @classmethod
    def from_str(cls, value: str) -> Severity:
        """Best-effort parse for tool-specific severity strings."""
        v = value.upper().strip()
        aliases = {
            "BLOCKER": "CRITICAL",
            "CRITICAL": "CRITICAL",
            "MAJOR": "HIGH",
            "ERROR": "HIGH",
            "HIGH": "HIGH",
            "MINOR": "LOW",
            "WARNING": "MEDIUM",
            "WARN": "MEDIUM",
            "MEDIUM": "MEDIUM",
            "INFO": "INFO",
            "INFORMATIONAL": "INFO",
            "NOTE": "INFO",
            "STYLE": "INFO",
        }
        return cls[aliases.get(v, "MEDIUM")]


class Category(enum.Enum):
    """Top-level category. Used by reporters to group and color."""

    LINT = "lint"
    TYPE = "type"
    SECURITY = "security"
    SECRETS = "secrets"
    DEAD_CODE = "dead-code"
    COMPLEXITY = "complexity"
    DUPLICATION = "duplication"
    CVE = "cve"
    DEPS = "deps"
    FORMAT = "format"
    OTHER = "other"


@dataclass
class Finding:
    """A single reported issue, normalized across all tools."""

    tool: str                              # e.g. "ruff", "eslint", "gitleaks"
    rule: str                              # tool-specific rule id, e.g. "E501", "no-unused-vars"
    severity: Severity
    category: Category
    message: str                           # human-readable, single line
    file: str | None = None                # repo-relative POSIX path
    line: int | None = None
    column: int | None = None
    fixable: bool = False                  # tool has a --fix equivalent
    fix_command: str | None = None         # exact command the user can run
    doc_url: str | None = None             # tool-specific docs link, if known
    raw: dict[str, Any] = field(default_factory=dict)  # original tool output

    def location(self) -> str:
        """``path:line:col`` short form for reporters. Path is bare if
        no file; line/column elided if missing."""
        if not self.file:
            return ""
        loc = self.file
        if self.line is not None:
            loc += f":{self.line}"
            if self.column is not None:
                loc += f":{self.column}"
        return loc

    def fingerprint(self) -> str:
        """Stable identity for cross-tool deduplication. Two findings with
        the same fingerprint are likely the same defect seen by two tools.
        """
        return f"{self.tool}|{self.rule}|{self.file or ''}|{self.line or 0}|{self.column or 0}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.name
        d["category"] = self.category.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Finding:
        return cls(
            tool=d["tool"],
            rule=d["rule"],
            severity=Severity[d["severity"]] if isinstance(d["severity"], str) else d["severity"],
            category=Category(d["category"]) if isinstance(d["category"], str) else d["category"],
            message=d["message"],
            file=d.get("file"),
            line=d.get("line"),
            column=d.get("column"),
            fixable=d.get("fixable", False),
            fix_command=d.get("fix_command"),
            doc_url=d.get("doc_url"),
            raw=d.get("raw", {}),
        )


def fingerprint(tool: str, rule: str, file: str | None, line: int | None, column: int | None) -> str:
    """Module-level helper that matches ``Finding.fingerprint()``.

    Useful for tool adapters that want to mint a fingerprint without
    first constructing a full ``Finding``.
    """
    return f"{tool}|{rule}|{file or ''}|{line or 0}|{column or 0}"
