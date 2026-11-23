# Changelog

## 0.2.1 (2026-11-23)

Fixes:
  * `polycheck --version` printed 0.1.0 in the 0.2.0 wheel (hardcoded
    `__version__` missed in the version bump). A consistency test now
    enforces pyproject.toml ↔ `__init__.py` ↔ CHANGELOG.md.

Maintenance:
  * GitHub Actions bumped to current majors (checkout v7, setup-python v7,
    upload-artifact v7, download-artifact v8, gh-action-pypi-publish pinned
    to v1.14.3) — clears the Node 20 deprecation warnings.
  * Explicit least-privilege `permissions` on both workflows.
  * Markdown report caps each rule at 5 example rows (with an exact
    "and N more" count) so LLM triage reads bounded, relevant output.

## 0.2.0 (2026-11-23)

Every bundled analyzer is now guarded by a seeded-defect verifier, and the
daily-driver features landed.

Features:
  * `polycheck baseline` + `run --diff` — report only findings that are new
    since the baseline (fingerprint-based, stored in `polycheck-reports/`)
  * Durable suppressions: `.polycheck.yml` `suppress:` list (`rule` or
    `rule@file`) persists FALSE-POSITIVE triage verdicts across runs
  * Guided MCP workflow teaches the baseline/suppress loop; `polycheck.run`
    gained a `diff` parameter and reports `baseline` known/new counts
  * `verify-tools` fails with `missed-defects` when an analyzer runs clean on
    a repo seeded with defects it must catch (per-tool expectations)
  * Claude Code skill template now ships the required YAML frontmatter

Fixes (silently broken adapters — all verified against real tool output):
  * eslint, tsc, knip, depcheck: argv duplication (`tsc tsc ...`) when the
    binary was on PATH
  * shellcheck: passed a directory argument; parses `note:` severity now
  * gitleaks: parses the JSON report from `--report-path`, scans the working
    tree (`--no-git`), surfaces real failures as errors
  * mypy: parses `--show-column` output
  * vulture: exit code is the finding count, not an error signal
  * deptry: reads findings from stderr, parses file-level DEP002 lines
  * depcheck: parses the heading+bullet output format
  * ruff: bug-shaped rules (F821/F811) are HIGH, E7xx MEDIUM, so real bugs
    survive the default MEDIUM filter

Quality gates:
  * GitHub Actions CI: 9-job OS/Python matrix (lint, strict-ish mypy, tests)
    plus a self-check job that dogfoods polycheck on this repo
  * `mypy src/polycheck` and `mypy .` (whole repo) pass; pragmatic config
  * Test suite: 134 tests

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
