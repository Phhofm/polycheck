# polycheck

> **Stop wasting LLM tokens re-reading codebases.**
> polycheck runs the cheap, exhaustive static-analysis pass first
> (linters, type-checkers, CVE scanners, secret scanners) and hands
> the LLM a tight, structured report to triage. The LLM never has to
> read source code it doesn't need to.

```bash
pipx install polycheck        # 1. install (or: pipx install git+https://github.com/Phhofm/polycheck.git)
polycheck doctor && polycheck install --all -y   # 2. install the analyzers
polycheck run ~/code/myproject                   # 3. scan
polycheck prompt --plain                         # 4. copy the triage prompt → paste it to your LLM with the report
```

**That's the whole loop.** Reports land in
`<repo>/polycheck-reports/`. The LLM reads the report, not the code.

> **Self-audit:** `polycheck run .` on this repo's source tree returns
> **0 findings at MEDIUM+ severity** across all 7 bundled Python
> analyzers. Last verified: 0.1.0.

---

## What you get

`polycheck run <repo>` writes a `<repo>/polycheck-reports/` directory:

  * `polycheck-report.md` — human-friendly, LLM-friendly triage report
  * `polycheck-report.json` — canonical machine-readable findings
  * `polycheck-report.sarif` — IDE / GitHub code-scanning integration

Each finding has a stable schema:

```json
{
  "tool": "ruff",
  "rule": "I001",
  "severity": "LOW",                  // INFO | LOW | MEDIUM | HIGH | CRITICAL
  "category": "lint",                 // lint | type | security | dead_code | deps | cve | secrets
  "message": "Import block is un-sorted or un-formatted",
  "file": "src/foo.py",
  "line": 12,
  "column": 1,
  "fixable": true,
  "fix_command": "ruff check --fix .",
  "doc_url": "https://docs.astral.sh/ruff/rules/i001"
}
```

polycheck auto-detects the languages in your repo, picks the
applicable analyzers, dedupes cross-tool reports, and filters by
severity. The default floor is `INFO` (everything is reported); pass
`--severity MEDIUM` to drop noise.

## The LLM triage prompt

After `polycheck run`, hand this prompt to an LLM (Claude Code, Kilo
Code, opencode, or a chat):

````markdown
You are a senior code reviewer. The file `polycheck-report.md` is the
output of a static-analysis pipeline. It contains LINT, TYPE,
SECURITY, DEAD_CODE, DEPS, and SECRETS findings with file, line,
rule id, severity, and the analyzer's message.

Triage every finding as one of:

  REAL BUG       — must be fixed; do not ship without a fix.
  REAL SMELL     — not wrong, but worth refactoring; flag for follow-up.
  FALSE POSITIVE — analyzer is wrong here; suppress or whitelist.
  DEFERRED       — known issue, tracked elsewhere; leave it.

For REAL BUG and REAL SMELL, give the smallest possible patch. Do not
rewrite surrounding code. Do not add new dependencies. Do not change
public APIs unless the finding says to. Prefer the analyzer's
suggested fix if one exists.

Ignore findings that are clearly tooling noise (e.g. "Library stubs
not installed for X" from mypy — that's the lint venv, not the
project).

Do not re-read the source files unless a finding's message is
genuinely ambiguous. Trust the static report. Read the full markdown
report with the `read_file` tool, then the JSON report with
`read_file` for any findings you need full `raw` data on.

When you're done, return a single JSON object shaped like:

{
  "actions": [
    {
      "tool": "ruff",
      "rule": "I001",
      "file": "src/foo.py",
      "line": 12,
      "verdict": "REAL BUG",
      "patch": "…unified diff or null…",
      "comment": "one sentence"
    }
  ],
  "summary": "X real bugs, Y real smells, Z false positives, W deferred"
}
````

Print it any time with `polycheck prompt --plain`.

## Installation

