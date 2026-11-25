# DEVELOPMENT.md

Single log for progress, decisions, and experiments. Task checklists live in
`MASTERPLAN.md` (task-by-task with commit messages) and `implementation_plan.md`
(milestones); this file records *state* and *why*, so nothing goes stale.

## Next session start here

0.3.4 (profiles, tach, quality questions) shipped and released — see the
0.3.4 experiments entry below for evidence and the three audit fixes.

Suggested next block (from the backlog, one per iteration, D1):

1. **Baseline + diff in the pr hook** — the hook could pass `--diff` so a
   taken baseline filters known findings out of the gate. Deliberately not
   shipped in 0.3.4: the hook is the "always safe" path; baseline semantics
   in a gate need a repo that has actually taken one.
2. **dependency-cruiser** (JS/TS structural counterpart to tach), seeded
   expectation required before it ships.
3. **Cross-model audit follow-ups**: eslint expectation still needs a
   machine with eslint; knip expectation still undecided.
4. **D3/D4 pending items** (README reframe is partially done; MCP surface
   cut still pending).

Working agreement (Philip, 2026-11-25): **everything is verified in this
repo first** — local gates green, live run on a scratch/synthetic repo,
pipx E2E from a fresh install — *then* it gets tested in other repos.
Releases: assert-anchored changelog insert, `&&`-chained gates before
commit, tag, PyPI verification — see the 0.3.2 process-miss entry in
Experiments.

Also read before starting: the *Experiments* log (live-test history and
the two external live tests that produced meta-findings #1–#5, all fixed
or logged), the *Decisions* section, and the *Backlog* section.

## Current state (verified 2026-11-25, 0.3.4 work block)

Environment: Python 3.12, tooling installed to `~/.local` (pipx-style).
`polycheck` on PATH = local source install (`pipx install --force
/home/phhofm/Documents/GitHub/polycheck`); refresh it after every feature
block so hook/CLI E2E runs test the new code. `scb-check` also
pipx-installed.

| Gate | Command | Result |
| --- | --- | --- |
| Lint | `ruff check src tests` | clean (exit 0) |
| Types | `mypy .` (whole repo incl. tests) | clean — pragmatic config |
| Tests | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q` | 201 passed, 0 failed, 1 skipped (LUCID_PATH env) |

Latest release: **0.3.4** (tagged this session; verify on PyPI after the
publish workflow finishes). v0.3.0–v0.3.3 all released via Trusted
Publishing. CI note: GitHub runner capacity queued test-matrix runs for
hours on 2026-11-23/24 — Release workflows stayed green; local gates are
the verification chain.

Environment notes discovered this session:

* **tach 0.35.3 is pipx-installed** (`pipx install tach`) — needed by the
  tach adapter's seeded verification. import-linter 2.17 was installed
  for the adapter evaluation only (human-text output, no JSON) and can be
  removed with `pipx uninstall import-linter`.
* The bash tool resets cwd between calls — scratch-repo work must pass an
  explicit `workdir` per call; a bare `git add -A && git commit` once ran
  in the polycheck repo instead of a scratch dir (accidental `tach.toml`
  + "seed" commit, immediately reset — see the 0.3.4 experiment entry).
* `typer` 0.23 was installed without its `shellingham` dependency → `import typer`
  (and therefore the whole CLI) failed. Fixed by `pip install --user
  --break-system-packages shellingham`. Root cause: typer 0.23 split into
  typer-slim; the global env predates the fix.
* The globally installed **langsmith pytest plugin** breaks pytest collection
  (`ModuleNotFoundError: requests_toolbelt`). Workaround until the env is
  cleaned: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p no:cacheprovider`.
* **mypy runs in an isolated pipx venv** (`~/.local/pipx/venvs/mypy`), so it
  cannot see user site-packages. The runtime deps + stubs must be injected:
  `pipx inject mypy mcp pyyaml requests typer rich anyio tomli types-PyYAML
  types-requests`. **Pin the injected mcp to the runtime version**
  (`pipx inject mypy "mcp==1.27.0"`) — an unpinned inject pulled mcp 2.3.0,
  whose renamed pydantic fields (`mime_type`, `input_schema`) produced false
  API-mismatch errors against the 1.27.0 runtime.
