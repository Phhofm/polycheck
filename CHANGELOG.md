# Changelog

## 0.3.15 (2026-11-27)

Added — MCP readiness parity and structured install failures:

  * **`polycheck.doctor` MCP tool** (read-only): the module docstring
    promised a doctor tool the surface never shipped; an MCP-first
    agent had to shell out to the CLI for the 0.3.14 readiness payload
    and per-profile plan. Now the surface is two workflow tools plus
    one read-only readiness tool — installs stay behind the guided
    flow's consent gate, so doctor can never change the machine.
  * **Structured install failures**: a bare `EACCES` from npm-global
    installs (system-node layouts) now carries the concrete fix —
    user-prefix config or sudo — instead of raw npm stderr for every
    agent to rediscover.

## 0.3.14 (2026-11-27)

Added — scan coverage and per-profile setup plans: a report can no
longer present an incomplete profile as complete, and an agent can ask
what to install *before* burning a scan (found by the
heart-nerve_trainner live test, where a deep run silently omitted
SonarQube because sonarless was not installed — the report footer was
the only hint):

  * **Run coverage**: `polycheck run` now records, per applicable tool,
    whether it ran, failed, was not applicable, was skipped by the
    profile, or is missing — surfaced as a `⚠ … SCAN INCOMPLETE`
    banner + `## Coverage` section in the markdown report, a
    `coverage` object in the JSON report, and a console warning.
    A missing or failed tool makes the profile INCOMPLETE;
    `not-applicable` and profile skips never do.
  * **`doctor --json` profile plan**: `polycheck doctor --json [PATH]`
    now detects the repo's languages and reports, per profile,
    `applicable` / `ready` / `missing` — each missing entry carries
    the install command and an `executor` tag (`agent` for
    package-manager installs polycheck can run after user approval,
    `human` for apt / remote-script installs policy reserves for the
    user). The MCP `polycheck.run` reports carry the same coverage.
  * **Shared eligibility**: the runner, the CLI missing-tool check, and
    the readiness plan now derive from one `candidate_tools` function,
    so doctor and run can never disagree about what would apply to a
    repo.
  * **PATH-independent sonarless detection**: the sonarless installer
    targets `~/.sonarless` without promising a PATH entry — an
    installed sonarless was reported as missing for months because the
    adapter only probed `shutil.which` (live test 2026-11-27: Docker
    was healthy the whole time, the CLI was simply unreachable by
    name). The adapter now resolves the CLI from PATH *or*
    `~/.sonarless/sonarless` and invokes the absolute path, so a
    PATH-less install scans instead of silently vanishing from the
    deep profile.

## 0.3.13 (2026-11-25)

Fixed — sonarless could report a FAILED SonarQube scan as **no-findings**
(found by the ionic-vue/nestjs live test):

  * **Failure detection**: sonarless exits 0 even when the SonarQube
    scan fails (e.g. the Java analyzer aborting on Capacitor's
    uncompiled `.java` stubs). The adapter now raises on failure
    markers, non-zero exits, timeouts, and issues-API errors — a run
    whose analysis did not land on the server never reads as clean.
  * **Success verification**: the adapter polls the SonarQube server
    for the fresh analysis timestamp after the scan. Field-verified
    endpoint on Community Build 26.4: `api/navigation/component` →
    `analysisDate` (`components/show.lastAnalysis` is always null on
    this build).
  * **Default scanner exclusions**: the adapter writes a
    `sonar-project.properties` with `sonar.exclusions`
    (`**/node_modules/**`, `**/dist/**`, `**/build/**`,
    `**/android/**`, `**/ios/**`) when the repo has none — without it
    the Java analyzer aborts on Capacitor stubs — and removes the file
    after the scan. Existing properties files are left untouched.
  * **npm-audit reported installed=False forever** — the default
    binary check used the tool name (`npm-audit` is not an
    executable); the binary is `npm`.
  * Session state: `.polycheck/` is kept out of git automatically
    (appended once to `.gitignore`); `polycheck-reports/` stays
    tracked by design.


Fixed — one shared root cause, found by the ionic-vue/nestjs live test:

  * **gitleaks reported ABSOLUTE file paths** (the adapter passed the
    repo root absolute to `--source`), which broke three things at
    once: the relative-anchored gitignore allowlist never matched —
    so 1408 CRITICAL findings from gitignored build assets flooded a
    live report (the 0.3.3 gitignore-awareness was silently dead in
    every run since; the gitleaks tests are monkeypatch-fake and never
    exercised the allowlist against the real binary) — tracked files
    were bucketed "untracked" — and baseline fingerprints became
    machine-dependent. `--source` is now relative (`.`), gitleaks
    reports repo-relative paths. Regression: a real-binary nested-
    `.gitignore` integration test (monkeypatch-fake tests cannot catch
    flag-level path semantics).
  * **ts-slop had the same absolute-path bug** (absolute scan-path
    argument) — same consequences for ts-slop findings; the scan path
    is relative now.
  * `tests/test_gitleaks_ignores.py` contains a seeded AWS-key-shaped
    fixture; the repo's own scan surfaced it and two more
    secret-shaped documentation strings — all suppressed durably in
    the repo's new `.polycheck.yml` with reasons (seeded defect, test
    fixture, documentation example). polycheck's own repo is back to
    0 findings at MEDIUM+.


  * **`ts-slop` gains `ts-any-annotation`** — flags `: any` type
    annotations (parameters, variables) as slop. Found in the field:
    an ionic-vue/nestjs codebase screenshot showed `function
    openPDF(pdf: any)` — the untyped function signature is a stronger
    erosion marker than an `as any` cast. Seeded expectation now 3.


