# polycheck

> **Stop wasting LLM tokens re-reading codebases.**
> polycheck runs the cheap, exhaustive static-analysis pass first
> (linters, type-checkers, CVE scanners, secret scanners, SonarQube)
> and hands the LLM a tight, structured report to triage. The LLM
> never has to read source code it doesn't need to.

> **Self-audit:** `polycheck run .` on this repo's source tree returns
> **0 findings at MEDIUM+ severity** across the bundled analyzers that are
> installed and applicable, including optional SonarQube via sonarless when
> Docker and the `sonarless` binary are available. Last verified: 0.1.0.

---

## Quick Start: One Command for LLM Coding Assistants

polycheck is designed for Claude Code, Kilo Code, OpenCode, and other
LLM coding tools. Install it once, enable the MCP server, then run:

```text
/polycheck
```

or:

```text
run polycheck
```

The LLM calls one guided MCP workflow. polycheck checks dependencies,
reports missing tools, runs local analyzers, writes reports, summarizes
findings, and asks before installing tools or applying fixes.

### Step 1: Install polycheck

```bash
pipx install polycheck
# Or from source:
pipx install "git+https://github.com/Phhofm/polycheck.git"
```

### Step 2: Add MCP config

**Claude Code** — add to `~/.claude/settings.json` or project `.claude/settings.json`:

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

**Kilo Code (VSCode Extension)** — add to `kilo.jsonc` in your project root or `~/.config/kilo/kilo.jsonc`:

```json
{
  "mcp": {
    "polycheck": {
      "type": "local",
      "command": ["polycheck", "mcp"],
      "enabled": true
    }
  }
}
```

**OpenCode** — add to `opencode.jsonc` in your project root:

```json
{
  "mcp": {
    "polycheck": {
      "type": "local",
      "command": ["polycheck", "mcp"],
      "enabled": true
    }
  }
}
```

**Any MCP-compatible tool** (generic JSON):

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

### Step 3: Run the guided workflow

In your project, type:

```text
/polycheck
```

or:

```text
run polycheck
```

What happens:

1. polycheck checks which analyzers and system dependencies are available.
2. If tools are missing, the LLM asks whether to install them.
3. polycheck runs the installed applicable analyzers.
4. Reports are written to `polycheck-reports/`.
5. The LLM shows a compact summary grouped by tool and severity.
6. If fixable findings exist, the LLM asks before applying fixes.
7. After fixes, the LLM can rerun polycheck to verify the result.

Session summaries are written under `.polycheck/` so future LLM sessions
can reference what was checked, skipped, fixed, or deferred.

**Docker / SonarQube:** SonarQube analysis through sonarless requires
both Docker running and the `sonarless` binary installed. polycheck keeps
sonarless enabled by default when those are available. If Docker is
missing, polycheck reports it as a skipped system dependency and suggests
asking your LLM coding assistant for OS-specific Docker setup help. If
Docker is available but sonarless is missing, the guided MCP workflow
offers to install sonarless before rerunning the scan.

---

## CLI Usage (Manual)

If you prefer running polycheck directly without an LLM:

```bash
polycheck run [PATH]                      # run all applicable tools
polycheck run . --tool ruff --tool mypy    # restrict to specific tools
polycheck run . --severity MEDIUM          # drop INFO / LOW findings
polycheck run . --fail-on HIGH             # exit 1 if any HIGH/CRITICAL (CI)
polycheck run . --install                  # install missing tools, then run
polycheck run . --parallel                 # run tools concurrently
polycheck run . --output markdown          # markdown only (no JSON / sarif)
polycheck doctor                           # show installed/missing tools, exit 0 by default
polycheck doctor --fail-on-missing         # exit 1 when tools are missing
polycheck install                          # install every missing tool
polycheck install ruff mypy                # install specific tools
polycheck list-tools                       # list every available analyzer
polycheck prompt --plain                   # print the triage prompt
polycheck mcp                              # start the MCP server
```

`polycheck run` exits with code **1** if any finding is at or above
`--fail-on` (default `MEDIUM`). Use `--fail-on HIGH` in CI.

### The Triage Prompt

The guided MCP workflow handles triage automatically. If you run the CLI
manually, you can still print the prompt and pair it with a report:

```bash
polycheck prompt --plain    # prints just the prompt
```

The LLM reads the report (not the source code) and triages each finding
as REAL BUG, REAL SMELL, FALSE POSITIVE, or DEFERRED.

---

## MCP Server Reference

polycheck ships an MCP server with one primary workflow tool and several
advanced/low-level tools.

### Primary tool

| Tool | Description |
|------|-------------|
| `polycheck` | Run the guided workflow: dependency check, optional install approval, scan, reports, compact summary, and next action. |