* ~~`tests/test_sonarless.py::test_sonarless_install_requires_docker` is
  env-dependent~~ — fixed 2026-11-23 (test patches `is_installed` too).

Known silently-broken analyzers: **all resolved 2026-11-23** — the seeded-defect
verifier (implementation_plan 1.13) now guards every adapter with an
expectation (`_EXPECTED_FINDINGS` in verify.py), and the locally installed set
(ruff, mypy, vulture, deptry, gitleaks, shellcheck, tsc, actionlint, depcheck)
all report `ok` on their seeded repos. eslint's expectation is in place but
unverified locally (eslint not installed on this machine); knip has no
expectation yet (its argv bug is fixed, but the synthetic repo may legitimately
produce no knip findings).

## Decisions

Format: id, date, decision, reason, status. User decisions override anything here.

* **D1 (2026-11-23) — Signal quality over breadth.** No new analyzers until the
  four broken ones above are fixed and every adapter has a seeded-defect
  regression test (implementation_plan 1.13). A scan that silently returns
  nothing produces false confidence — the exact failure mode polycheck exists
  to prevent. Status: ACCEPTED (user approved continuing with review roadmap).
* **D2 (2026-11-23) — Baseline + diff is the strategic core.** `polycheck
  baseline` + diff against it ("what's new in my PR?") plus durable
  suppressions (`.polycheck.yml` `suppress:` list, persisted FALSE-POSITIVE
  verdicts) are the features that convert polycheck from an occasional audit
  tool into a daily driver. Priority over CI and PyPI polish.
  Status: ACCEPTED as roadmap priority; implementation pending.
* **D3 (2026-11-23) — Reposition README claim.** Lead with "your LLM triages a
  verified report instead of hallucinating a review" (grounding, precision,
  reproducibility) rather than token savings, which the on-prem LLM shift
  weakens. Status: PENDING.
* **D4 (2026-11-23) — Cut product surface.** Installer zoo reduced to
  pipx/pip/npm (drop brew/apt/GitHub-release auto-download — maintenance and
  supply-chain surface; print hints instead). MCP surface cut to
  `polycheck.run` + `audit_run` (+ resources); `doctor`/`explain_finding`/
  `install` become CLI-only. Guided-workflow protocol simplified. SARIF
  shelved. sonarless stays as the semantic-analysis differentiator but becomes
  opt-in with manual-first install. Status: PENDING (execute after D2).
* **D5 (2026-11-23) — gitleaks scans the working tree only** (`--no-git`),
  matching the adapter docstring; history scanning is a deliberate opt-in to
  add later if wanted. README tool matrix corrected accordingly.
  Status: ACCEPTED (implemented with the gitleaks fix).

## Experiments

Format per §7: date, hypothesis/recommendation, metric + command, before →
after, verdict, reason.

