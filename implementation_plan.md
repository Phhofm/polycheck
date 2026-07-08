# polycheck — Implementation Plan

This plan supersedes `MASTERPLAN.md` (deleted in task 0.4). It was produced by a
full audit of the codebase on 2026-07-08, including empirical verification of
every suspected bug. It is written so a small LLM coding agent can execute it
task by task without making design decisions.

**Verified state at time of writing:** `ruff check` passes; `mypy` FAILS with
131 errors (strict mode was configured but never green); `pytest -m "not heavy"`
has 1 failing test (environment-dependent); three analyzers (gitleaks,
shellcheck, and the node tools when installed globally) silently return zero
findings on every run.

---

## Global rules for the implementing agent

Follow these rules for EVERY task. Do not skip them.

1. Do ONE task at a time, in order. Finish and verify a task before starting
   the next.
2. After every task, run this exact verification sequence from the repo root
   (inside the project venv — see task 0.1):
   ```bash
   ruff check src tests
   mypy src/polycheck
   pytest -q -m "not heavy"
   ```
   All three must pass (exception: mypy is allowed to fail until task 0.3 is
   complete). If a command fails, fix the failure before moving on. If you
   cannot fix it after 2 attempts, revert your change
   (`git checkout -- <files>`), write the task number + error into
   `IMPLEMENTATION_PROGRESS.md`, and continue with the next task.
3. Make ONE git commit per task, using the commit message given in the task.
4. Never reformat, rename, or "clean up" code that the task does not mention.
   Keep diffs minimal.
5. Never add new runtime dependencies unless a task explicitly says to.
6. Never change the `Finding` JSON schema field names.
7. After each task append a line to `IMPLEMENTATION_PROGRESS.md`:
   `- [x] <task-id> <short result>` (create the file on the first task).

---

# 1. ARCHITECTURAL DECISIONS

**D1 — The architecture stays.** Tool adapters → one `Finding` schema →
Runner → Reporters, with CLI and MCP as thin frontends, is the right shape for
"thin wrapper that hands LLMs a tight report". No rewrite. Everything below is
repair and simplification, not redesign.

**D2 — Correctness before features.** An analyzer wrapper that silently
returns zero findings is worse than no wrapper: it reports "clean" and the
user believes it. Verified broken today: **gitleaks** (writes JSON to a report
file, adapter parses stdout → always empty), **shellcheck** (passed `.` but it
does not accept directories → always empty), **eslint/tsc/knip/depcheck**
(argv is `["eslint", "eslint", ...]` when the binary is on PATH → tool errors
out). These are fixed first, each with a test that would have caught it.

**D3 — Tests must assert detection, not just survival.** The smoke test only
asserts adapters don't crash — that's exactly why D2's bugs shipped. The
verifier seeds each synthetic repo with a known defect; from now on, a seeded
tool that runs and reports zero findings is a FAILURE, not "no-findings".

**D4 — Normalize file paths in ONE place.** Adapters emit whatever their tool
prints (ruff/eslint print absolute paths; shellcheck prints `./x.sh`). Instead
of fixing 16 adapters, the Runner relativizes every `Finding.file` against the
repo root after each tool runs. Adapters stay dumb; the schema promise
("repo-relative POSIX path") is enforced at a single choke point.

**D5 — Config must not lie.** `.polycheck.yml` documents `timeout` and
`extra_args`, but no adapter reads either (every timeout is hardcoded; the
config `timeout` appears only in an error message). Fix: `Tool` gains
`self.timeout` / `self.extra_args` instance attributes with per-class
defaults; the Runner injects config values before each run. Small mechanical
change per adapter; config becomes honest.

**D6 — Delete what nothing calls.** Dead code found: `polycheck/languages/`
package (empty placeholder), `ToolRegistry.applicable()` (only its own test),
`Finding.from_dict()`, module-level `fingerprint()`, `Severity.from_str()`
(only its own test), `Tool.fix_command()` method hook (zero callers — the
`Finding.fix_command` FIELD stays). A committed binary `.depwire/cache.db`
is removed from git.

**D7 — Selection logic lives in `runner.py`.** "Which tools apply / are
missing" currently exists twice: in `Runner._applicable_tools` and in
`cli._missing_tools` — and `mcp_server` imports the private CLI helper
(server → CLI is backwards). The shared logic moves to `runner.py`; CLI and
MCP both import it from there.

**D8 — `mcp_server.py` (928 lines) becomes a package.** Transport, tool
schemas, handlers, summaries, and prompts are separate concerns; splitting
them is the difference between "new teammate productive in an hour" and not.
Code moves verbatim; a compatibility shim keeps `polycheck.mcp_server`
imports working so existing tests pass unchanged.

**D9 — MCP tool names are spec-safe.** Dots in tool names (`polycheck.run`)
are rejected by several MCP hosts (`^[a-zA-Z0-9_-]+$`). Underscore names
become primary (`polycheck_run`); dotted names stay as aliases.

**D10 — mypy gate is pragmatic, then green, then enforced.** `strict = true`
with 131 standing errors is a gate that never gated. Replace with a
non-strict config (`check_untyped_defs`, `no_implicit_optional`,
`warn_unused_ignores`), fix the ~30 real errors, and wire CI so the gate can
never silently rot again. Strictness can be ratcheted later.

**D11 — The token-saving pipeline is the product.** Three features deliver
the original vision (expensive model plans, cheap model executes): cap
repeated per-rule rows in the markdown report; a deterministic
`polycheck-plan.md` fix-plan reporter (no LLM calls — polycheck stays
model-free); and a findings baseline so mature repos see only NEW findings.

**D12 — Publish or it isn't real.** `pipx install polycheck` in the README
currently 404s. CI (lint+types+tests on a 3-OS matrix, plus dogfooding
polycheck on itself) and a PyPI trusted-publishing release workflow are the
highest-leverage credibility steps.

---

# 2. STEP-BY-STEP CHECKLISTS

Milestones are ordered so the repo is never broken between tasks: first make
the gates real, then fix correctness (each with a regression test), then lock
in CI, then remove noise, then restructure, then build product value, then
docs.

---

## Milestone 0 — Make the quality gates real