```bash
# Recommended: pipx (isolated venv, no global pollution)
pipx install polycheck

# Alternative: pip
pip install polycheck

# From source (current dev branch)
pipx install "git+https://github.com/Phhofm/polycheck.git"

# Editable local checkout (for hacking on polycheck itself)
git clone https://github.com/Phhofm/polycheck.git
cd polycheck
pipx install -e .
```

The polycheck Python package is small (4 deps: typer, rich, pyyaml,
mcp). The analyzers it shells out to — ruff, mypy, gitleaks, etc. —
are *your* responsibility. polycheck skips tools that aren't on your
`PATH`; use the `polycheck doctor` + `polycheck install` commands to
manage them.

Quick install of the common Python set:

```bash
pipx install ruff mypy vulture deptry pip-audit
brew install gitleaks              # macOS — see https://github.com/gitleaks/gitleaks for Linux
```

## Verify the install

```bash
polycheck --version     # → polycheck 0.1.0
polycheck doctor        # → table of installed/missing tools
polycheck list-tools    # → all 15 bundled analyzers
```

## Usage

```bash
polycheck run [PATH]                      # run all applicable tools
polycheck run . --tool ruff --tool mypy    # restrict to specific tools
polycheck run . --severity MEDIUM          # drop INFO / LOW findings
polycheck run . --fail-on HIGH             # exit 1 if any HIGH/CRITICAL (CI)
polycheck run . --install                  # install missing tools, then run
polycheck run . --parallel                 # run tools concurrently
polycheck run . --no-dedupe                # skip cross-tool dedup
polycheck run . --output markdown          # markdown only (no JSON / sarif)
polycheck run . --output json,sarif        # multiple formats
polycheck doctor                           # show installed/missing tools
polycheck install                          # install every missing tool
polycheck install ruff mypy                # install specific tools
polycheck install --all -y                 # reinstall everything (no prompt)
polycheck list-tools                       # list every available analyzer
polycheck explain <tool> [rule]            # show a tool's doc URL
polycheck detected [PATH]                  # show detected languages
polycheck prompt                           # show the LLM triage prompt
polycheck prompt --plain                   # prompt only, no explanation
polycheck --version
polycheck mcp                              # start the MCP server
```

`polycheck run` exits with code **1** if any finding is at or above
`--fail-on` (default `MEDIUM`). Use `--fail-on HIGH` (or `CRITICAL`)
in CI to surface only the most serious defects.

## Configuration

Drop a `.polycheck.yml` (or `.polycheck.toml`) at the repo root:

```yaml
enable:                 # only run these tools (default: all applicable)
  - ruff
  - mypy
  - gitleaks
disable:                # never run these tools
  - pylint
severity_threshold: MEDIUM
timeout: 600            # per-tool seconds
output:
  formats: [markdown, json, sarif]
  report_dir: polycheck-reports
extra_args:             # per-tool extra CLI args
  ruff: ["--select", "E,F"]
  eslint: ["--max-warnings", "0"]
```

## How it works

```
                ┌────────────────────────────────────────────┐
                │               polycheck run                │
                └─────────────────────┬──────────────────────┘
                                      │
       doctor → install ──► detect → filter → run → dedupe → group
                                      │
   ┌────────────┬─────────────┬───────┴────────┬──────────────┐
   │ Python     │ JS / TS     │ Universal      │ Polyglot     │
   │ ruff       │ eslint      │ gitleaks       │ semgrep      │
   │ mypy       │ tsc         │                │              │
   │ vulture    │ knip        │                │              │
   │ pip-audit  │ npm-audit   │                │              │
   │ deptry     │ depcheck    │                │              │
   └────────────┴─────────────┴────────────────┴──────────────┘
                                      │
                          normalize → Finding
                                      │
                  ┌───────────────────┼───────────────────┐
              markdown               json              sarif
              (LLM-friendly)     (canonical)        (IDE / GH code-scanning)
```

