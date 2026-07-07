# polycheck — Implementation Masterplan

This is a step-by-step implementation plan for improving polycheck. It is written
so that a small LLM coding agent (e.g. qwen3.5-9b) can execute it task by task
without making design decisions. Every task states: the goal, the exact files to
touch, the exact change, how to verify it, and the commit message to use.

**Current state (verified 2026-07-07):** version 0.1.0, ~7000 lines of Python,
52+ passing tests, clean architecture (Tool adapters → Finding schema →
reporters → CLI/MCP). NOT yet published on PyPI. No CI. Several concrete bugs
listed in Phase 1.

---

## Global rules for the implementing agent

Follow these rules for EVERY task. Do not skip them.

1. Do ONE task at a time, in order. Finish and verify a task before starting
   the next.
2. After every task, run this exact verification sequence from the repo root:
   ```bash
   ruff check src tests
   mypy src/polycheck
   pytest -q
   ```
   All three must pass. If a command fails, fix the failure before moving on.
   If you cannot fix it after 2 attempts, revert your change
   (`git checkout -- <files>`) and write the task number + the error into
   `MASTERPLAN_PROGRESS.md`, then continue with the next task.
3. Make ONE git commit per task, using the commit message given in the task.
4. Never reformat, rename, or "clean up" code that the task does not mention.
   Keep diffs minimal.
5. Never add new runtime dependencies unless a task explicitly says to.
6. Never change the `Finding` JSON schema field names — external consumers
   (reports, SARIF, LLM prompts) depend on them.
7. Track progress: after each task append a line to `MASTERPLAN_PROGRESS.md`:
   `- [x] T<number> <short result>` (create the file on first task).

---

## Phase 1 — Bug fixes (do these first)

### T1. Add required YAML frontmatter to the Claude Code skill template

**Why:** Claude Code skills (`SKILL.md`) require YAML frontmatter with `name`
and `description`. The current template has none, so the generated
`.claude/skills/polycheck/SKILL.md` is not recognized as a skill. This breaks
the main advertised workflow for Claude Code users.

**File:** `src/polycheck/workflows/__init__.py`

**Change:** Replace the `CLAUDE_WORKFLOW` definition with:

```python
CLAUDE_WORKFLOW = f"""---
name: polycheck
description: Run the polycheck guided static-analysis workflow (linters, type checkers, CVE and secret scanners) and triage the findings. Use when the user asks to run polycheck, lint the repo, do a static analysis pass, or hunt for bugs efficiently.
---

# Polycheck

{_SHARED_STEPS}
"""
```

**Also:** In `tests/test_initializer.py`, add a test that asserts the written
`SKILL.md` starts with `---` and contains `name: polycheck` and
`description:`. Model it on the existing tests in that file.

**Verify:** standard sequence, plus:
```bash
python -c "from polycheck.workflows import CLAUDE_WORKFLOW; assert CLAUDE_WORKFLOW.startswith('---'); assert 'name: polycheck' in CLAUDE_WORKFLOW; print('ok')"
```

**Commit:** `fix: add required YAML frontmatter to Claude Code skill template`

---

### T2. Fix MCP resource reads failing with AnyUrl URIs

**Why:** In `mcp` SDK 1.x, the `@server.read_resource()` handler receives a
pydantic `AnyUrl`, not a `str`. `_read_resource_content` compares `uri ==
"polycheck://triage/prompt"` — an `AnyUrl` never equals a `str`, so every
resource read raises `Unknown resource`. Tests pass only because they call
`_read_resource_content` directly with strings.

**File:** `src/polycheck/mcp_server.py`

**Change 1:** At the top of `_read_resource_content`, normalize the input:

```python
def _read_resource_content(uri: str) -> str:
    """Read content from an MCP resource URI."""
    uri = str(uri).rstrip("/")
```

(keep the rest of the function unchanged; the existing comparisons now work).

**Change 2:** In `run_server()`, the inner `_read_resource(uri)` handler:
pass `str(uri)` to `_read_resource_content` explicitly.

**Also:** In `tests/test_mcp_server.py`, add a test that calls
`_read_resource_content` with a pydantic URL object:

```python
def test_read_resource_accepts_anyurl():
    from pydantic import AnyUrl
    from polycheck import mcp_server
    text = mcp_server._read_resource_content(AnyUrl("polycheck://triage/prompt"))
    assert "Triage Rules" in text
```