* **2026-11-25 — 0.3.4: profiles + first structural adapter + cross-model
  audit of the heavy adapters.** What: (1) `--profile pr|deep` as presets
  over existing primitives (profiles.py): pr = fast tools only (heavy +
  structural skipped), findings scoped to changed tracked files (git diff
  vs HEAD plus merge-base-ahead when an upstream exists), gate HIGH; deep
  = every tool incl. heavy, no gate; default unchanged (MEDIUM gate).
  Pre-push hook switched to `--profile pr`; MCP `polycheck.run` and
  `audit_run` gained a `profile` param (pr presets the HIGH severity
  floor); `/polycheck` workflow template documents the mode argument.
  (2) First structural adapter **tach** (Category.ARCHITECTURE, new
  `structural` Tool flag): chosen over import-linter on evidence —
  import-linter 2.17 emits human text with ASCII art and no JSON, tach
  0.35.3 emits clean JSON (`check --output json`); tach needs declared
  `depends_on` edges, so the adapter runs only when tach.toml /
  `[tool.tach]` exists. Seeded verifier expectation `tach: 1` verified
  `ok` against the real binary (0.2s). (3) Reviewer template gained the
  "Quality questions (deep profile)" section — SRP/SOLID/LoD/names/
  comments-why/patterns/observability/scalability as checklist QUESTIONS,
  never findings. (4) Cross-model audit of the heavy adapters against
  real CLI/API payloads: **pip-audit** — real payload matched the parser
  (54/54 unique vuln IDs, pillow==9.0.0) but the pyproject fallback wrote
  `.polycheck-pip-audit-reqs.txt` into the repo and never removed it
  (fixed: tempfile outside the repo, removed after the run) and crashed
  on a non-dict JSON payload (fixed: tolerant parse). **npm-audit** —
  real payload matched (6/6 via-entries, lodash 4.17.20). **semgrep** —
  the parser read `extra.start` but real 1.186.0 output carries
  `start.line/col` on the result object, so every location was silently
  None (fixed; verified against a real local-rule run). **sonarless** —
  full live run against the real SonarQube API matched the parse
  (`sonar:bug:python:S930`, BLOCKER→CRITICAL). Note: semgrep OSS
  `--config=auto` selects a rule subset (327 of 1074 rules on the seed)
  and misses textbook defects like `yaml.load` without login-tier rules —
  tiering behavior, not a polycheck bug. Verification chain: gates green
  (ruff/mypy/201 tests), live scratch-repo runs of all three profiles
  (default exit 1 on HIGH mypy — unchanged; pr exit 0 with only
  src/new.py findings in scope, exit 1 after planting a HIGH F821 in the
  changed file; deep ran pip-audit/semgrep/sonarless and exited 0),
  bare-remote pre-push hook E2E (HIGH finding in changed file → push
  blocked; fix → push lands). Process note: a scratch-repo `git add -A
  && git commit` ran in this repo by mistake (cwd reset) — accidental
  tach.toml commit reset immediately (`git reset a0798b3`), lesson
  recorded in environment notes. Verdict: KEPT.

* **2026-11-24 — 0.3.3: track buckets + reviewer rules from the
  bigger-repo test.** Live-test feedback turned into features: (1) track
  annotation (batch `git ls-files` + `git check-ignore --stdin`, zero
  per-finding spawns), gate counts tracked+untracked, reports show
  buckets — the 1717-raw-finding headline problem solved at the
  runner/reporter layer, not per-adapter; (2) gitleaks allowlist gains
  the repo's gitignored paths (collapsed dirs from
  `git ls-files -o -i --exclude-standard --directory`; hyphens
  un-escaped after re.escape — `test\-results` does not literal-match);
  (3) reviewer template: doc-verification/applicability rule for
  concrete config values (invented `min-release-age = 7` case), cited
  lines must be read before proposing actions (already-satisfied code →
  FALSE POSITIVE with evidence — the template-literal case), return
  format carries coverage gaps. The colleague loop's full cycle (scan →
  triage → choice → fix → re-scan green) ran between 0.3.2 and 0.3.3.

* **2026-11-23 — seeded-defect verifier (plan 1.13) exposed 6 more silently
  broken adapters (RED→GREEN).** Hypothesis: tools that run clean on a repo
  seeded with defects they must catch are broken, so `verify-tools` must fail
  on that. Metric: `verify_tools()` statuses on the locally installed set.
  Before: mypy, shellcheck, tsc, vulture, deptry, depcheck all
  `missed-defects`; after fixes all `ok` (findings 1–3 each; vulture 3,
  depcheck 3). Root causes: mypy regex lacked the `--show-column` column
  group; shellcheck's gcc format emits `note:` severity (not in regex);
  vulture exits with the *finding count* (rc 3 = 3 findings) and the adapter
  dropped rc ≥ 2; tsc regex expected `error:` but tsc prints `error TS2322:`;
  knip/tsc/depcheck had the eslint-style argv duplication (`tsc tsc ...`);
  deptry prints findings to **stderr**; depcheck's heading+bullet format
  replaced the old `Unused: pkg` lines; gitleaks's default config allowlists
  the literal `aws_access_key_id`/`aws_secret_access_key` names, so the seeded
  secret now uses `aws_key =`. Verdict: KEPT. Suite 111 passed; eslint's
  expectation still needs a machine with eslint installed.