### 0.1 Set up the dev environment
- [ ] From the repo root: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`.
- [ ] Add `.venv/` to `.gitignore` (new line in the "Build / cache" block).
- [ ] Use this venv for every verification run in this plan.
- Commit: `chore: ignore .venv`

### 0.2 Fix the environment-dependent sonarless test
- **File:** `tests/test_sonarless.py`
- **Why:** `test_sonarless_install_requires_docker` fails on any machine where
  sonarless IS installed, because `install()` returns early from
  `is_installed()` before it ever checks Docker.
- [ ] In `test_sonarless_install_requires_docker`, add
  `monkeypatch.setattr(SonarlessTool, "is_installed", lambda self: False)`
  before calling `install()`.
- [ ] Check the other tests in this file for the same assumption
  (`test_sonarless_install_without_curl_fails` also calls `install()` — add
  the same `is_installed` stub there).
- Verify: `pytest -q tests/test_sonarless.py` passes.
- Commit: `test: stub is_installed in sonarless install tests`

### 0.3 Make mypy pass with a pragmatic config
- **Files:** `pyproject.toml`, then every file mypy still reports.
- [ ] In `pyproject.toml`, replace the `[tool.mypy]` section with:
  ```toml
  [tool.mypy]
  python_version = "3.10"
  check_untyped_defs = true
  no_implicit_optional = true
  warn_unused_ignores = true
  warn_redundant_casts = true
  ```
- [ ] In `[project.optional-dependencies] dev`, add `"types-PyYAML"` and
  `"types-requests"`, then `pip install -e ".[dev]"` again.
- [ ] Run `mypy src/polycheck` and fix every remaining error (~30). Use these
  patterns — do NOT sprinkle `# type: ignore`:
  - Bare `type` annotations → `type[Tool]`; bare `list` → a parametrized type.
    Affected: `cli.py` (`_missing_tools`, `_tool_enabled`, `_language_matches`,
    `_tool_applicable`, `_resolve_install_targets`, `_resolve_named_tools`,
    `_confirm_install`, `_execute_installs`, `_exit_code` — its `findings`
    param is `list[Finding]`), `runner.py` (`_applicable_tools`,
    `_apply_filters`, `_run_one` — all `type` → `type[Tool]`). Import `Tool`
    with `from .tools.base import Tool` where needed.
  - `tools/base.py` `_latest_github_release_assets`: change the return
    annotation to `tuple[str, list[dict[str, Any]]] | tuple[None, str]` and
    add `from typing import Any` if missing.
  - `tools/base.py` `install()`: `cmd` can be `None` when passed to
    `_check_package_manager` — mypy is right. Guard it:
    `if cmd is None: return False, f"no automatic installer for {self.name}"`
    immediately after `cmd = build_install_command(...)`.
  - `tools/hadolint.py` line ~38: don't reassign `dockerfiles` to a
    `list[str]`; use a second variable `paths = [str(p) for p in dockerfiles if p.is_file()]`.
- Verify: full sequence — all three commands now pass. This is the baseline
  for every later task.
- Commit: `fix: pragmatic mypy config and zero standing type errors`

### 0.4 Repo hygiene
- [ ] `git rm --cached .depwire/cache.db` (a binary MCP cache accidentally committed).
- [ ] Append to `.gitignore`: `.depwire/`, `.kilo/`, `.polycheck/`.
- [ ] Delete `MASTERPLAN.md` (`git rm MASTERPLAN.md`) — this plan replaces it.
- Commit: `chore: untrack tool caches, remove superseded MASTERPLAN`

---

## Milestone 1 — Fix the silently broken analyzers (each with a test)

### 1.1 Add an ignore-aware file walker to `detect.py`
- **File:** `src/polycheck/detect.py` — every later task in this milestone uses this.
- [ ] Add at module level:
  ```python
  _IGNORED_DIRS = {
      ".git", "node_modules", ".venv", "venv", ".tox", ".mypy_cache",
      ".ruff_cache", ".pytest_cache", "__pycache__", "dist", "build",
      ".next", "target", ".polycheck", "polycheck-reports",
  }


  def iter_files(repo: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
      """Yield files under ``repo`` whose suffix or exact name is in
      ``suffixes``, skipping vendored and cache directories."""
      stack = [repo]
      while stack:
          current = stack.pop()
          try:
              entries = list(current.iterdir())
          except OSError:
              continue
          for entry in entries:
              if entry.is_dir():
                  if entry.name not in _IGNORED_DIRS:
                      stack.append(entry)
              elif entry.suffix in suffixes or entry.name in suffixes:
                  yield entry


  def any_file(repo: Path, suffixes: tuple[str, ...]) -> bool:
      """True if the repo contains at least one matching file. Stops early."""
      return next(iter_files(repo, suffixes), None) is not None
  ```
  Add `from collections.abc import Iterator` to the imports.
- [ ] Test in `tests/test_detect.py`: tmp repo with only
  `node_modules/x/a.py` → `any_file(repo, (".py",))` is `False`; add
  `src/b.py` → `True`; `iter_files(repo, ("Dockerfile",))` finds an exact-name
  match.
- Commit: `feat: ignore-aware file walker in detect`

### 1.2 Fix gitleaks: parse the report file, scan the working tree
- **File:** `src/polycheck/tools/gitleaks.py`
- **Why (verified):** gitleaks writes JSON only to `--report-path`, never to
  stdout — the adapter parses stdout, so it has NEVER reported a finding.
  Also, `detect` without `--no-git` scans commit history only, so uncommitted
  secrets are invisible and repos without commits scan nothing.