**Verify:** standard sequence.

**Commit:** `fix: normalize AnyUrl resource URIs in MCP server`

---

### T3. Give MCP tools spec-safe primary names (no dots)

**Why:** Several MCP clients and LLM APIs restrict tool names to
`^[a-zA-Z0-9_-]+$` (no dots). Names like `polycheck.run` get rejected or
silently sanitized by some hosts. Keep the dotted names as compatibility
aliases, but make underscore names the primary ones.

**File:** `src/polycheck/mcp_server.py`

**Change 1:** In `_build_tool_definitions()`, register these tools (underscore
name first in the list, dotted alias kept):
- `polycheck_run` (primary) and keep `polycheck.run` + `polycheck` as aliases
- `polycheck_audit_run` and keep `polycheck.audit_run`
- `polycheck_list_tools` and keep `polycheck.list_tools`
- `polycheck_explain_finding` and keep `polycheck.explain_finding`
- `polycheck_doctor` and keep `polycheck.doctor`
- `polycheck_install` and keep `polycheck.install`

For the workflow tool this means calling the existing `_workflow_tool(name)`
helper for each name. For the other tools, extract each `Tool(...)` definition
into a small helper function that takes `name: str` so the definition is not
duplicated, e.g. `_audit_tool(name)`, `_list_tools_tool(name)`, etc.

**Change 2:** In `_dispatch_tool`, add the underscore names to the `handlers`
dict, mapped to the same handler functions as their dotted twins.

**Change 3:** Update `_WORKFLOW_TOOL_DESCRIPTION`, `_TRIAGE_PROMPT`, and the
module docstring to reference `polycheck_run` instead of `polycheck.run`
(mention the dotted names as deprecated aliases in the module docstring only).

**Change 4:** In `src/polycheck/workflows/__init__.py` `_SHARED_STEPS`,
replace `polycheck.run` with `polycheck_run` (3 occurrences).

**Also:** In `tests/test_mcp_server.py`, add:

```python
def test_tool_names_are_spec_safe():
    import re
    from polycheck import mcp_server
    tools = mcp_server._build_tool_definitions()
    primary = [t.name for t in tools if "." not in t.name]
    assert "polycheck_run" in primary
    for t in tools:
        if "." not in t.name:
            assert re.fullmatch(r"[a-zA-Z0-9_-]+", t.name)
```

And a test that `_dispatch_tool("polycheck_run", {...})` and
`_dispatch_tool("polycheck.run", {...})` reach the same handler (you can
assert both return an error payload for a nonexistent repo path, i.e. both are
routed rather than raising `Unknown tool`).

**Verify:** standard sequence.

**Commit:** `fix: use spec-safe MCP tool names, keep dotted aliases`

---

### T4. Fix Windows binary suffix in GitHub-release installer

**Why:** In `src/polycheck/tools/base.py`, `_download_and_install_asset` has
`if platform.system() == "windows"`, but `platform.system()` returns
`"Windows"` (capitalized). The `.exe` suffix is never applied on Windows.

**File:** `src/polycheck/tools/base.py`

**Change:** In `_download_and_install_asset`, replace:
```python
target_name = f"{binary}.exe" if platform.system() == "windows" else binary
```
with:
```python
target_name = f"{binary}.exe" if platform.system().lower() == "windows" else binary
```

**Also:** Add a unit test in `tests/test_install.py` that monkeypatches
`platform.system` to return `"Windows"` and asserts the computed target name
ends with `.exe`. If `_download_and_install_asset` is hard to call directly
(it downloads), extract the one-line name computation into a helper
`_target_binary_name(binary: str) -> str` and test that helper instead.

**Verify:** standard sequence.

**Commit:** `fix: apply .exe suffix on Windows in GitHub-release installer`

---

### T5. Reuse the workflow run_id in session summaries

**Why:** `_handle_polycheck` in `mcp_server.py` creates a `run_id` like
`20260707T120000Z-ab12cd34`, but `write_session_summary` in `session.py`
generates its OWN id via `new_run_id()`. The session files under
`.polycheck/sessions/` are therefore named differently from the run's
`run_id`, which makes runs impossible to correlate.

**Files:** `src/polycheck/session.py`, `src/polycheck/mcp_server.py`