* **2026-11-23 — pragmatic mypy config (plan 0.3, RED→GREEN).** Hypothesis:
  the strict gate was red on fixable typing, not design problems. Metric:
  `mypy src/polycheck`. Before: 132 errors (strict) → 31 after config change +
  stub injection → 21 after pinning mcp to the runtime version → **0** after
  real fixes: `type` → `type[Tool]` (runner, cli), guard for None installer
  cmd (base.py), typed `_latest_github_release_assets` 3-tuple, inlined
  issubclass narrowing in registry (removed `_should_register`), hadolint
  second-variable comprehension fix, `sys.version_info` tomllib/tomli switch
  (config, pip_audit), `AnyUrl(...)` for MCP resource URIs. Config: strict=true
  → check_untyped_defs + no_implicit_optional + warn_unused_ignores +
  warn_redundant_casts; dev extras gained types-PyYAML/types-requests.
  No `# type: ignore` added. Verdict: KEPT. All three gates now green.
* **2026-11-24 — 0.3.1 released; live-repo before/after measured.** The
  three meta-findings fixed: (1) gitignore-aware discovery via
  `git ls-files -co --exclude-standard` (walker fallback for non-git
  repos) — verified on Philip's vibecode-skill repo: shellcheck noise
  584 → 2 real findings, total findings all from project code;
  (2) detection now uses walker-based file presence anywhere in the
  project — the manifest-less repo detected "github-actions, shell,
  python" and ruff/mypy/vulture/scb-check ran for the first time
  (6+15+3+2 real findings surfaced); (3) actionlint had
  `languages = []`, which the candidate filter (runner AND cli) treats
  as never-matching — now `["github-actions"]`, appears in the run
  table. Released v0.3.1, verified via PyPI JSON API. Post-release
  E2E note: `pipx install polycheck` briefly served 0.3.0 from pip's
  HTTP simple-index cache (~2 min window) — cleared `~/.cache/pip` and
  0.3.1 installed correctly; not a polycheck bug, but part of the
  post-release checklist (retry after cache expiry or clear the cache).
* **2026-11-24 — first external live test found 3 meta-findings (from Philip's
  vibecode-skill repo run).** (1) Gitignored directories are scanned —
  `iter_source_files` + EXCLUDED_DIRS is a static denylist without
  .gitignore awareness; 582 noise findings from gitignored `logs/` harness
  code. Fix direction: discovery via `git ls-files -co --exclude-standard`
  (git-native, no new dependency), walker fallback for non-git repos,
  config escape hatch. (2) Python detection requires a manifest — repos
  with only `scripts/*.py`/`tests/*.py` and no pyproject.toml never see
  ruff/mypy/vulture/scb-check. Fix: file-presence marker in detect.py,
  generalizable to js/ts/sh. (3) actionlint missing from the run table
  despite github-actions detection and an existing workflow file — needs
  reproduction; hypotheses: language-slug mismatch detect↔adapter, or
  missing-binary handling hiding it. Status: logged, not yet implemented
  (user directive: info only).