**`ts-slop` — polycheck's own TypeScript slop rule set** (first
extension of the SlopCodeBench approach beyond Python):

  * New adapter running **polycheck-authored ast-grep rules** for
    TypeScript: index `for` loops over arrays, type-system escape
    hatches (`as any`, `as unknown as T`, empty-object casts,
    `@ts-ignore`), empty catch blocks, and mechanical verbosity
    (`!!x`, if/else returning booleans). Why authored, not ported:
    scb-check 0.2.0 ships 197 rules, all Python, and its extra-rules
    mechanism does not reach the analysis pipeline (verified in
    source) — the degradation forms are agent behavior, so the rules
    are written fresh per language, not translated.
  * ast-grep ships via `npm:@ast-grep/cli` with an npx fallback
    (package-name form — `npx ast-grep` cannot resolve the bin);
    Windows-safe via the 0.3.9 `cmd /c` routing.
  * Rule file ships as package data; every rule verified against a
    seeded TypeScript defect; seeded-verifier expectation `ts-slop: 2`
    verified `ok` against the real binary (0.5 s).
  * Known gap, documented with evidence: Vue SFCs (`.vue`) are
    silently skipped by ast-grep 0.51 (no builtin language) — `.ts`
    files (NestJS backends, Ionic services) are covered fully.

## 0.3.9 (2026-11-25)

  * **Fixed: the npm-family npx/npm fallbacks crashed on Windows**
    (`WinError 2` — npm's `.cmd` shims cannot be spawned directly).
    knip, depcheck, eslint, tsc, dependency-cruiser, and npm-audit now
    route through `cmd /c` on Windows; caught by the cross-platform
    smoke test, verified green on windows-latest (all three Python
    versions).
  * **CI: macOS removed from the test matrix.** The hosted macOS pools
    starved for days — macos jobs waited hours for a runner while
    ubuntu/windows picked one up in seconds, keeping runs stuck
    "in progress". macOS coverage is suspended until capacity is
    dependable (ubuntu-latest + windows-latest × 3.10/3.12/3.13 remain).

## 0.3.8 (2026-11-25)

The SlopCodeBench composites become first-class scan metrics:

  * **`polycheck-report.json` carries a top-level `metrics` key** with
    scb-check's SlopCodeBench composites — `verbosity`, `erosion`,
    `cog_erosion` plus the detail counts — on every scan that runs
    scb-check. Diff them across runs to measure whether an
    agent-assisted codebase stays stable or erodes turn over turn. The
    markdown report gains a "Scan metrics" section. The key is omitted
    entirely when no tool publishes metrics, keeping the schema stable
    for consumers that diff reports.
  * The scb-check adapter makes a second `scb-check check . --report`
    invocation after the finding run (the human output carries no
    composites); a failed metrics run never breaks the findings.
  * Fixed: the run table swallowed bracket tokens like `[tool.tach]`
    in not-applicable reasons — rich parsed them as style markup; cell
    content is escaped now.
  * Fixed: deptry's not-applicable row carried an empty reason; it now
    states "no pyproject.toml" like the other manifest adapters.

(Both fixes found by the second external reviewer loop.)

## 0.3.7 (2026-11-25)

Fixes from the first external live test (a full reviewer loop in
another repo, scan trajectory 590 → 2):

  * **Not-applicable tools are now visible in the run table.** A deep
    run silently dropped installed tools whose config or dependency
    manifest was absent (tach without `tach.toml`, pip-audit without a
    manifest, dependency-cruiser without its config) — understanding
    why required a doctor cross-check. The run now shows every such
    tool as `not-applicable` with the adapter's reason (e.g.
    "no dependency manifest (pyproject.toml, requirements.txt, …)").
    Scan-coverage math excludes these rows.
  * **`polycheck doctor --json` embeds a `skill` block** — pointer to
    the `polycheck://setup` resource and the raw `polycheck-skill.md`
    URL with an install hint, so any agent reaches the full usage guide
    in one hop without a host-specific skill preinstalled.
  * README documents that suppressing a **mitigated** finding via
    `suppress:` is legitimate — persist the verdict with a comment
    documenting the mitigation (context: semgrep inline suppression
    does not stick for taint rules; `.polycheck.yml` suppress is the
    reliable path).

## 0.3.6 (2026-11-25)

The JS/TS structural adapter, a machine-readable readiness surface for
LLM agents, and a README that now leads with the why:

Features:
  * **`dependency-cruiser` adapter** — second structural adapter
    (`ARCHITECTURE` category, deep profile): circular dependencies and
    path/layer rules from `depcruise --output-type json`. Runs when the
    repo carries a `.dependency-cruiser.*` config. Shape-pinned against
    real 18.9.0 output (violations live in `summary.violations`;
    violations do not change the exit code; the npm fallback must use
    the package name, `npx depcruise` resolves a placeholder).
  * **LLM readiness surface** — `polycheck doctor --json`: every
    analyzer with `installed`/`install_hint`/`auto_installable` and the
    scan `profiles` it participates in, system prerequisites (Docker for
    sonarless), profile guidance, and the install policy (what polycheck
    installs itself — and what it never does). New MCP resource
    `polycheck://setup` (setup/operations guide for agents) and a
    `profile_guidance` block in both scan responses.
  * `/polycheck` workflow gains a readiness preflight step before the
    first deep run: propose missing prerequisites (Docker, sonarless) to
    the user; never auto-install either.
  * **`polycheck-skill.md`** — a ready-to-install agent skill encoding
    the optimal usage (readiness first, profile choice, triage →
    suppress → baseline, hard rules). Claude Code users get a skill via
    `polycheck init`; this is the standalone version.
  * README: leads with the why — SlopCodeBench (Orlanski et al., 2026,
    arXiv:2603.24755) measured that coding agents degrade codebases
    across iterative extension (erosion in 77 % of trajectories, agent
    code 2.3× more verbose than human repos) and that prompt-level
    quality guidance does not change the degradation rate. polycheck
    applies those findings as deterministic checks. Plus: anti-AI-slop
    section and a restructure (most important first).

Fixed:
  * **knip** reported not-installed on machines without a global knip
    binary even though its `run()` falls back to `npx knip` — the
    fallback was unreachable. Same fix applied to dependency-cruiser.
  * mypy surfaced latent false positives against the mcp SDK's dynamic
    decorator API — handled with a documented `follow_imports = skip`
    override instead of scattered ignores.

CI:
  * docs-only pushes skip the 9×3 test matrix; a release commit pushed
    to dev AND main runs the matrix once (SHA concurrency group).

## 0.3.5 (2026-11-25)

Fixed:
  * **`--profile pr` gate hole (found by the post-release pipx E2E)**: on
    a repository with no upstream — the first push to a fresh remote —
    the changed-file scope was empty once everything was committed, so a
    committed HIGH finding could be pushed straight through the pre-push
    gate. No upstream means nothing has been pushed yet: the pr scope now
    covers every tracked file in that case (committed + staged), and the
    gate blocks. Repositories with an upstream keep the narrow
    merge-base + working-tree scope.

## 0.3.4 (2026-11-25)

Profiles, the first structural adapter, and a cross-model audit of the
heavy analyzers against real tool output:

Features:
  * **Scan profiles** — `--profile pr` (fast tools only, findings scoped
    to changed tracked files, HIGH gate; the pre-push hook now runs it)
    and `--profile deep` (every tool including heavy ones, no gate —
    output feeds triage → baseline). The default scan is unchanged
    (whole repo, MEDIUM gate). Profiles are presets over existing
    primitives — tool selection, scoping, gate — no new engines.
  * **`tach` adapter** — first structural adapter (`ARCHITECTURE`
    category): undeclared cross-module dependencies and, with
    `forbid_circular_dependencies`, dependency cycles from
    `tach check --output json`. Runs when the repo carries a
    `tach.toml` (or `[tool.tach]`); deep-profile family. Chosen over
    import-linter on real-output evidence: tach emits JSON,
    import-linter only human text.
  * Reviewer subagent: "Quality questions (deep profile)" section —
    SRP, SOLID, Law of Demeter, naming, comments-why, design patterns,
    observability, scalability as checklist QUESTIONS for the user,
    never fabricated findings.
  * MCP `polycheck.run` / `audit_run` accept `profile: "pr" | "deep"`
    (pr presets the HIGH severity floor); the `/polycheck` workflow
    documents the mode argument.

Fixed (cross-model audit against real CLI/API payloads):
  * **semgrep**: findings carried no line/column — the parser read
    `extra.start`, but real semgrep output has `start` on the result
    object. Every semgrep location was silently `None` before.
  * **pip-audit**: the pyproject.toml fallback wrote its temporary
    requirements file into the repo (`.polycheck-pip-audit-reqs.txt`)
    and never removed it — pollution the next gitleaks run would scan.
    Now a temp file outside the repo, removed after the run.
  * **pip-audit**: a non-object JSON payload crashed the parser;
    it is now tolerated as "no findings" while the documented object
    shape parses unchanged.

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
  * New `scb-check` adapter: AI-slop metrics from SlopCodeBench —
    duplicated AST blocks (DUPLICATION), slop patterns like
    `range(len(x))` and `dict.get(k, None)` (LINT), and erosion
    findings for functions above the complexity threshold (COMPLEXITY).

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