**Change 1:** In `session.py`, change the signature to
`def write_session_summary(repo: Path, payload: dict[str, Any], run_id: str | None = None) -> dict[str, str]:`
and inside replace `run_id = new_run_id()` with
`run_id = run_id or new_run_id()`.

**Change 2:** In `mcp_server.py` `_handle_polycheck`, call
`write_session_summary(repo, summary, run_id=run_id)`.

**Also:** In `tests/test_session.py`, add a test that passes an explicit
`run_id` and asserts the returned markdown path filename is
`<run_id>.md`.

**Verify:** standard sequence.

**Commit:** `fix: correlate session summary filenames with workflow run_id`

---

### T6. Make ruff findings use repo-relative paths and per-item fix data

**Why:** Three defects in `src/polycheck/tools/ruff.py`:
1. `file=item.get("filename")` — ruff emits ABSOLUTE paths, but the `Finding`
   schema documents repo-relative POSIX paths (all reporters and the LLM
   prompt rely on that).
2. `fix_command=... if any(it.get("fix") for it in items)` — this scans the
   whole list once per finding (O(n²)) and attaches a fix command to findings
   that are not themselves fixable.
3. Severity is INFO/LOW for everything, but ruff `F` rules (e.g. F821
   undefined name, F811 redefinition) are real bug shapes.

**File:** `src/polycheck/tools/ruff.py`

**Change:** Rewrite the loop body of `run()` as follows:

```python
        findings: list[Finding] = []
        for item in items:
            loc = item.get("location", {})
            code = item.get("code") or "?"
            filename = item.get("filename")
            if filename:
                try:
                    filename = Path(filename).resolve().relative_to(repo.resolve()).as_posix()
                except ValueError:
                    filename = Path(filename).as_posix()
            fixable = item.get("fix") is not None
            findings.append(
                Finding(
                    tool=self.name,
                    rule=code,
                    severity=_severity_for_rule(code),
                    category=self.category,
                    message=item.get("message", ""),
                    file=filename,
                    line=loc.get("row"),
                    column=loc.get("column"),
                    fixable=fixable,
                    fix_command="ruff check --fix ." if fixable else None,
                    doc_url=f"https://docs.astral.sh/ruff/rules/{code.lower()}",
                    raw=item,
                )
            )
        return findings
```

And add this module-level helper above the class:

```python
def _severity_for_rule(code: str) -> Severity:
    """Map ruff rule prefixes to polycheck severities.

    F (pyflakes) rules are real bug shapes; E/W are style; N is naming.
    """
    if code.startswith("F"):
        return Severity.MEDIUM
    if code.startswith("B"):
        return Severity.MEDIUM
    if code.startswith("N"):
        return Severity.INFO
    return Severity.LOW
```

**Also:** Add `tests/test_ruff_tool.py` with a test that monkeypatches
`subprocess.run` to return a canned ruff JSON payload containing one `F821`
item with an absolute filename, and asserts: severity is MEDIUM, `file` is
repo-relative POSIX, `fixable` matches the item's own `fix` field.

**Verify:** standard sequence.

**Commit:** `fix: ruff adapter paths, severity mapping, and per-item fixability`

---

### T7. Stop applicability globs from walking node_modules and virtualenvs

**Why:** `RuffTool.is_applicable` uses `any(repo.glob("**/*.py"))`, and other
adapters do the same for their extensions. On a big repo this recursively
walks `node_modules/`, `.venv/`, `.git/` just to answer a yes/no question.

**Files:** `src/polycheck/detect.py`, then every tool adapter that uses a
recursive glob in `is_applicable` (check `ruff.py`, `mypy.py`, `vulture.py`,
`shellcheck.py`, `hadolint.py`, `actionlint.py`, and any others you find with
`grep -rn 'glob("\*\*' src/polycheck/tools/`).

**Change 1:** In `detect.py`, add (reuse the ignore set already there if one
exists — check first, and if `detect.py` already has an equivalent skip-list
walker, use that instead of adding a new one):

```python
_IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", ".tox", ".mypy_cache",
    ".ruff_cache", "__pycache__", "dist", "build", ".next", "target",
}


def any_file_with_suffix(repo: Path, suffixes: tuple[str, ...]) -> bool:
    """True if the repo contains at least one file with one of ``suffixes``,
    skipping vendored/cache directories. Stops at the first match."""
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
                return True
    return False
```