* **2026-11-24 — extra_args plumbing shipped; verifier caught a regression
  in the same change.** Meta-finding #4 from the colleague loop:
  `.polycheck.yml` `extra_args` existed in Config but never reached the
  tools (adapters built commands without config knowledge). Fix: optional
  config injection (`Tool.__init__(config=...)` + `extra_args()` helper),
  Runner constructs tools with config, `*self.extra_args()` plumbed into
  15 adapters (mypy, ruff, eslint ×2 paths, shellcheck, vulture, hadolint,
  tsc ×2, knip ×2, depcheck ×2, deptry, gitleaks, scb-check). pip-audit/
  npm-audit/sonarless deferred (heavy/complex). While re-running the
  seeded-defect verifier after the sweep, gitleaks reported
  `missed-defects` — the verifier caught that the exclusion-config commit
  had broken detection entirely: gitleaks `--config` REPLACES the default
  ruleset, and our generated allowlist config had no rules. Fixed with
  `[extend] useDefault = true`. Verdict: KEPT; the verifier guarding every
  adapter change is doing its job.
  Also noted (meta-finding #5, not actionable in polycheck): semgrep inline
  `# nosemgrep` does not suppress taint-mode rules — semgrep engine
  behavior, documented in the colleague loop.
* **2026-11-24 — release-process miss on 0.3.2, self-caught.** Two chained
  mistakes: (1) the 0.3.2 changelog insert was a silent no-op (its search
  anchor "## Unreleased" no longer existed) — the consistency test caught
  it immediately; (2) the release command chain used `;` before the git
  steps instead of `&&`, so the tag was pushed despite the red gate —
  against the project's own rule. Recovery: changelog fixed (the wheel
  itself was correct: pyproject 0.3.2, PyPI accepted it), consistency test
  green, docs commit pushed. Rule going forward: release chains use `&&`
  end to end; a red gate stops the chain. Also: the replace-style
  changelog edits need an assert-anchored insert, not a silent replace.
* **2026-11-24 — end-to-end verification day (caught 2 real bugs).** What:
  (a) fresh `pipx install polycheck` from PyPI → 0.3.0 correct, init writes
  reviewer agents, scan gates; (b) **real MCP stdio client** spawned
  `polycheck mcp`, listed exactly 2 tools + resources, called
  `polycheck.run` → correct guided payload incl. `needs_user_input` on
  missing analyzers; (c) **real pre-push gate test**: bare remote + hook →
  push with HIGH findings blocked ("polycheck found HIGH+ findings"), fix →
  push lands. Test (c) exposed a real product bug: gitleaks/semgrep scanned
  `polycheck-reports/` — self-referential contamination (reports embed
  finding texts, next run flags them as secrets). Fixed via gitleaks
  native config allowlist (generated temp TOML with path regexes from
  EXCLUDED_DIRS) and semgrep `--exclude` flags; sonarless noted (opt-in
  heavy tool, defer). Verdict: KEPT — these end-to-end tests are now the
  standard post-release checks.
