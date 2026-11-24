# Changelog

## 0.3.3 (2026-11-24)

From the bigger-repo live test (1717 raw findings on first scan):

Features:
  * **Track-status buckets**: every finding is annotated
    `tracked` / `untracked` / `ignored` (batch git calls, zero per-finding
    cost). The severity headline and the `--fail-on` gate count only what a
    push can carry (tracked + untracked); gitignored files cannot reach the
    repo, so ~1690 "CRITICAL" noise findings in a real repo stopped being
    alarms. Reports show the buckets explicitly.
  * gitleaks excludes the repo's **gitignored paths** (build outputs,
    Playwright traces with throwaway tokens, backups) via the generated
    allowlist — the source of the 1717 raw findings.
  * Reviewer agent: suggested actions with concrete config keys/values are
    doc-verified or phrased generically with an applicability condition
    (invented keys/units are worse than no value); triage reads the cited
    lines before proposing actions (action already satisfied → FALSE
    POSITIVE with evidence); the return format carries a coverage-gap line
    (e.g. "npm-audit not installed — no CVE scan this run").
## 0.3.2 (2026-11-24)

Features:
  * `.polycheck.yml` `extra_args` now reaches the tool command lines
    (`mypy: ["--python-executable", ".venv/bin/python"]` for project
    venvs, ruff/eslint/semgrep/shellcheck/vulture/hadolint/tsc/knip/
    depcheck/deptry/gitleaks/scb-check alike). pip-audit, npm-audit and
    sonarless follow in a later release.

Fixed:
  * gitleaks regression caught by the seeded-defect verifier: a custom
    `--config` replaces gitleaks' default ruleset — the generated
    exclusion config now extends the defaults (`[extend] useDefault =
    true`) so secrets are detected again while our paths stay excluded.

## 0.3.1 (2026-11-24)

Fixes from the first external live test (Philip's vibecode-skill repo):
  * Gitignored directories are no longer scanned — discovery uses
    `git ls-files -co --exclude-standard` in git repos (walker fallback
    elsewhere). A repo with gitignored harness code dropped from 591
    findings to 39, all from project code.
  * Language detection works from file presence anywhere in the project
    (`.py`, `.ts`, `.sh`, ...), not only from manifests at the root —
    repos without `pyproject.toml` now run ruff/mypy/vulture/scb-check.
  * actionlint is no longer silently dropped from every run (it declared
    no languages, so the candidate filter excluded it).

## Unreleased

Features:
  * New `scb-check` adapter: AI-slop metrics from SlopCodeBench —
    duplicated AST blocks (DUPLICATION), slop patterns like
    `range(len(x))` and `dict.get(k, None)` (LINT), and erosion
    findings for functions above the complexity threshold (COMPLEXITY)

## 0.3.0 (2026-11-24)

The reviewer release: polycheck becomes a delegable code-review step that
keeps the main chat clean.

Features:
  * `polycheck init` now writes a **`polycheck-reviewer` subagent** for
    Kilo (`.kilo/agent/`), OpenCode (`.opencode/agent/`), and Claude
    (`.claude/agents/`): it runs polycheck, triages every finding
    (REAL BUG / REAL SMELL / FALSE POSITIVE / DEFERRED), writes a ranked,
    actionable checklist to `polycheck-reports/polycheck-review-checklist.md`
    (severity, tool:rule, exact location, concrete action, effort estimate),
    persists FALSE-POSITIVE verdicts into `.polycheck.yml`, and returns only
    a compact summary — the main chat stays clean
  * `--no-agents` / `--agents-only` flags to control agent generation
  * `polycheck init --git-hook pre-push` installs a dev-cycle quality gate
    (`.git/hooks/pre-push` runs `polycheck run . --parallel --fail-on HIGH`;
    never overwrites an existing hook)
  * Guided workflow prefers the reviewer subagent when available
  * Vendored/build directories (`.venv`, `node_modules`, `dist`, `vendor`,
    …) are excluded from file-collecting analyzers — no more false
    positives from other people's code in dependency trees
  * MCP progress notifications (`notifications/progress`) during
    `polycheck.run` when the client requests them

Simplifications:
  * MCP server slimmed to two tools (`polycheck.run`, `polycheck.audit_run`);
    diagnostics, listings, explanations, and installs are CLI-only
    (`polycheck doctor` / `install` / `list-tools` / `explain`)
  * GitHub-release binary downloads and `curl | bash` installs removed from
    all installers — polycheck no longer fetches unverified executables;
    package-manager installs (pipx/pip/npm/brew/apt) and explicit hints remain

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