**Change 2:** In each adapter, replace the recursive glob with a call to this
helper, e.g. in `ruff.py`:

```python
from ..detect import any_file_with_suffix

    def is_applicable(self, repo: Path) -> bool:
        return (repo / "pyproject.toml").exists() or any_file_with_suffix(repo, (".py",))
```

Adapt per tool (`.sh` for shellcheck, `Dockerfile` for hadolint, etc. — keep
each adapter's existing semantics, only change HOW files are found).

**Also:** Add a test in `tests/test_detect.py`: create a tmp repo containing
only `node_modules/x/a.py` → `any_file_with_suffix(repo, ('.py',))` is False;
add `src/b.py` → True.

**Verify:** standard sequence.

**Commit:** `perf: skip vendored and cache dirs in applicability checks`

---

### T8. Fix documentation lies: dedupe claim, README duplicate, CHANGELOG duplicate

**Why:**
1. README says a fingerprint means "two tools reporting the same defect
   converge to one row", and `finding.py`'s `fingerprint()` docstring says
   "same defect seen by two tools" — but the fingerprint INCLUDES the tool
   name, so cross-tool dedupe never happens. The behavior (tool-scoped dedupe)
   is fine; the docs are wrong.
2. README lines ~242–244: the bullet "`sonarless` requires Docker…" appears
   twice in a row.
3. CHANGELOG.md: the entire 0.1.0 entry is pasted twice (a second copy starts
   at "Initial MVP" around line 36).

**Files:** `README.md`, `CHANGELOG.md`, `src/polycheck/finding.py`

**Changes:**
1. In `README.md`, replace the sentence "A finding has a `fingerprint` of
   `(tool, rule, file, line, column)`, so two tools reporting the same defect
   converge to one row." with: "A finding has a `fingerprint` of
   `(tool, rule, file, line, column)`, used to drop duplicate rows when the
   same tool reports the same defect twice (e.g. across re-runs or overlapping
   invocations)."
2. In `finding.py`, fix the `fingerprint()` docstring the same way (it
   deduplicates within a tool, not across tools).
3. In `README.md`, delete the duplicated sonarless bullet (keep one copy).
4. In `CHANGELOG.md`, delete everything from the second "Initial MVP" line to
   the end of the file, keeping only the first, fuller 0.1.0 entry.

**Verify:** standard sequence, plus visually: `grep -c "Initial MVP" CHANGELOG.md` prints `1`.

**Commit:** `docs: fix dedupe description, remove duplicated README/CHANGELOG text`

---

## Phase 2 — CI and publishing (make it real for other people)

### T9. Add GitHub Actions CI

**Why:** A static-analysis tool with no CI cannot credibly ask users to trust
it. CI must run lint, types, tests on all supported OS/Python versions, and
dogfood polycheck on itself.

**File (new):** `.github/workflows/ci.yml`

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

**Note:** If `pytest -m "not heavy"` fails on Windows for path-separator
reasons, fix the test (use `Path` comparisons, not string comparisons) — do
not exclude Windows from the matrix. If a test failure is genuinely
OS-specific tool absence, mark that test with
`@pytest.mark.skipif(shutil.which("<tool>") is None, reason="tool not installed")`.

**Verify:** `git push` a branch and confirm all jobs pass on GitHub, or run
locally: `pip install -e ".[dev]" && ruff check src tests && mypy src/polycheck && pytest -q -m "not heavy"`.

**Commit:** `ci: add lint, type-check, test matrix, and self-check workflows`

---

### T10. Add a PyPI release workflow (trusted publishing)

**Why:** `pipx install polycheck` in the README currently fails — the package
is NOT on PyPI (verified: 404). The name is free. Publishing is the single
highest-impact usability improvement.

**File (new):** `.github/workflows/release.yml`

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

**Manual steps for the human (Philip) — write these into
`MASTERPLAN_PROGRESS.md` as a reminder, the agent cannot do them:**
1. On pypi.org: create the project `polycheck` as a "pending publisher"
   (Trusted Publishing → GitHub → repo `Phhofm/polycheck`, workflow
   `release.yml`, environment `pypi`).
2. `git tag v0.1.0 && git push --tags` after Phase 1 is merged.

**Also:** In `README.md`, until the package is live, change the Quick Start
install block to:

```bash
pipx install "git+https://github.com/Phhofm/polycheck.git"
# Once published: pipx install polycheck  (or: uv tool install polycheck)
```

After the first successful publish, restore `pipx install polycheck` as the
primary command and mention `uvx polycheck@latest mcp` as a no-install way to
run the MCP server.

**Verify:** `python -m build` succeeds locally and `twine check dist/*` (add
`pip install build twine` first) reports PASSED.

**Commit:** `ci: add PyPI trusted-publishing release workflow`

---

## Phase 3 — Code organization (keep behavior identical)

### T11. Split mcp_server.py into a package

**Why:** `mcp_server.py` is 928 lines mixing transport setup, tool schemas,
handlers, summary builders, and the triage prompt. Splitting makes each part
testable and reviewable.

**Files:** Create `src/polycheck/mcp/` with:
- `__init__.py` — re-export `run_server` (`from .server import run_server`).
- `server.py` — `run_server()`, handler registration, resource listing.
- `tools.py` — `_build_tool_definitions`, `_workflow_tool`, per-tool schema helpers.
- `handlers.py` — `_dispatch_tool`, `_handle_*`, `_dependency_check`,
  `_install_missing_tools`, `_check_docker`, `_LAST_RUN` state.
- `summaries.py` — `_scan_coverage`, `_audit_summary`, `_workflow_summary`,
  `_next_action`.
- `prompts.py` — `_TRIAGE_PROMPT`, `_CATEGORY_HELP`.

Keep `src/polycheck/mcp_server.py` as a thin compatibility shim:

```python
"""Deprecated location — see polycheck.mcp. Kept for import compatibility."""
from .mcp.handlers import *  # noqa: F401,F403
from .mcp.prompts import _CATEGORY_HELP, _TRIAGE_PROMPT  # noqa: F401
from .mcp.server import run_server  # noqa: F401
from .mcp.summaries import *  # noqa: F401,F403
from .mcp.tools import _build_tool_definitions, _workflow_tool  # noqa: F401
```

**Rules:** Move code verbatim — no logic changes, no renames. Fix only the
imports. `tests/test_mcp_server.py` must keep passing UNCHANGED (it imports
`polycheck.mcp_server`); that is the acceptance criterion. Check `cli.py` for
`from .mcp_server import run_server` and update it to
`from .mcp.server import run_server`.

**Note on `_LAST_RUN`:** it must remain a single shared dict. Put it in
`handlers.py` and have `server.py` import it from there.

**Verify:** standard sequence (all existing tests pass without edits).

**Commit:** `refactor: split mcp_server into polycheck.mcp package`

---

### T12. Deduplicate _audit_summary and _workflow_summary

**Why:** The two functions in `summaries.py` share ~25 identical lines
(by_severity, by_tool, tools_run construction).

**File:** `src/polycheck/mcp/summaries.py`

**Change:** Extract:

```python
def _summary_core(findings: list, results: list) -> dict:
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
            "name": r.tool,
            "status": r.status,
            "finding_count": len(r.findings),
            "duration_sec": round(r.duration_sec, 2),
            "error": r.error,
        }
        for r in results
    ]
    return {"by_severity": by_severity, "by_tool": by_tool, "tools_run": tools_run}
```

Then in both summary functions, replace the three duplicated blocks with
`core = _summary_core(findings, results)` and use
`core["by_severity"]` etc. The returned dict keys and values must remain
byte-for-byte identical to before.

**Verify:** standard sequence.

**Commit:** `refactor: share summary construction between audit and workflow`

---

## Phase 4 — The token-saving pipeline (core product value)

### T13. Cap per-rule examples in the markdown report

**Why:** The markdown report is what the LLM reads. A repo with 400 identical
`E501` findings currently produces 400 rows — exactly the token waste
polycheck exists to prevent.

**File:** `src/polycheck/reporters/markdown_reporter.py`

**Change:** When a single `(tool, rule)` pair has more than 5 findings, render
the first 5 rows followed by one line:
`- …and N more `rule` findings (see polycheck-report.json)`.
Read the file first to match its existing rendering style; implement the cap
where rows are emitted. Add a module constant `MAX_EXAMPLES_PER_RULE = 5`.

**Also:** Test in `tests/test_reporters.py`: build 8 findings with the same
tool+rule, render markdown, assert the output contains exactly 5 location rows
for that rule and the string `and 3 more`.

**Verify:** standard sequence.

**Commit:** `feat: cap per-rule examples in markdown report to save LLM tokens`

---

### T14. Add a deterministic fix-plan reporter (`polycheck-plan.md`)

**Why:** This is the project's original vision: a big LLM (or no LLM at all)
should hand a cheap model an ordered, atomic task list — not a raw findings
dump. polycheck can generate that plan deterministically, without calling any
model, keeping the "polycheck never calls an LLM" philosophy.

**File (new):** `src/polycheck/reporters/plan_reporter.py`

**Behavior:** A function
`render(repo: Path, findings: list[Finding], results: list, report_dir: Path) -> list[Path]`
(same signature convention as the other reporters — read
`reporters/__init__.py` first and follow the existing registration mechanism)
that writes `polycheck-plan.md` containing:

1. A header block with the repo path, total findings, and these standing
   rules for the implementing agent (verbatim):
   ```
   ## Rules
   - Do one task at a time, in order.
   - After each task run the listed verification command; it must pass.
   - Make one commit per task with the given message.
   - Do not refactor, reformat, or fix anything a task does not mention.
   ```
2. Tasks ordered by: severity (CRITICAL first), then category, then tool.
   Consecutive findings with the same `(tool, rule)` are merged into ONE task
   listing all locations.
3. Each task rendered as:
   ```
   ### Task <n>: <tool> <rule> — <first finding message>
   - Severity: <severity> | Category: <category>
   - Locations: <file:line>, <file:line>, …
   - Docs: <doc_url if present>
   - Fix: <fix_command if fixable, otherwise "manual — edit each location so the rule no longer fires">
   - Verify: polycheck run . --tool <tool> --severity <severity>  (expect this rule gone)
   - Commit: fix(<tool>): resolve <rule> (<count> locations)
   ```

**Wire-up:** Register the format name `plan` wherever the other formats
(`markdown`, `json`, `sarif`) are registered (`reporters/__init__.py`). Add
`plan` to the default `output.formats` in `config.py` ONLY IF the default list
is defined in one place; otherwise leave defaults unchanged and document
`formats: [markdown, json, sarif, plan]` in the README configuration example.

**Also:**
- Test `tests/test_plan_reporter.py`: 3 findings (two same tool+rule, one
  CRITICAL different tool) → assert CRITICAL task is Task 1, the two same-rule
  findings merged into one task with two locations, file written to
  `report_dir`.
- Mention the plan file in `_SHARED_STEPS` (workflows) as: "For large finding
  sets, read `polycheck-plan.md` and execute it task by task instead of
  re-deriving an order from the raw report."

**Verify:** standard sequence, plus
`python -c "from polycheck.reporters import plan_reporter; print('ok')"`.

**Commit:** `feat: deterministic fix-plan reporter for cheap-model execution`

---

### T15. Add a findings baseline (`polycheck baseline`) so existing repos aren't flooded

**Why:** On any mature repo the first run yields hundreds of findings, which
makes the tool unusable day-to-day. A baseline file records current
fingerprints; later runs report only NEW findings. This is the standard
adoption pattern (ratchet).

**Files:** new `src/polycheck/baseline.py`, edits in `src/polycheck/cli.py`,
`src/polycheck/mcp/handlers.py`.

**`baseline.py`:**

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

**CLI:** add a `baseline` command to `cli.py` (model it on the existing `run`
command): it runs the same pipeline as `run` (no severity filter), then calls
`write_baseline` and prints the path and count. Add a `--no-baseline` flag to
`run`; by default `run` loads the baseline and applies it AFTER dedupe and
BEFORE severity filtering, printing `(N known findings suppressed by
.polycheck-baseline.json)` when N > 0.

**MCP:** in `_handle_polycheck` and `_handle_audit_run`, apply the baseline
the same way and include `"baseline_suppressed": N` in the summary dict.

**Also:** tests in a new `tests/test_baseline.py` for write/load/apply
round-trip and for the corrupted-file case (returns empty set). Document the
feature in README under Configuration.

**Verify:** standard sequence.

**Commit:** `feat: findings baseline to surface only new issues`

---

## Phase 5 — Docs and host polish

### T16. README overhaul for first-time users

**File:** `README.md`

**Changes (keep everything else):**
1. Top of file, right under the tagline: a 5-line "30-second start" block:
   ```bash
   pipx install "git+https://github.com/Phhofm/polycheck.git"
   polycheck init --host all --scope global
   # restart your assistant, then type:  /polycheck
   ```
2. Add CI badge after T9 is merged:
   `![CI](https://github.com/Phhofm/polycheck/actions/workflows/ci.yml/badge.svg)`.
3. New short section "Using polycheck with small/cheap models" explaining the
   two-tier flow: run `/polycheck` → the assistant triages the report → for
   big backlogs, hand `polycheck-reports/<run>/polycheck-plan.md` to a cheap
   model and let it execute task by task.
4. Update the tool-name references from `polycheck.run` to `polycheck_run`
   (after T3).
5. Remove the "Self-audit" claim block or update its "Last verified" line only
   if you have actually rerun `polycheck run .` successfully in this session.

**Verify:** standard sequence (README changes don't affect tests, but run it
anyway per global rules).

**Commit:** `docs: 30-second quickstart, cheap-model workflow, name updates`

---

### T17. Add CONTRIBUTING.md

**File (new):** `CONTRIBUTING.md` with exactly these sections:
- Dev setup: `pip install -e ".[dev]"`.
- Quality gates: the three-command verification sequence from this plan's
  global rules, plus `polycheck run . --tool ruff --tool mypy --fail-on HIGH`.
- How to add a tool adapter: copy the shortest existing adapter
  (`src/polycheck/tools/depcheck.py`), list the required attributes
  (`name`, `category`, `languages`, `installer`), the two required methods,
  and the rule: every adapter needs a smoke test entry (point to how
  `tests/test_tool_smoke.py` discovers adapters — read it first and describe
  what it actually does).
- Release process: bump version in `pyproject.toml`, update `CHANGELOG.md`,
  tag `vX.Y.Z`, push tags.

**Verify:** standard sequence.

**Commit:** `docs: add CONTRIBUTING.md`

---

### T18. Ship a Claude Code plugin manifest (optional, last)

**Why:** A Claude Code *plugin* can bundle the MCP server config + the skill
in one installable unit (`/plugin install`), which is nicer than `polycheck
init` for Claude users. Kilo/OpenCode keep using `init`.

**Files (new):**
- `claude-plugin/.claude-plugin/plugin.json`:
  ```json
  {
    "name": "polycheck",
    "description": "Static-first code analysis: run local analyzers, hand the LLM a tight triage report.",
    "version": "0.1.0",
    "mcpServers": {
      "polycheck": {
        "command": "polycheck",
        "args": ["mcp"]
      }
    }
  }
  ```
- `claude-plugin/skills/polycheck/SKILL.md` — same content as
  `CLAUDE_WORKFLOW` (with frontmatter from T1). Generate it, don't hand-copy:
  add a tiny script `scripts/sync_plugin_skill.py` that writes
  `CLAUDE_WORKFLOW` to that path, and call it out in CONTRIBUTING.md so the
  two never drift.
- README section "Install as a Claude Code plugin" documenting
  `/plugin marketplace add Phhofm/polycheck` + `/plugin install polycheck`
  (note: requires the repo to have a `.claude-plugin/marketplace.json`; create
  one listing the `claude-plugin` directory as the plugin source — check the
  current Claude Code plugin docs for the exact marketplace schema before
  writing it, and if unsure, write the manifest but mark the README section
  "experimental").

**Verify:** standard sequence; plus
`python scripts/sync_plugin_skill.py && git diff --exit-code claude-plugin/` succeeds
when run twice.

**Commit:** `feat: Claude Code plugin manifest bundling MCP server and skill`

---

## Explicitly OUT of scope (do not do these)

- Do NOT add LLM API calls to polycheck. It stays model-free by design.
- Do NOT rewrite the MCP server on FastMCP; the low-level API works and is
  tested.
- Do NOT add new analyzers in this plan (Go/Rust support etc. is future work).
- Do NOT change the `Finding` schema or SARIF output structure.
- Do NOT touch `.polycheck/` session file formats beyond T5.

## Order and dependencies

Run phases in order. Within Phase 1, tasks are independent except T3 before
T16. T14 depends on T13 only conceptually (both touch reporters) — do T13
first. T18 depends on T1.