Every analyzer is wrapped by a `Tool` adapter in
`src/polycheck/tools/`. Each adapter:

  1. Calls the underlying tool as a subprocess.
  2. Parses its output (JSON or text, with format-specific regexes).
  3. Emits `Finding` objects with a stable schema.

A finding has a `fingerprint` of
`(tool, rule, file, line, column)`, so two tools reporting the same
defect converge to one row.

## Tool matrix

| Language / Surface | Tool            | What it does                            |
|--------------------|-----------------|-----------------------------------------|
| Python             | ruff            | Fast linter + import sort               |
| Python             | mypy            | Static type checker                     |
| Python             | vulture         | Dead code (with whitelist support)      |
| Python             | pip-audit       | CVE scan in dependencies                |
| Python             | deptry          | Missing / unused dependencies           |
| JS / TS            | eslint          | Linter (ESLint v9 flat config + legacy) |
| JS / TS            | tsc             | TypeScript type checker                 |
| JS / TS            | knip            | Unused files, exports, dependencies     |
| JS / TS            | npm-audit       | CVE scan in dependencies                |
| JS / TS            | depcheck        | Missing / unused dependencies           |
| Universal          | gitleaks        | Secrets in working tree + git history   |
| Universal          | semgrep         | Pattern-based security (multi-language) |
| GitHub Actions     | actionlint      | Workflow file linter                    |
| Shell              | shellcheck      | Shell script linter                     |
| Docker             | hadolint        | Dockerfile linter                       |

Install hints are exposed via `polycheck explain <tool>`.

## MCP server

polycheck ships an MCP server. Wire it into Kilo Code, Claude Code,
or opencode:

```json
{
  "mcpServers": {
    "polycheck": {
      "command": "polycheck",
      "args": ["mcp"]
    }
  }
}
```

Three tools are exposed:

  * `polycheck.audit_run` — run the full pipeline on a repo.
  * `polycheck.list_tools` — list every analyzer.
  * `polycheck.explain_finding` — explain a category (CVE, DEAD_CODE,
    LINT, …) and how to triage findings in it.

Three resources are exposed:

  * `polycheck://triage/prompt` — the LLM triage prompt.
  * `polycheck://findings/markdown` — last run's markdown report.
  * `polycheck://findings/json` — last run's JSON report.

A typical agent flow:

  1. `polycheck.audit_run` against the repo.
  2. `read_file` the markdown report from the resource URI.
  3. Apply the triage prompt.
  4. Optionally write patches.

## Adding a language or tool

Adding a new analyzer is a single file:

```python
# src/polycheck/tools/mypy_advanced.py
from ..finding import Category, Severity
from .base import Tool

class MypyAdvancedTool(Tool):
    name = "mypy-advanced"
    category = Category.TYPE
    languages = ["python"]

    def is_applicable(self, repo):
        return (repo / "pyproject.toml").exists()

    def run(self, repo):
        # call subprocess, parse output, return list[Finding]
        ...
```

`ToolRegistry.discover()` will auto-register it on first import. No
core changes required.

To add a new **language** (e.g. Go, Rust), add a marker to the
`LANGUAGES` tuple in `src/polycheck/detect.py`, and existing tools
that already speak the language (e.g. semgrep, gitleaks) will pick it
up automatically. New language-specific tools just set
`languages = ["go"]`.

## Philosophy

  * **Static analyzers are cheap; reading code is expensive.**
    polycheck does the cheap pass exhaustively.
  * **One schema, many backends.** Every analyzer maps to
    `Finding`. Reporters only know one shape.
  * **LLMs are a second pass, not a substitute.** polycheck
    doesn't call any model. It produces the artifacts that make an
    LLM's review step fast and focused.
  * **No magic.** polycheck is a thin subprocess wrapper. It
    doesn't try to *understand* your code. Your linters already
    do that better than any LLM would.
  * **Reports are git-tracked.** `polycheck-reports/` is plain
    text. Diff it across PRs.

## License

MIT.