* **2026-11-24 — scb-check adapter (AI-slop metrics) shipped.** What: new
  adapter for [scb-check](https://github.com/gabeorlanski/scb-check)
  (SlopCodeBench verbosity/erosion model): parses human output into
  ast-grep slop findings (LINT/LOW), erosion findings
  (COMPLEXITY/MEDIUM, cyclomatic + cognitive), and duplicate-structure
  findings (DUPLICATION/MEDIUM); multi-box blocks parse via a
  header→location state machine. JSON output carries aggregates only —
  per-finding detail lives in the human output, hence the parser. Seeded
  repo gained slop.py + dup.py; verifier expectation `scb-check: 3`
  verified `ok` against the real tool (pipx-installed). Category enum
  already had DUPLICATION/COMPLEXITY — no schema change.installer:
  `pipx:scb-check`. Why it matters: fills the identified DRY-proxy gap
  (clone detection) and adds the quantitative anti-slop signal for
  agent-written code; README links SlopCodeBench + the No AI Slop
  manifesto (its resolution 12 is polycheck's thesis).
* **2026-11-24 — reviewer subagent + pre-push gate shipped (0.3.0).** What:
  `polycheck init` writes `polycheck-reviewer` subagent definitions for
  Kilo/OpenCode/Claude (shared body: run via CLI, triage with verdicts, write
  ranked checklist to `polycheck-reports/polycheck-review-checklist.md`,
  persist FALSE-POSITIVEs to `.polycheck.yml` suppress, return compact
  summary only), `--no-agents`/`--agents-only` flags, and
  `--git-hook pre-push` dev-cycle gate (never overwrites existing hooks).
  Host agent paths/formats follow each host's convention (Kilo
  `.kilo/agent/` singular, Claude `.claude/agents/` plural); field names
  should be re-verified against current host docs before advertising
  Kilo/OpenCode agent support publicly. Tests: onboarding characterization
  (configs parse, agents carry contract), no-agents/agents-only, git-hook
  write/protect/validate. Version 0.3.0 released.
* **2026-11-23 — end-to-end install test from PyPI caught a real release bug.**
  Metric: fresh `pipx install --force polycheck` (the published 0.2.0) →
  `polycheck --version`. Before: printed **0.1.0** while the wheel metadata
  said 0.2.0 (hardcoded `__version__` in `__init__.py` missed in the bump).
  Also verified on an unrelated repo (bottle, shallow clone): scan works
  cross-tool (deptry 43 / mypy 54 / ruff 168 findings, sub-2s per tool,
  55 after MEDIUM filter), `--fail-on HIGH` exits 1 on real undefined-name
  findings. Fix: version consistency test (pyproject ↔ `__init__` ↔
  CHANGELOG) + 0.2.1 release. Verdict: KEPT — the E2E install check is now a
  standard post-release step.
* **2026-11-23 — markdown per-rule example cap (plan 5.1), measured.** Metric:
  byte size of `polycheck-report.md` for the same unfiltered scan (`--severity
  INFO --output markdown --tool ruff --tool mypy --tool deptry`) of bottle.
  Before: 16,347 bytes. After: 9,389 bytes (**−43%**), zero information loss
  (exact hidden counts per rule/category, full list stays in the JSON report).
  Verdict: KEPT.
* **2026-11-23 — coverage measurement in a disposable venv.** Metric:
  `pytest --cov=polycheck` (fresh `python3 -m venv` + `pip install -e ".[dev]"`,
  which also validates the from-source dev setup; `--version` correctly
  reports 0.2.1 there). Result: **71% total**. The lowest-covered files are
  exactly the D4 cut targets (base.py installer zoo 45%, sonarless 40%,
  pip-audit 30%, npm-audit 48%) — evidence *for* the simplification pass, not
  for writing more installer tests. Heavy tools are skipped by design.
  Verdict: record.
* **2026-11-23 — eslint adapter verified end to end via local npm.** Metric:
  `verify_tools(tools=['eslint'])` with eslint@latest installed into a scratch
  npm prefix (`npm install --prefix /tmp/... eslint`, PATH-augmented — no
  global install). Result: status `ok`, 1 finding on the seeded repo (the
  unused-variable defect). The `_EXPECTED_FINDINGS["eslint"] = 1` expectation
  is now machine-confirmed. Verdict: record.
* **2026-11-23 — D4 refinement: sonarless opt-in via manual install.** With
  the installer now hint-only, installing sonarless IS the deliberate opt-in;
  running it by default when present is the correct behavior, so no separate
  config flag was added (simpler than the original D4 plan).
* **2026-11-23 — MCP progress notifications shipped.** Spec-standard:
  `polycheck.run` emits `notifications/progress` (0.15 deps → 0.3 scan →
  0.7 scan done → 0.9 reports) when the client passes a progressToken;
  no token → no notifications. Wired via `_call_tool_with_progress`; the
  MCP tool surface stays 2 tools.
* **2026-11-23 — first public release v0.2.0.** What: main fast-forwarded to
  dev, annotated tag `v0.2.0`, Release workflow built and published via
  Trusted Publisher (PyPI pending publisher + GitHub `pypi` environment —
  both configured manually by Philip). Verified: pypi.org JSON API returns
  version 0.2.0 with wheel + sdist. Note: GitHub flagged Node.js 20
  deprecation warnings on actions/checkout@v4, setup-python@v5,
  upload-artifact@v4 — cosmetic; bump action majors when v5/v6 exist.
* **2026-11-23 — baseline + diff + durable suppressions shipped (D2, extends
  5.3).** Hypothesis: the daily-driver gap is "only show me what's new". What
  landed: `polycheck baseline`, `run --diff` (fingerprint baseline in
  `polycheck-reports/`, malformed baseline treated as absent — never crashes
  or hides findings), `.polycheck.yml` `suppress:` (`rule` / `rule@file`),
  MCP `polycheck.run` `diff` param with `baseline` known/new payload, guided
  workflow + triage prompt teach the loop, Claude skill frontmatter fixed
  (MASTERPLAN T1). Tests: runner suppression/baseline units, baseline
  roundtrip, CLI flow (hermetic stub registry — note: Runner now receives
  `default_registry` explicitly from the CLI, which the monkeypatch-based
  tests rely on), MCP diff payloads, meta consistency tests (changelog ↔
  version, template frontmatter). Verdict: KEPT.
* **2026-11-23 — release readiness (2.2).** `release.yml` (trusted
  publishing, `pypi` environment), version bumped 0.1.0 → 0.2.0 with
  CHANGELOG entry, README install block updated. Manual steps for Philip
  recorded above.
* **2026-11-23 — four adapter fixes (RED→GREEN).** Hypothesis: eslint/shellcheck/
  gitleaks/ruff were silently broken (see list above). Metric: new regression
  tests `tests/test_tool_adapters.py` + full suite
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`. Before: 6 of 8 new tests failed
  for the expected reasons; suite 88 passed / 1 failed. After: adapter tests
  8/8; suite 97 passed / 0 failed / 1 skipped; ruff clean. Changes: eslint argv
  de-duplicated, shellcheck gets file args (returns [] when no `*.sh`),
  gitleaks parses `--report-path` temp report with `--no-git` and raises on
  unexpected exit codes, ruff severity mapping (F821/F811 HIGH, E7xx MEDIUM,
  N* INFO). Also fixed env-dependent sonarless test (0.2) and two README
  doc lies (duplicate bullet, gitleaks row). Verdict: KEPT.
* **2026-11-23 — baseline verification of quality gates.** Metric: gate
  results from `ruff check src tests`, `mypy src/polycheck`,
  `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q`. Before: unknown (claims in
  MASTERPLAN dated 2026-07-07: all green, 52 tests). After: ruff clean, mypy
  132 errors, pytest now green. Verdict: record — MASTERPLAN's "all three must
  pass" gate is red on mypy only; the 0.1.0-era results were stale.

## Manual release steps (the agent cannot do these)

1. On pypi.org, create the project `polycheck` as a **pending Trusted
   Publisher**: GitHub owner `Phhofm`, repo `polycheck`, workflow
   `release.yml`, environment `pypi`.
2. After CI is green on `dev` and the branch is merged to `main`:
   `git tag v0.2.0 && git push origin v0.2.0` — the release workflow builds
   and publishes via trusted publishing.

## Open tasks (ordered)

1. ~~Four adapter fixes with regression tests~~ — done 2026-11-23.
2. ~~Env-dependent sonarless test fix~~ — done 2026-11-23.
3. ~~mypy pragmatic config so the strict gate is green~~ — done 2026-11-23.
4. ~~Seeded-defect verifier hardening (1.13)~~ — done; also fixed 6 more
   broken adapters; eslint verified via local npm; knip expectation still
   undecided.
5. ~~Baseline + diff + durable suppressions (D2)~~ — done.
6. ~~README reframe, release pipeline~~ — done; 0.2.0–0.3.3 released and
   verified on PyPI.
7. ~~CI (2.1)~~ — green; GitHub runner capacity caused multi-hour queues
   (2026-11-23/24) — infrastructure, logged below.
8. ~~Reviewer subagent + pre-push gate (0.3.0)~~ — done; two external
   live tests validated the full loop (scan → triage → choice → fix →
   re-scan green).
9. ~~Track buckets, gitleaks gitignore-awareness, reviewer rules
   (0.3.3)~~ — done from the bigger-repo live test (1717 raw → 7 real).
10. ~~extra_args plumbing (0.3.2)~~ — done (meta-finding #4 from the
    colleague loop).
11. ~~Profiles `--profile pr|deep` + hook switch (0.3.4)~~ — done, live
    verified incl. the hook E2E.
12. ~~First structural adapter: tach (0.3.4)~~ — done, seeded expectation
    verified against the real binary.
13. ~~Reviewer "Quality questions" section (0.3.4)~~ — done.
14. ~~Cross-model audit of the heavy adapters (0.3.4)~~ — done against
    real payloads; pip-audit temp-file leak + crash tolerance and the
    semgrep location bug found and fixed; npm-audit/sonarless clean.

## Backlog: 0.3.4+ (profiles & structural adapters)

**Profiles — design decision (2026-11-25):** two named profiles plus the
unchanged default, presets over existing primitives (tool selection,
scoping, gate) — no new engines.

* **`--profile pr`** — for pre-push/PR checks and the hook: same
  applicable fast tools, but **scoping to changed tracked files** (git
  diff vs HEAD or merge-base), gate HIGH. Findings in files that did not
  change are out of scope; a baseline further filters known findings.
* **`--profile deep`** — project-onboarding and periodic full pass: heavy
  tools ON (sonarless, semgrep, pip-audit, npm-audit), structural
  adapters as they land, no gate by default; output feeds triage →
  baseline → suppressions.
* **Default stays as-is** (whole-repo fast scan, MEDIUM gate): it is the
  re-scan-after-sweep confirmation step and the daily scan with baseline
  filtering — a named "dev" profile would be the same thing twice (see
  the design debate in the experiments log).
* The pre-push hook switches to `--profile pr`; `/polycheck` gains a
  mode argument (default dev scan; `deep` on onboarding).

**Structural adapters (deep profile), one per iteration, seeded-verifier
expectation required each (D1):**

* ~~**import-linter or tach** (Python) — circular imports, layer
  violations, modularity~~ — done 2026-11-25: **tach** shipped (JSON
  output beat import-linter's human text; see the 0.3.4 experiment
  entry). dependency-cruiser as the JS/TS counterpart is next.
* **interrogate** — docstring coverage per public symbol
  (documentation coverage, deterministic).
* **ncu / `pip list --outdated`** — dependency drift and deprecation
  (deep profile only, noise-bewusst).
* **osv-scanner** — multi-ecosystem CVE consolidation (opt-in; pip-audit
  + npm-audit cover Python/Node today).
* **fallow** — TS/JS module-graph all-in-one; young project, adopt only
  after verification against real output.
* **ls-lint** — file-naming conventions; YAGNI until requested.
* **Native repo-hygiene mini-check** — giant monolith files (>800 LOC),
  `*.bak`/`temp_*` clutter, orphaned test files; no external dependency,
  on-brand anti-agent-clutter.
* Explicitly rejected for now: radon/lizard (sonarless + scb-check cover
  complexity), jscpd (scb-check covers cross-language clones),
  ncu-as-default (noise), coverage tooling (needs running test suites —
  categorically different; heavy-opt-in later at most).

**Reviewer template — "Quality Questions" section (deep profile):**
Principles that cannot be measured deterministically become checklist
questions for the LLM, never fabricated findings: SRP, SOLID, Law of
Demeter, meaningful names, comments-for-why, design patterns,
observability, scalability. Performance stays out of scope (no runtime
data). Test coverage needs running test suites — heavy-opt-in at most.

**Cross-model audit:** ~~fresh-model audit of the heavy adapters
(sonarless/pip-audit/npm-audit/semgrep) against real CLI/API payloads~~ —
done 2026-11-25 (3 real bugs found and fixed; see the 0.3.4 experiment
entry). The remaining gap: the seeded verifier still skips heavy tools by
design — the audit payloads are pinned as unit tests instead.

**Language gaps / docs:** `.vue`/Svelte/Angular SFCs are not eslint-
scanned (plugin + parser needed) — document the `extra_args` recipe;
CodeRabbit noted as a different lane (LLM review SaaS), not a polycheck
concern.

## Closed / historical notes

* ~~Note (2026-11-24): GitHub Actions runner capacity was constrained
    all day — CI runs queued for hours (macOS starvation overnight, then
    the whole matrix). Local gates + the Release workflow + PyPI serve as
    the verification chain; CI catches up when capacity returns.~~