- [ ] Replace `run()` with:
  ```python
  def run(self, repo: Path) -> list[Finding]:
      if shutil.which("gitleaks") is None:
          return []
      with tempfile.TemporaryDirectory(prefix="polycheck-gitleaks-") as tmp:
          report = Path(tmp) / "report.json"
          cmd = [
              "gitleaks", "detect", "--no-git", "--no-banner",
              "--report-format=json", f"--report-path={report}",
              "--source", str(repo),
          ]
          # gitleaks exits 1 when leaks are found; that's normal.
          subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=300)
          if not report.is_file():
              return []
          try:
              data = json.loads(report.read_text(encoding="utf-8"))
          except (OSError, json.JSONDecodeError):
              return []
      ...  # keep the existing parse loop over `data` unchanged
  ```
  Add `import tempfile`. Update `is_applicable` to `return True` (working-tree
  scan needs no `.git`) and fix the module docstring (it already claims
  `--no-git`; now it's true).
- [ ] Test in a new `tests/test_gitleaks_tool.py`: monkeypatch
  `subprocess.run` with a fake that finds `--report-path=` in the argv and
  writes a one-item JSON array to that path; assert `run()` returns one
  CRITICAL finding. A second test: fake writes nothing → `run()` returns `[]`.
- Commit: `fix: gitleaks adapter reads the report file and scans the working tree`

### 1.3 Fix shellcheck: pass files, not a directory
- **File:** `src/polycheck/tools/shellcheck.py`
- **Why (verified):** `shellcheck .` prints `.: is a directory` and checks
  nothing — the adapter has never reported a finding.
- [ ] Rewrite `run()` to enumerate scripts first:
  ```python
  def run(self, repo: Path) -> list[Finding]:
      if shutil.which("shellcheck") is None:
          return []
      from ..detect import iter_files
      scripts = [str(p.relative_to(repo)) for p in iter_files(repo, (".sh", ".bash"))]
      if not scripts:
          return []
      cmd = ["shellcheck", "-f", "gcc", "--severity=style", *scripts]
      out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=300)
      return self._parse(out.stdout + "\n" + out.stderr)
  ```
- [ ] Simplify `is_applicable` to `return any_file(repo, (".sh", ".bash"))`
  (import `any_file` from `..detect`).
- [ ] Test in `tests/test_shellcheck_tool.py`: monkeypatch `subprocess.run` to
  capture argv and return canned gcc-format output; create `tmp/x.sh`; assert
  the argv contains `x.sh` and NOT `"."`, and one finding is parsed.
- Commit: `fix: shellcheck adapter passes script files instead of a directory`

### 1.4 Fix the node-tool argv duplication (eslint, tsc, knip, depcheck)
- **Files:** `src/polycheck/tools/base.py`, `eslint.py`, `tsc.py`, `knip.py`, `depcheck.py`
- **Why (verified):** `binary = "eslint" if which("eslint") else "npx"` then
  `cmd = [binary, "eslint", ...]` runs `eslint eslint …` when the tool is on
  PATH — the tool errors out and the adapter returns `[]`.
- [ ] In `base.py`, add a module-level helper:
  ```python
  def node_tool_command(name: str, args: list[str]) -> list[str] | None:
      """argv for a Node-ecosystem tool: the PATH binary when present,
      otherwise via npx (which prefers the repo-local node_modules copy)."""
      if shutil.which(name):
          return [name, *args]
      if shutil.which("npx"):
          return ["npx", "--yes", name, *args]
      return None
  ```
- [ ] In each of the four adapters, replace the `binary = ...` / `cmd = ...`
  lines with `cmd = node_tool_command("<name>", [<existing args>])` and
  `if cmd is None: return []`. Existing args per tool:
  - eslint: `["--format=json", "."]` — **also drop `--no-warn-ignored`**, it
    only exists in ESLint 9 and makes the whole run fail on ESLint 8 (verified).
  - tsc: `["--noEmit", "--pretty", "false"]`
  - knip: `["--reporter=json", "--no-progress"]`
  - depcheck: `[".", "-q", "--no-dev"]`
- [ ] In the same four adapters, override `is_installed`:
  `return shutil.which(self.name) is not None or shutil.which("npx") is not None`
  (otherwise the Runner skips repos that only have a local node_modules install).
- [ ] Test in `tests/test_node_tools.py`: with `shutil.which` monkeypatched so
  `which("eslint") == "/usr/bin/eslint"`, assert
  `node_tool_command("eslint", ["--format=json", "."]) == ["eslint", "--format=json", "."]`
  (no duplicated name). With `which` returning a path only for `"npx"`, assert
  the command starts with `["npx", "--yes", "eslint"]`. With `which` always
  `None`, assert `None`.
- Commit: `fix: node tool argv duplication and ESLint 8 compatibility`

### 1.5 Normalize finding paths centrally in the Runner
- **Files:** `src/polycheck/runner.py`, `src/polycheck/reporters/sarif_reporter.py`
- **Why:** the `Finding` schema documents repo-relative POSIX paths, but ruff
  and eslint emit absolute paths and shellcheck emits `./x.sh`. Reporters and
  the SARIF output currently work around this inconsistently.
- [ ] In `runner.py`, add a module-level function:
  ```python
  def _relativize(file: str, repo: Path) -> str:
      """Best-effort conversion of a tool-reported path to repo-relative POSIX."""
      p = Path(file)
      if p.is_absolute():
          try:
              p = p.resolve().relative_to(repo)
          except (OSError, ValueError):
              return p.as_posix()
      posix = p.as_posix()
      return posix[2:] if posix.startswith("./") else posix
  ```
- [ ] In `Runner._run_one`, right after `findings = inst.run(self.repo)`, add:
  ```python
  for f in findings:
      if f.file:
          f.file = _relativize(f.file, self.repo)
  ```
- [ ] In `sarif_reporter.py` `_make_location`, replace the
  `uri = f.file if f.file.startswith("/") else f"{repo.name}/{f.file}"` hack
  with `uri = f.file` (paths are now repo-relative).
- [ ] Test in `tests/test_runner.py`: register a fake tool whose `run()`
  returns one finding with an absolute path inside the tmp repo and one with
  `./x.sh`; run the Runner; assert both `file` values are repo-relative POSIX
  with no `./` prefix.
- Commit: `fix: enforce repo-relative POSIX paths at the runner boundary`

### 1.6 Fix ruff severity mapping and per-item fixability
- **File:** `src/polycheck/tools/ruff.py`
- **Why:** every ruff finding is INFO/LOW even for real bug shapes (F821
  undefined name); `fix_command` scans the whole list once per finding (O(n²))
  and marks unfixable findings with a fix command.
- [ ] Add above the class:
  ```python
  def _severity_for_rule(code: str) -> Severity:
      """F (pyflakes) and B (bugbear) rules are real bug shapes; N is naming."""
      if code.startswith(("F", "B")):
          return Severity.MEDIUM
      if code.startswith("N"):
          return Severity.INFO
      return Severity.LOW
  ```
- [ ] In the `run()` loop: `code = item.get("code") or "?"`;
  `severity=_severity_for_rule(code)`; `fixable = item.get("fix") is not None`;
  `fix_command="ruff check --fix ." if fixable else None`. Keep
  `file=item.get("filename")` as-is (task 1.5 relativizes it).
- [ ] Test in `tests/test_ruff_tool.py`: monkeypatch `subprocess.run` to return
  a canned ruff JSON payload with one `F821` item (no `fix`) and one `I001`
  item (with `fix`); assert F821 → MEDIUM, not fixable, no fix_command; I001 →
  LOW, fixable, has fix_command.
- Commit: `fix: ruff severity mapping and per-item fixability`

### 1.7 Fix pip-audit temp file leaking into the user's repo
- **File:** `src/polycheck/tools/pip_audit.py`
- **Why:** `_build_command` writes `.polycheck-pip-audit-reqs.txt` INTO the
  scanned repo and never deletes it.
- [ ] In `_build_command`, replace the repo-local temp file with a system temp
  file: `import tempfile` at the top; then
  ```python
  fd, tmp_path = tempfile.mkstemp(prefix="polycheck-pip-audit-", suffix=".txt", text=True)
  with os.fdopen(fd, "w", encoding="utf-8") as fh:
      fh.write("\n".join(reqs))
  return ["pip-audit", "-r", tmp_path, "--format", "json", "--no-deps"]
  ```
  Add `import os`. (The file lives in the OS temp dir; leaving it there is
  harmless and it is never inside the user's repo.)
- [ ] Remove the now-obsolete `.polycheck-pip-audit-reqs.txt` line from
  `.gitignore`.
- [ ] Test in `tests/test_install.py` or a new test: call
  `PipAuditTool()._build_command(tmp_repo)` on a repo with a `pyproject.toml`
  declaring one dependency and no requirements.txt; assert the `-r` argument
  is NOT inside `tmp_repo`.
- Commit: `fix: pip-audit writes its temp requirements outside the repo`

### 1.8 Fix applicability checks that walk vendored trees
- **Files:** `src/polycheck/tools/ruff.py`, `mypy.py`, `vulture.py`,
  `hadolint.py`, `semgrep.py`
- [ ] ruff/mypy: `return (repo / "pyproject.toml").exists() or any_file(repo, (".py",))`.
- [ ] vulture: `return any_file(repo, (".py",))`.
- [ ] hadolint: `return any_file(repo, ("Dockerfile",)) or (repo / "Dockerfile").exists()`
  and in `run()` replace `repo.glob("**/Dockerfile*")` with
  `iter_files(repo, ("Dockerfile",))` (keep the explicit `repo / "Dockerfile"`
  append). Note `iter_files` matches exact names, so `Dockerfile.dev` variants
  are no longer matched — that is acceptable; note it in the docstring.
- [ ] semgrep: `is_applicable` currently globs every file in the repo just to
  return an effectively-constant answer. Replace the body with `return True`
  (language detection already gates it).
- [ ] Import `any_file` / `iter_files` from `..detect` in each file.
- Verify: full sequence, plus `pytest -q tests/test_detect.py`.
- Commit: `perf: skip vendored and cache dirs in applicability checks`

### 1.9 Fix small CLI bugs
- **File:** `src/polycheck/cli.py`
- [ ] `explain` command: `console.print(f"Install hint: {inst.install_hint}")`
  prints a bound-method repr. Change to `{inst.install_hint()}`.
- [ ] `run` command: `_missing_tools(...)` is called without the loaded
  config, so it suggests installing tools the user disabled. Pass
  `config=cfg` at both call sites in `run` and `_auto_install_missing`
  (thread the `cfg` parameter through `_auto_install_missing`).
- [ ] `run` command: validate `fail_on` up front —
  ```python
  if fail_on.upper() not in Severity.__members__:
      console.print(f"[red]Invalid --fail-on: {fail_on}[/red]")
      raise typer.Exit(2)
  ```
  (import `Severity` at top level of the function or module). Remove the
  silent `return 0` on `KeyError` in `_exit_code`.
- [ ] `run` command: flip `--parallel` to default `True` with a
  `--no-parallel` opt-out: `parallel: bool = typer.Option(True, "--parallel/--no-parallel", ...)`.
- [ ] `run` command UX: after `_print_detected_languages(repo)`, print which
  tools are about to run so long runs aren't silent. Insert after
  `runner = Runner(...)`:
  ```python
  planned = [c.name for c in runner._applicable_tools()]
  if tool:
      planned = [n for n in planned if n in set(tool)]
  console.print("Running: " + ", ".join(sorted(planned)) if planned else "[yellow]No applicable tools installed.[/yellow]")
  ```
- [ ] Test in `tests/test_cli_helpers.py`: `_exit_code` no longer exists a
  silent-invalid path — update/add tests accordingly.
- Commit: `fix: CLI explain hint, config-aware missing tools, fail-on validation, run progress`

### 1.10 MCP correctness: resource URIs, run_id, resource listing
- **Files:** `src/polycheck/mcp_server.py`, `src/polycheck/session.py`
- [ ] **AnyUrl bug:** in `mcp` SDK 1.x the `read_resource` handler receives a
  pydantic `AnyUrl`, and `AnyUrl == str` is always False, so every resource
  read raises `Unknown resource`. At the top of `_read_resource_content`, add
  `uri = str(uri).rstrip("/")` (adjust the signature docstring accordingly).
- [ ] **run_id mismatch:** `_handle_polycheck` mints a `run_id` but
  `write_session_summary` generates its own, so session files can't be
  correlated with runs. In `session.py`, change the signature to
  `def write_session_summary(repo: Path, payload: dict[str, Any], run_id: str | None = None) -> dict[str, str]:`
  and use `run_id = run_id or new_run_id()`. In `_handle_polycheck`, call
  `write_session_summary(repo, summary, run_id=run_id)`.
- [ ] **Incomplete listing:** `_list_resources` lists only 2 of the 4
  documented resources. Add `Resource(...)` entries for
  `polycheck://findings/markdown` (mimeType `text/markdown`) and
  `polycheck://findings/json` (mimeType `application/json`).
- [ ] Tests in `tests/test_mcp_server.py`:
  ```python
  def test_read_resource_accepts_anyurl():
      from pydantic import AnyUrl
      text = mcp_server._read_resource_content(AnyUrl("polycheck://triage/prompt"))
      assert "Triage Rules" in text
  ```
  and in `tests/test_session.py` a test that an explicit `run_id` produces
  `<run_id>.md` in `.polycheck/sessions/`.
- Commit: `fix: MCP resource URIs, session run_id correlation, complete resource listing`

### 1.11 MCP spec-safe tool names (underscores primary, dots as aliases)
- **Files:** `src/polycheck/mcp_server.py`, `src/polycheck/workflows/__init__.py`,
  `tests/test_mcp_server.py`
- [ ] In `_build_tool_definitions`, extract each non-workflow `Tool(...)`
  literal into a tiny helper taking `name: str` (e.g. `_audit_tool(name)`,
  `_list_tools_tool(name)`, `_explain_tool(name)`, `_doctor_tool(name)`,
  `_install_tool(name)`), then register, in this order:
  `polycheck_run`, `polycheck.run`, `polycheck`, `polycheck_audit_run`,
  `polycheck.audit_run`, `polycheck_list_tools`, `polycheck.list_tools`,
  `polycheck_explain_finding`, `polycheck.explain_finding`,
  `polycheck_doctor`, `polycheck.doctor`, `polycheck_install`,
  `polycheck.install`.
- [ ] In `_dispatch_tool`, add the underscore names to `handlers`, mapped to
  the same handler as their dotted twin.
- [ ] Replace `polycheck.run` with `polycheck_run` in
  `_WORKFLOW_TOOL_DESCRIPTION`, `_TRIAGE_PROMPT`, `_next_action` strings, the
  module docstring (mention dotted names as deprecated aliases), and all 3
  occurrences in `workflows/__init__.py` `_SHARED_STEPS`.
- [ ] Update the existing assertions in `tests/test_mcp_server.py` that expect
  dotted names (`"polycheck.run" in payload["next_action"]`, the
  `tools["polycheck.run"].description` checks, the `_dispatch_tool` tests) to
  use `polycheck_run`, and KEEP one test proving the dotted alias still
  dispatches. Add:
  ```python
  def test_tool_names_are_spec_safe():
      import re
      tools = mcp_server._build_tool_definitions()
      assert "polycheck_run" in [t.name for t in tools]
      for t in tools:
          if "." not in t.name:
              assert re.fullmatch(r"[a-zA-Z0-9_-]+", t.name)
  ```
- Commit: `fix: spec-safe MCP tool names with dotted aliases`

### 1.12 Claude Code skill frontmatter + Windows installer suffix
- **Files:** `src/polycheck/workflows/__init__.py`, `src/polycheck/tools/base.py`
- [ ] `CLAUDE_WORKFLOW` lacks the YAML frontmatter Claude Code requires, so
  the generated SKILL.md is not recognized. Replace it with:
  ```python
  CLAUDE_WORKFLOW = f"""---
  name: polycheck
  description: Run the polycheck guided static-analysis workflow (linters, type checkers, CVE and secret scanners) and triage the findings. Use when the user asks to run polycheck, lint the repo, or hunt for bugs efficiently.
  ---

  # Polycheck

  {_SHARED_STEPS}
  """
  ```
  (unindent the string so `---` is at column 0).
- [ ] In `base.py` `_download_and_install_asset`:
  `platform.system() == "windows"` never matches (it returns `"Windows"`).
  Extract `def _target_binary_name(binary: str) -> str: return f"{binary}.exe" if platform.system().lower() == "windows" else binary`
  and use it.
- [ ] Tests: in `tests/test_initializer.py` assert the written SKILL.md starts
  with `---` and contains `name: polycheck`; in `tests/test_install.py`
  monkeypatch `platform.system` → `"Windows"` and assert
  `_target_binary_name("gitleaks") == "gitleaks.exe"`.
- Commit: `fix: Claude skill frontmatter and Windows .exe install suffix`

### 1.13 Make the verifier fail when a seeded defect goes undetected
- **Files:** `src/polycheck/verify.py`, `tests/test_tool_smoke.py`
- **Why (D3):** every bug in tasks 1.2–1.4 passed the smoke test because
  "ran without crashing, found nothing" counted as success.
- [ ] In `_seed_repo`:
  - Change `app.js` content to `const unused = 1;\n` (the current seed uses
    the variable, so eslint finds nothing even when working).
  - Also write `.eslintrc.json` next to `eslint.config.js`:
    `{"rules": {"no-unused-vars": "error"}, "parserOptions": {"ecmaVersion": 2022, "sourceType": "module"}}`
    (ESLint 8 reads only the legacy file, ESLint 9 only the flat one).
  - Change the gitleaks secret: the AWS `EXAMPLEKEY` value is on gitleaks'
    allowlist. Use
    `github_pat = "ghp_9aB8cD7eF6gH5iJ4kL3mN2oP1qR0sT9uV8wX"\n` instead.
- [ ] In `verify.py`, add at module level:
  ```python
  # Tools whose synthetic repo contains a defect they MUST detect.
  SEEDED_DEFECT_TOOLS = {
      "ruff", "mypy", "vulture", "tsc", "eslint", "shellcheck",
      "hadolint", "actionlint", "gitleaks",
  }
  ```
  and in `verify_one`, replace the final return with:
  ```python
  if findings:
      return ToolVerification(..., status="ok", findings=len(findings), ...)
  if tool_cls.name in SEEDED_DEFECT_TOOLS:
      return ToolVerification(..., status="error",
          message="tool ran but did not detect the seeded defect", ...)
  return ToolVerification(..., status="no-findings", ...)
  ```
  (keep all other fields as they are today).
- [ ] `tests/test_tool_smoke.py` needs no change — `status == "error"` already
  fails it. Run it with your locally installed tools and confirm it passes;
  if a tool is not installed it is skipped, which is fine.
- Commit: `test: seeded-defect verification — no-findings is a failure for seeded tools`

---

## Milestone 2 — CI and publishing (lock the gates in)

### 2.1 GitHub Actions CI
- **File (new):** `.github/workflows/ci.yml`
  ```yaml
  name: CI

  on:
    push:
      branches: [main]
    pull_request:

  jobs:
    test:
      strategy:
        fail-fast: false
        matrix:
          os: [ubuntu-latest, macos-latest, windows-latest]
          python: ["3.10", "3.12", "3.13"]
      runs-on: ${{ matrix.os }}
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: ${{ matrix.python }}
        - run: pip install -e ".[dev]"
        - run: ruff check src tests
        - run: mypy src/polycheck
        - run: pytest -q -m "not heavy"

    selfcheck:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: "3.12"
        - run: pip install -e ".[dev]"
        - name: Dogfood polycheck on itself
          run: polycheck run . --tool ruff --tool mypy --fail-on HIGH
  ```
- [ ] If a test fails on Windows for path-separator reasons, fix the test to
  compare `Path` objects, not strings. Do not drop Windows from the matrix.
- Verify: push a branch and confirm all jobs pass (or run the three commands
  locally as the minimum).
- Commit: `ci: lint, type-check, test matrix, and self-check workflows`

### 2.2 PyPI release workflow (trusted publishing)
- **File (new):** `.github/workflows/release.yml`
  ```yaml
  name: Release

  on:
    push:
      tags: ["v*"]

  jobs:
    build:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: "3.12"
        - run: pip install build
        - run: python -m build
        - uses: actions/upload-artifact@v4
          with:
            name: dist
            path: dist/

    publish:
      needs: build
      runs-on: ubuntu-latest
      environment: pypi
      permissions:
        id-token: write
      steps:
        - uses: actions/download-artifact@v4
          with:
            name: dist
            path: dist/
        - uses: pypa/gh-action-pypi-publish@release/v1
  ```
- [ ] Write these MANUAL steps for Philip into `IMPLEMENTATION_PROGRESS.md`
  (the agent cannot do them): (1) on pypi.org create the project `polycheck`
  as a pending Trusted Publisher (GitHub → `Phhofm/polycheck`, workflow
  `release.yml`, environment `pypi`); (2) after Milestone 1 is merged, run
  `git tag v0.2.0 && git push --tags`.
- [ ] In `README.md` Quick Start, change the install block to
  `pipx install "git+https://github.com/Phhofm/polycheck.git"` with a comment
  `# Once published: pipx install polycheck`.
- Verify: `pip install build twine && python -m build && twine check dist/*` → PASSED.
- Commit: `ci: PyPI trusted-publishing release workflow`

---

## Milestone 3 — Delete dead code, make config honest

### 3.1 Remove dead code
- [ ] Delete `src/polycheck/languages/` (empty placeholder package; nothing
  imports it).
- [ ] Delete `ToolRegistry.applicable()` from `registry.py` (the Runner has
  its own filtered version; the registry one is only used by its own test).
  Remove the corresponding test in `tests/test_registry.py`.
- [ ] Delete `Finding.from_dict()` and the module-level `fingerprint()`
  function from `finding.py` (zero callers).
- [ ] Delete `Severity.from_str()` from `finding.py` and its test in
  `tests/test_finding.py` (no adapter uses it; each has an explicit map).
- [ ] Delete the `fix_command()` METHOD from `tools/base.py` and its overrides
  in `ruff.py` and `sonarless.py` (zero callers — careful: the
  `Finding.fix_command` dataclass FIELD stays).
- [ ] In `sonarless.py`, delete the duplicated `_writable_install_dir` and
  import it from `.base` instead.
- [ ] Fix the `fingerprint()` docstring in `finding.py`: it claims cross-tool
  dedupe but the fingerprint includes the tool name. New wording: "Stable
  identity used to drop duplicate rows when the same tool reports the same
  defect twice."
- Verify: full sequence, plus `grep -rn "from_dict\|from_str\|languages import" src/` shows nothing stale.
- Commit: `refactor: remove dead code paths`

### 3.2 Make `timeout` and `extra_args` config real
- **Files:** `src/polycheck/config.py`, `src/polycheck/runner.py`,
  `src/polycheck/tools/base.py`, every adapter in `src/polycheck/tools/`
- **Why (D5):** both are documented and parsed but never reach any adapter.
- [ ] `config.py`: change `timeout: int = 300` to `timeout: int | None = None`
  (None = each tool's own default). Update the class docstring.
- [ ] `tools/base.py`: give `Tool` a class attribute `default_timeout: int = 300`
  and an `__init__`:
  ```python
  def __init__(self) -> None:
      self.timeout: int = self.default_timeout
      self.extra_args: list[str] = []
  ```
- [ ] `semgrep.py` and `sonarless.py`: set `default_timeout = 600` as a class
  attribute; `actionlint.py` and `hadolint.py`: `default_timeout = 120`.
- [ ] `runner.py` `_run_one`, before `inst.run(self.repo)`:
  ```python
  if self.config.timeout is not None:
      inst.timeout = self.config.timeout
  inst.extra_args = list(self.config.extra_args.get(name, []))
  ```
- [ ] In EVERY adapter's `run()`: replace the hardcoded `timeout=300` (or
  120/600) in the main tool `subprocess.run` call with `timeout=self.timeout`,
  and splice `*self.extra_args` into the command right after the tool's fixed
  flags (before any file/`.` arguments). Skip `sonarless.py`'s Docker/API
  helper calls — only its `sonarless scan` subprocess gets `self.timeout`.
- [ ] Test in `tests/test_runner.py`: fake tool records `self.timeout` and
  `self.extra_args` when run; config with `timeout: 42` and
  `extra_args: {fake: ["--x"]}` → both observed.
- Commit: `feat: honor timeout and extra_args from config in every adapter`

### 3.3 SARIF metadata fixes
- **File:** `src/polycheck/reporters/sarif_reporter.py`
- [ ] `informationUri` says `https://github.com/KiloApp2/polycheck` — change
  to `https://github.com/Phhofm/polycheck`.
- [ ] The hardcoded `"version": "0.1.0"` — import
  `from .. import __version__` and use it.
- Commit: `fix: SARIF driver metadata`

---

## Milestone 4 — Structure: one home per concern

### 4.1 Move tool-selection logic out of the CLI
- **Files:** `src/polycheck/runner.py`, `src/polycheck/cli.py`,
  `src/polycheck/mcp_server.py`, `tests/test_cli_helpers.py`
- **Why (D7):** `mcp_server` imports the private `cli._missing_tools`; the
  server should not depend on the CLI.
- [ ] Move `_missing_tools`, `_tool_enabled`, `_language_matches`, and
  `_tool_applicable` from `cli.py` to `runner.py`, renaming `_missing_tools`
  to public `missing_tools` (same signature). Keep them module-level
  functions. Move verbatim otherwise.
- [ ] `cli.py`: `from .runner import missing_tools` and update the two call
  sites; delete the moved functions.
- [ ] `mcp_server.py` `_missing_tools_for_mcp`: replace the
  `from .cli import _missing_tools` import with
  `from .runner import missing_tools`.
- [ ] Update any imports in `tests/test_cli_helpers.py` that reference the
  moved functions to import from `polycheck.runner`.
- Commit: `refactor: tool-selection logic lives in runner, not cli`

### 4.2 Split `mcp_server.py` into a package
- **Files:** new `src/polycheck/mcp/` package; `src/polycheck/mcp_server.py`
  becomes a shim.
- [ ] Create `src/polycheck/mcp/` with (move code VERBATIM, fix imports only):
  - `__init__.py` — `from .server import run_server` re-export.
  - `server.py` — `run_server()` and the handler/resource registration.
  - `tools.py` — `_build_tool_definitions`, `_workflow_tool`, the per-tool
    schema helpers from task 1.11, `_WORKFLOW_TOOL_DESCRIPTION`.
  - `handlers.py` — `_dispatch_tool`, all `_handle_*`, `_dependency_check`,
    `_missing_tools_for_mcp`, `_missing_tool_to_dict`,
    `_missing_system_dependencies`, `_tool_enabled_by_config`,
    `_install_missing_tools`, `_check_docker`, `_repo_from_arguments`,
    `_validate_report_dir`, `_guided_report_dir`, `_text_content`,
    `_read_resource_content`, `_last`, `_latest_session_markdown`, and the
    `_LAST_RUN` dict (it must remain ONE shared dict — `server.py` imports it
    from here).
  - `summaries.py` — `_scan_coverage`, `_audit_summary`, `_workflow_summary`,
    `_next_action`.
  - `prompts.py` — `_TRIAGE_PROMPT`, `_CATEGORY_HELP`.
- [ ] Replace `src/polycheck/mcp_server.py` content with:
  ```python
  """Deprecated location — see polycheck.mcp. Kept for import compatibility."""
  from .mcp.handlers import *  # noqa: F401,F403
  from .mcp.prompts import _CATEGORY_HELP, _TRIAGE_PROMPT  # noqa: F401
  from .mcp.server import run_server  # noqa: F401
  from .mcp.summaries import *  # noqa: F401,F403
  from .mcp.tools import _build_tool_definitions, _workflow_tool  # noqa: F401
  ```
  Note: for the star-imports to re-export underscore names, add an explicit
  `__all__` listing the underscore names at the bottom of `handlers.py` and
  `summaries.py` — OR (simpler) import the needed underscore names explicitly
  in the shim; choose whichever makes `tests/test_mcp_server.py` pass
  UNCHANGED. That test file passing unchanged is the acceptance criterion.
- [ ] `cli.py`: change `from .mcp_server import run_server` (inside the `mcp`
  command) to `from .mcp.server import run_server`, and the `prompt` command's
  `from .mcp_server import _TRIAGE_PROMPT` to `from .mcp.prompts import _TRIAGE_PROMPT`.
- [ ] Move the `"src/polycheck/mcp_server.py" = ["F401"]` per-file-ignore in
  `pyproject.toml` to cover the shim as needed.
- Commit: `refactor: split mcp_server into polycheck.mcp package`

### 4.3 Deduplicate the summary builders
- **File:** `src/polycheck/mcp/summaries.py`
- [ ] `_audit_summary` and `_workflow_summary` share ~25 identical lines.
  Extract:
  ```python
  def _summary_core(findings: list[Finding], results: list[ToolResult]) -> dict[str, Any]:
      by_severity = {
          name: sum(1 for f in findings if f.severity.name == name)
          for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
      }
      by_tool = {
          tool: sum(1 for f in findings if f.tool == tool)
          for tool in sorted({f.tool for f in findings})
      }
      tools_run = [
          {
              "name": r.tool, "status": r.status,
              "finding_count": len(r.findings),
              "duration_sec": round(r.duration_sec, 2), "error": r.error,
          }
          for r in results
      ]
      return {"by_severity": by_severity, "by_tool": by_tool, "tools_run": tools_run}
  ```
  Use it in both functions. The returned dict keys and values must remain
  byte-for-byte identical to before.
- Commit: `refactor: share summary construction between audit and workflow`

---

## Milestone 5 — The token-saving pipeline (core product value)

### 5.1 Cap per-rule examples in the markdown report
- **File:** `src/polycheck/reporters/markdown_reporter.py`
- **Why:** 400 identical `E501` rows is exactly the token waste polycheck
  exists to prevent.
- [ ] Add module constant `MAX_EXAMPLES_PER_RULE = 5`. In
  `_category_findings_table`, group the category's items by `(tool, rule)`
  (preserve current ordering: severity desc, tool, file). For each group
  render at most `MAX_EXAMPLES_PER_RULE` rows; when a group is larger, follow
  its rows with a single line:
  `| … | \`{tool}\` | \`{rule}\` | — | _…and {n} more; see polycheck-report.json_ |`
  Keep the existing per-category `cap` of 50 as an outer bound.
- [ ] Test in `tests/test_reporters.py`: 8 findings with one tool+rule →
  markdown contains exactly 5 location rows for the rule and the string
  `and 3 more`.
- Commit: `feat: cap per-rule examples in markdown report to save LLM tokens`

### 5.2 Deterministic fix-plan reporter (`polycheck-plan.md`)
- **File (new):** `src/polycheck/reporters/plan_reporter.py`; edit
  `src/polycheck/reporters/__init__.py`
- **Why (D11):** the original vision — hand a cheap model an ordered, atomic
  task list generated deterministically, with no LLM calls.
- [ ] Implement `render(repo, findings, results, *, report_dir) -> list[Path]`
  (same signature as the other reporters) writing `polycheck-plan.md`:
  1. Header: repo path, total findings, then verbatim:
     ```
     ## Rules
     - Do one task at a time, in order.
     - After each task run the listed verification command; it must pass.
     - Make one commit per task with the given message.
     - Do not refactor, reformat, or fix anything a task does not mention.
     ```
  2. Tasks ordered by severity (CRITICAL first), then category, then tool.
     Findings with the same `(tool, rule)` merge into ONE task listing all
     locations.
  3. Each task:
     ```
     ### Task <n>: <tool> <rule> — <first finding message>
     - Severity: <severity> | Category: <category>
     - Locations: <file:line>, <file:line>, …
     - Docs: <doc_url if present>
     - Fix: <fix_command if fixable, otherwise "manual — edit each location so the rule no longer fires">
     - Verify: polycheck run . --tool <tool> --severity <severity>  (expect this rule gone)
     - Commit: fix(<tool>): resolve <rule> (<count> locations)
     ```
- [ ] Register `"plan": plan_reporter.render` in `REPORTERS`
  (`reporters/__init__.py`). Leave the default `output.formats` unchanged;
  document `formats: [markdown, json, sarif, plan]` in the README config
  example.
- [ ] In `workflows/__init__.py` `_SHARED_STEPS`, add a step: "For large
  finding sets, generate and read `polycheck-plan.md` (config format `plan`)
  and execute it task by task instead of re-deriving an order."
- [ ] Test `tests/test_plan_reporter.py`: 3 findings (two same tool+rule, one
  CRITICAL from another tool) → CRITICAL is Task 1, the pair merges into one
  task with two locations, file written under `report_dir`.
- Commit: `feat: deterministic fix-plan reporter for cheap-model execution`

### 5.3 Findings baseline (`polycheck baseline`)
- **Files:** new `src/polycheck/baseline.py`; edits in `cli.py` and
  `src/polycheck/mcp/handlers.py`; new `tests/test_baseline.py`
- **Why:** first run on a mature repo floods hundreds of findings; a baseline
  records current fingerprints so later runs surface only NEW ones.
- [ ] `baseline.py`:
  ```python
  """Baseline — suppress known findings so runs only surface new ones."""
  from __future__ import annotations

  import json
  from pathlib import Path

  from .finding import Finding

  BASELINE_NAME = ".polycheck-baseline.json"


  def baseline_path(repo: Path) -> Path:
      return repo / BASELINE_NAME


  def write_baseline(repo: Path, findings: list[Finding]) -> Path:
      path = baseline_path(repo)
      payload = {"version": 1, "fingerprints": sorted({f.fingerprint() for f in findings})}
      path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
      return path


  def load_baseline(repo: Path) -> set[str]:
      path = baseline_path(repo)
      if not path.is_file():
          return set()
      try:
          payload = json.loads(path.read_text(encoding="utf-8"))
      except (OSError, ValueError):
          return set()
      fingerprints = payload.get("fingerprints", [])
      return set(fingerprints) if isinstance(fingerprints, list) else set()


  def apply_baseline(findings: list[Finding], known: set[str]) -> list[Finding]:
      if not known:
          return findings
      return [f for f in findings if f.fingerprint() not in known]
  ```
- [ ] `cli.py`: add a `baseline` command modeled on `run` — same pipeline, no
  severity filter, then `write_baseline` and print path + count. Add
  `--no-baseline` flag to `run`; by default `run` loads the baseline and
  applies it AFTER dedupe, BEFORE severity filtering, printing
  `(N known findings suppressed by .polycheck-baseline.json)` when N > 0.
- [ ] MCP: in `_handle_polycheck` and `_handle_audit_run`, apply the baseline
  the same way and add `"baseline_suppressed": N` to the summary dict.
- [ ] Tests: write/load/apply round-trip; corrupted file → empty set; `run`
  integration via a fake tool.
- [ ] Document under README Configuration.
- Commit: `feat: findings baseline to surface only new issues`

---

## Milestone 6 — Documentation that tells the truth

### 6.1 Fix documentation lies
- **Files:** `README.md`, `CHANGELOG.md`
- [ ] README: the sentence "…so two tools reporting the same defect converge
  to one row" is false (fingerprint includes the tool name). Replace with:
  "used to drop duplicate rows when the same tool reports the same defect
  twice (e.g. across re-runs)."
- [ ] README ~lines 242–250: the bullet "`sonarless` requires Docker…" appears
  twice in a row — delete one copy.
- [ ] README "What You Get": default formats are markdown + json; SARIF is
  written only when configured. Say so.
- [ ] README gitleaks row in the Tool Matrix: it scans the **working tree**
  (task 1.2 uses `--no-git`); update "Secrets in working tree + git history"
  accordingly.
- [ ] README configuration example: `timeout` is optional (per-tool defaults
  otherwise), and `formats` may include `plan`.
- [ ] CHANGELOG.md: the entire 0.1.0 entry is pasted twice — delete everything
  from the second "Initial MVP" line to the end of the file.
  Verify: `grep -c "Initial MVP" CHANGELOG.md` prints `1`.
- [ ] README "Self-audit" block: delete it, or re-run `polycheck run .` in
  this session and update the "Last verified" line honestly.
- Commit: `docs: fix dedupe claim, duplicates, and format defaults`

### 6.2 README quickstart + cheap-model workflow section
- **File:** `README.md`
- [ ] Directly under the tagline, add a "30-second start":
  ```bash
  pipx install "git+https://github.com/Phhofm/polycheck.git"
  polycheck init --host all --scope global
  # restart your assistant, then type:  /polycheck
  ```
- [ ] Add the CI badge:
  `![CI](https://github.com/Phhofm/polycheck/actions/workflows/ci.yml/badge.svg)`
- [ ] New short section "Using polycheck with small/cheap models": run
  `/polycheck` → assistant triages the report → for big backlogs hand
  `polycheck-plan.md` (format `plan`) to a cheap model to execute task by task.
- [ ] Update all `polycheck.run` tool-name references to `polycheck_run`.
- Commit: `docs: 30-second quickstart, cheap-model workflow, name updates`

### 6.3 CONTRIBUTING.md
- **File (new):** `CONTRIBUTING.md` with exactly these sections:
  - Dev setup: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`.
  - Quality gates: the three-command verification sequence, plus
    `polycheck run . --tool ruff --tool mypy --fail-on HIGH`.
  - How to add a tool adapter: copy `src/polycheck/tools/depcheck.py`; required
    class attributes (`name`, `category`, `languages`, `installer`,
    optionally `default_timeout`), the two required methods
    (`is_applicable`, `run`); every adapter that can detect a seeded defect
    must be added to `SEEDED_DEFECT_TOOLS` in `verify.py` with a matching
    seed in `_seed_repo`; and every adapter needs a canned-output parse test
    (point to `tests/test_ruff_tool.py` as the model).
  - Release: bump `pyproject.toml` version, update `CHANGELOG.md`, tag
    `vX.Y.Z`, push tags.
- Commit: `docs: add CONTRIBUTING.md`

### 6.4 (Optional, last) Claude Code plugin manifest
- **Files (new):** `claude-plugin/.claude-plugin/plugin.json`,
  `claude-plugin/skills/polycheck/SKILL.md`, `scripts/sync_plugin_skill.py`,
  `.claude-plugin/marketplace.json`, README section.
- [ ] `plugin.json`:
  ```json
  {
    "name": "polycheck",
    "description": "Static-first code analysis: run local analyzers, hand the LLM a tight triage report.",
    "version": "0.2.0",
    "mcpServers": {
      "polycheck": {
        "command": "polycheck",
        "args": ["mcp"]
      }
    }
  }
  ```
- [ ] `scripts/sync_plugin_skill.py` writes `CLAUDE_WORKFLOW` (from
  `polycheck.workflows`) to `claude-plugin/skills/polycheck/SKILL.md`; run it
  to generate the file; mention it in CONTRIBUTING so the two never drift.
- [ ] README section "Install as a Claude Code plugin" documenting
  `/plugin marketplace add Phhofm/polycheck` + `/plugin install polycheck`;
  check current Claude Code docs for the exact `marketplace.json` schema and
  mark the section "experimental" if unsure.
- Verify: `python scripts/sync_plugin_skill.py && git diff --exit-code claude-plugin/`
  succeeds when run twice.
- Commit: `feat: Claude Code plugin manifest bundling MCP server and skill`

---

## Explicitly OUT of scope (do not do these)

- Do NOT add LLM API calls to polycheck. It stays model-free by design.
- Do NOT rewrite the MCP server on FastMCP; the low-level API works and is tested.
- Do NOT add new analyzers (Go/Rust native tools are future work).
- Do NOT change the `Finding` schema field names or SARIF structure.
- Do NOT introduce new abstractions beyond what a task specifies.

## Order and dependencies

Milestones run strictly in order. Within a milestone, tasks run in the order
listed. Hard dependencies: 1.1 before 1.2/1.3/1.8 (walker); 1.11 before 6.2
(tool names in README); 3.2 before any adapter edit that mentions
`self.timeout`/`self.extra_args`; 4.2 before 4.3 and 5.3's MCP edits
(`polycheck/mcp/` paths); 2.1 before 6.2 (CI badge); 1.12 before 6.4 (skill
frontmatter).
