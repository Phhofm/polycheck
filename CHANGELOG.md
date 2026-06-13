# Changelog

## 0.1.0 (2026-06-05)

Initial MVP. polycheck — static-first, LLM-triage-ready code analysis.

Features:
  * Single ``Finding`` schema, fingerprint-based dedup, severity filter
  * Three reporters: markdown (LLM-friendly), JSON (canonical), SARIF
  * CLI: ``run``, ``list-tools``, ``explain``, ``detected``, ``prompt``, ``doctor``, ``install``, ``mcp``
  * MCP server: ``polycheck.audit_run``, ``list_tools``, ``explain_finding`` tools
    plus ``polycheck://triage/prompt`` resource
  * ``polycheck doctor`` lists installed/missing tools with install hints
  * ``polycheck install [--all] [tool ...]`` auto-installs via pipx/npm/brew/apt
  * ``polycheck run --install`` installs missing tools then runs
  * ``polycheck run --fail-on SEVERITY`` exits 1 in CI when findings exceed threshold
  * Configurable via ``.polycheck.yml`` / ``.polycheck.toml``
  * Auto-discovery of tool adapters via ``pkgutil``
  * Every tool has a populated ``installer`` class attribute (pipx/npm/brew/…)

Supported languages:
  * Python — ruff, mypy, vulture, pip-audit, deptry
  * JavaScript / TypeScript — eslint, tsc, knip, npm-audit, depcheck
  * Universal — gitleaks, semgrep
  * GitHub Actions — actionlint
  * Shell — shellcheck
  * Docker — hadolint

Validation:
  * 52 unit tests pass (including a smoke test on the LUCID repo)
  * Self-lints clean with ``ruff check``
  * Self-host: 0 findings at MEDIUM+ severity
  * End-to-end run on LUCID detected 13 critical CVEs in torch, 1 lint finding


Initial MVP. polycheck — static-first, LLM-triage-ready code analysis.

Supported languages:
  * Python — ruff, mypy, vulture, pip-audit, deptry
  * JavaScript / TypeScript — eslint, tsc, knip, npm-audit, depcheck
  * Universal — gitleaks, semgrep
  * GitHub Actions — actionlint
  * Shell — shellcheck
  * Docker — hadolint

Features:
  * Single ``Finding`` schema, fingerprint-based dedup, severity filter
  * Three reporters: markdown (LLM-friendly), JSON (canonical), SARIF
  * ``polycheck run``, ``list-tools``, ``explain``, ``detected`` CLI commands
  * MCP server: ``polycheck.audit_run``, ``list_tools``, ``explain_finding`` tools
    plus ``polycheck://triage/prompt`` resource
  * Configurable via ``.polycheck.yml`` / ``.polycheck.toml``
  * Auto-discovery of tool adapters via ``pkgutil``

Validation:
  * 34 unit tests pass (including a smoke test on the LUCID repo)
  * Self-lints clean with ``ruff check``
  * End-to-end run on LUCID detected 13 critical CVEs in torch, 1 lint finding