### Advanced tools

| Tool | Description |
|------|-------------|
| `polycheck.audit_run` | Run the low-level scan primitive on a repo. Returns report paths, dependency context, and summary. |
| `polycheck.list_tools` | List every analyzer polycheck knows about and whether it is installed. |
| `polycheck.explain_finding` | Explain a category (CVE, SECURITY, LINT, etc.) and how to triage it. |
| `polycheck.doctor` | Check Docker, sonarless, and all analyzers. Non-fatal by default. |
| `polycheck.install` | Install missing tools (all or specific ones). |

### Resources

| Resource | Description |
|----------|-------------|
| `polycheck://session/latest` | Latest guided workflow summary. |
| `polycheck://triage/prompt` | The interactive LLM triage prompt. |
| `polycheck://findings/markdown` | Last run's markdown report. |
| `polycheck://findings/json` | Last run's JSON report. |

---

## What You Get

`polycheck run <repo>` writes a `<repo>/polycheck-reports/` directory:

  * `polycheck-report.md` — human-friendly, LLM-friendly triage report
  * `polycheck-report.json` — canonical machine-readable findings
  * `polycheck-report.sarif` — IDE / GitHub code-scanning integration

Each finding has a stable schema:

```json
{
  "tool": "sonarless",
  "rule": "sonar:bug:S3776",
  "severity": "HIGH",
  "category": "security",
  "message": "Complexity of this function is too high",
  "file": "src/parser.py",
  "line": 42,
  "fixable": false
}
```

---

## Configuration

Drop a `.polycheck.yml` (or `.polycheck.toml`) at the repo root:

```yaml
enable:                 # only run these tools (default: all applicable)
  - ruff
  - mypy
  - gitleaks
  - sonarless
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

**sonarless** is enabled by default when Docker is running and the
`sonarless` binary is installed. Disable it with:

```yaml
disable:
  - sonarless
```

---

## Tool Matrix

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
| Universal          | **sonarless**   | **SonarQube: bugs, vulns, code smells (30+ languages, requires Docker)** |
| GitHub Actions     | actionlint      | Workflow file linter                    |
| Shell              | shellcheck      | Shell script linter                     |
| Docker             | hadolint        | Dockerfile linter                       |

Install hints are exposed via `polycheck explain <tool>`.

---

## How It Works

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
   │ mypy       │ tsc         │ **sonarless**  │              │
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

### sonarless (Docker-based)

sonarless starts a local SonarQube instance in Docker, scans your code,
and queries the SonarQube API for per-file issues. It covers 30+
languages for bugs, vulnerabilities, code smells, and security hotspots.

- Requires **Docker** installed and running
- Install when Docker is available: `curl -sSL https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash`
- The guided MCP workflow offers to install sonarless automatically when Docker is available.
- Web UI: `http://localhost:9234` (admin/Son@rless123)
- Clean up: `sonarless docker-clean`

**PATH setup:** After installing sonarless, add it to your PATH:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.sonarless:$PATH"

# Or create a wrapper script
echo '#!/bin/bash
exec $HOME/.sonarless/makefile.sh "$@"' > $HOME/.sonarless/sonarless
chmod +x $HOME/.sonarless/sonarless
```

**Note for OpenCode users:** If you're using OpenCode in a sandboxed
environment, Docker may not be accessible due to snap confinement.
Install Docker via apt (`sudo apt install docker.io`) instead of snap
for full compatibility.

---

## Adding a Language or Tool

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

---

## Origin

polycheck started because a coworker pasted this prompt into Claude Code
for two projects:

> *"Go bug hunting, carefully analyze the entire code. Create a list of
> bugs and errors. Sort by critical to minor. Max 20 items."*

It burned through a massive amount of tokens and produced very little
useful outcome. The LLM was re-reading code that existing tools already
analyze faster and more reliably.

That's when it clicked: **there's a more efficient way to use LLMs.**
Static analyzers already do the cheap, exhaustive pass — linting, type
checking, CVE scanning, secret detection. Give the LLM the structured
report from those tools, and it can focus on triage and verification
instead of re-reading everything from scratch.

We need to learn to *combine* new technology with established tools,
not replace the old with the new. It reminds me of the blockchain hype
during university — everyone wanted to use it as a distributed database
when highly optimized systems already existed for that. The same pattern
is repeating with LLMs: they're not the solution for *everything*.
Sometimes the right answer is a thin wrapper that connects tools that
already work.

polycheck is that wrapper. It doesn't try to understand your code. It
lets your linters do what they're good at, and hands the LLM a tight
report to act on.

---

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

---

## License

MIT.
