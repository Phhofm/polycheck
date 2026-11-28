# polycheck

[![CI](https://github.com/Phhofm/polycheck/actions/workflows/ci.yml/badge.svg)](https://github.com/Phhofm/polycheck/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/polycheck)](https://pypi.org/project/polycheck/)
[![Python](https://img.shields.io/pypi/pyversions/polycheck)](https://pypi.org/project/polycheck/)

More and more production code is written by AI coding agents — and the
way agents write code has measurable failure modes.

## Why polycheck exists

*"SlopCodeBench: Benchmarking How Coding Agents Degrade Over Long-Horizon
Iterative Tasks"* (Orlanski et al., 2026 —
[arXiv:2603.24755](https://arxiv.org/abs/2603.24755)) put numbers on what
reviewers keep feeling:

- agents degrade their own codebases across iterative extension:
  **structural erosion rises in 77 % of trajectories, verbosity in
  75.5 %**
- compared against 473 open-source Python repositories, agent code is
  **2.3× more verbose and 2.0× more eroded**
- the trap: **agents pass the checkpoints while the code erodes and
  bloats with every turn** — tests stay green, so the decay is
  invisible to exactly the checks most projects rely on
- and prompting the agent to write better code helps little: explicit
  quality guidance reduces initial verbosity and erosion by up to a
  third, but **does not change the degradation rate**

That is the gap polycheck fills. Prompts don't stop erosion;
deterministic, measurable checks run on every iteration can catch it.

## What polycheck does

polycheck applies the paper's findings — plus everything else
deterministic analysis catches — as a polyglot static-analysis pipeline
with LLM-ready output. It runs 22 bundled analyzers (linters,
type-checkers, CVE scanners, secret scanners, SonarQube) and hands the
LLM a tight, located, reproducible findings list to adjudicate:

- every finding has a **tool, rule, file, and line** — the LLM verifies
  instead of guessing
- the paper's erosion model is measured directly: duplicated AST
  blocks, slop patterns, complexity-mass concentration ([details](#anti-ai-slop-metrics-built-in-zero-install))
- works as an **MCP server** (three slim tools: run, audit_run, and the read-only doctor) with `/polycheck`
  workflows for Kilo Code, OpenCode, Claude Code, and any MCP client
- **self-auditing**: a seeded-defect verifier guards every adapter — a
  tool that runs clean on a repo seeded with defects it must catch
  reports `missed-defects`, never a false bill of health

**Let your LLM triage a verified report instead of hallucinating a
review — and measure the slop your agents leave behind.**

## Contents

1. [Why polycheck exists](#why-polycheck-exists)
2. [What polycheck does](#what-polycheck-does)
3. [Quick start](#quick-start)
4. [What you get](#what-you-get)
5. [Anti AI-slop metrics](#anti-ai-slop-metrics-built-in-zero-install)
6. [Scan profiles](#scan-profiles)
7. [CLI usage](#cli-usage-manual)
8. [The daily loop](#the-daily-loop)
9. [Configuration](#configuration)
10. [Tool matrix](#tool-matrix)
11. [How it works](#how-it-works)
12. [MCP server reference](#mcp-server-reference)
13. [For LLM agents: the polycheck skill](#use-polycheck-from-an-llm-skill)
14. [Extending](#adding-a-language-or-tool)
15. [Origin & philosophy](#origin)

---

## Quick Start

Install once, initialize your assistant integration, then run
`/polycheck` in any repository.

**Tested on:** Ubuntu Budgie (Linux) with the Kilo Code VS Code
extension, driven by GLM models. Designed to be portable (Linux/macOS
first; Windows via WSL or Git Bash), but that is the tested home base.

### Step 1: Install polycheck

```bash
pipx install polycheck
# Or from source:
pipx install "git+https://github.com/Phhofm/polycheck.git"
```

### Step 2: Initialize `/polycheck`

For one setup across all your projects, use global workflow/config files:

```bash
polycheck init --host all --scope global
```

Preview first:

```bash
polycheck init --host all --scope global --dry-run
```

For a single repository only, use project-local files:

```bash
polycheck init --host all --scope project
```

The initializer writes slash-command workflow files and, where safe, MCP
config:

| Host | Project files | Global files |
| --- | --- | --- |
| Kilo Code | `.kilo/commands/polycheck.md` and `kilo.jsonc` | `~/.config/kilo/commands/polycheck.md` and `~/.config/kilo/kilo.jsonc` |
| OpenCode | `.opencode/commands/polycheck.md` and `opencode.jsonc` | `~/.config/opencode/commands/polycheck.md` and `~/.config/opencode/opencode.jsonc` |
| Claude Code | `.claude/skills/polycheck/SKILL.md` and `.mcp.json` | `~/.claude/skills/polycheck/SKILL.md` and `~/.claude.json` |

Useful options:

```bash
polycheck init --host kilo,opencode --scope global --yes
polycheck init --host claude --scope project --force
polycheck init --host all --scope global --no-mcp
polycheck init --host all --scope global --mcp-only
```

### Step 3: Restart your LLM coding assistant

Restart Kilo Code, OpenCode, Claude Code, or your MCP-compatible tool so it
reloads MCP servers and slash-command files.

### Step 4: Run the guided workflow

In any project, type:

```text
/polycheck
```

or ask your assistant to:

```text
run polycheck
```

What happens:

1. The workflow calls the MCP tool `polycheck.run` against the current repo.
2. polycheck checks which analyzers and system dependencies are available.
3. If tools are missing, the LLM asks whether to install them.
4. polycheck runs the installed applicable analyzers.
5. Reports are written to `polycheck-reports/`.
6. The LLM shows a compact summary grouped by tool and severity.
7. If fixable findings exist, the LLM asks before applying fixes.
8. After fixes, the LLM reruns `polycheck.run` to verify the result.
9. Once you accept the current state, the LLM suggests `polycheck baseline`;
   later `polycheck.run` calls with `diff: true` surface only new findings.
10. FALSE-POSITIVE verdicts land in `.polycheck.yml` `suppress:` so they
    are never re-argued.

If the MCP tool is unavailable, the generated workflow falls back to:

```bash
polycheck run . --severity MEDIUM
```

and then asks the LLM to triage the generated markdown and JSON reports.

Session summaries are written under `.polycheck/` so future LLM sessions
can reference what was checked, skipped, fixed, or deferred.

---

## What You Get

`polycheck run <repo>` writes a `<repo>/polycheck-reports/` directory:

- `polycheck-report.md` — human-friendly, LLM-friendly triage report
- `polycheck-report.json` — canonical machine-readable findings
- `polycheck-report.sarif` — IDE / GitHub code-scanning integration

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

## Anti AI-slop metrics (built in, zero install)

LLM-written code tends toward specific, measurable failure modes —
polycheck ships an analyzer that measures them instead of arguing about
taste. `scb-check` runs on every scan with no extra binary, derived from
the [SlopCodeBench](https://www.scbench.ai) erosion model:

| Metric | Category | What it catches |
|--------|----------|-----------------|
| Duplicated AST blocks | `duplication` | copy-paste-variant functions that drifted apart — the classic "the model rewrote the same helper twice" |
| Slop patterns | `lint` | `range(len(x))` instead of `enumerate`, `dict.get(k, None)`, trivial pass-through wrappers — code that compiles, passes review, and is still worse |
| Complexity-mass concentration | `complexity` | erosion: the share of total complexity piling up in single functions while file count grows |

If you build with AI assistants (vibe coding), this is the report to
read first: it quantifies the erosion an LLM leaves behind in a
codebase that otherwise looks green — no failing tests, no type errors,
and yet the same logic living in three places and one function carrying
half the complexity.

The slop-pattern rules are Python-specific today **plus a first
polycheck-authored TypeScript set (`ts-slop`, ast-grep-based — index
loops, type-system escape hatches like `as any`/`as unknown as`/
`@ts-ignore`, empty catch blocks)**; duplication and erosion metrics
are cross-language. Structural decay across *modules* (circular
imports, boundary violations) is covered separately by the structural
adapters (`tach` for Python, `dependency-cruiser` for JS/TS) in the
deep profile. Vue SFCs are not covered yet (ast-grep skips `.vue`
without a custom parser).

**Trendable composites:** `polycheck-report.json` carries the
SlopCodeBench composites (verbosity, erosion, cog_erosion) under a
top-level `metrics` key on every scan that runs scb-check — diff them
across runs to see whether an agent-assisted codebase is staying
stable or eroding turn over turn. Read them **together**: verbosity
measures redundant code, cog_erosion the cognitive mass piling up in
few functions, and `erosion` the cyclomatic-mass *concentration* — a
 sprawling if/elif ladder spreads mass across branches and can read
0.0 on erosion while verbosity and cog_erosion spike. No single
composite catches every degradation form; a clean bill from one is
not a clean bill from the analysis.

---

## Scan profiles

Profiles are presets over the existing primitives — tool selection,
scoping, and the gate. The default scan stays what it was:

| Profile | Tools | Scope | Gate |
|---------|-------|-------|------|
| *(default)* | all installed + applicable, fast pass | whole repo | MEDIUM |
| `--profile pr` | fast tools only (no Docker/network-heavy, no structural) | changed tracked files (git diff vs HEAD / merge-base) | HIGH |
| `--profile deep` | everything, incl. sonarless/semgrep/pip-audit/npm-audit and structural adapters | whole repo | none — the report feeds triage, then `polycheck baseline` |

`pr` is for pre-push/PR gates: findings in files that did not change are
out of scope, and a baseline (`--diff`) can further filter known ones.
`deep` is for onboarding and periodic full passes. The pre-push hook
installed by `polycheck init --git-hook pre-push` runs `--profile pr`.

Before the **first deep run**, check readiness with
`polycheck doctor --json` — it reports which analyzers are missing and
that sonarless (SonarQube) needs Docker plus a manual sonarless install
(see [How it works](#how-it-works)).

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
polycheck run . --profile pr               # fast tools, changed-file scope, HIGH gate
polycheck run . --profile deep             # every tool incl. heavy ones, no gate
polycheck run . --output markdown          # markdown only (no JSON / sarif)
polycheck baseline .                       # snapshot current findings
polycheck run . --diff                     # only findings NEW since the baseline
polycheck init --host all --scope global   # initialize /polycheck workflows
polycheck init --dry-run --host all        # preview initialization
polycheck init --host all --agents-only    # write only the reviewer subagent
polycheck init --scope project --git-hook pre-push   # dev-cycle quality gate
polycheck doctor                           # show installed/missing tools, exit 0 by default
polycheck doctor --json                    # machine-readable readiness: tools, prerequisites, profiles, install policy
polycheck doctor --fail-on-missing         # exit 1 when tools are missing
polycheck install                          # install every missing tool
polycheck install ruff mypy                # install specific tools
polycheck list-tools                       # list every available analyzer
polycheck verify-tools                     # verify supported analyzers on synthetic repos
polycheck verify-tools --install --yes     # install missing auto-installable tools, then verify
polycheck verify-tools --include-heavy     # include Docker/network-heavy tools
polycheck prompt --plain                   # print the triage prompt
polycheck mcp                              # start the MCP server
```

`polycheck run` exits with code **1** if any finding is at or above
`--fail-on` (default `MEDIUM`). Use `--fail-on HIGH` in CI.

---

## The daily loop

Run, triage, snapshot, gate — this is the cycle that keeps a repo clean
without drowning in known findings.

### Baseline & durable suppressions

The daily loop: run once, triage, snapshot — then only *new* code
produces findings.

```bash
polycheck baseline .        # snapshot today's accepted findings
polycheck run . --diff      # report only NEW findings (exit 1 gates on new ones)
```

The baseline stores fingerprints only (tool, rule, file, line,
column) in `polycheck-reports/polycheck-baseline.json` — small, stable
across message changes. Re-run `polycheck baseline` after fixing or
triaging to move the needle forward.

When the LLM (or you) classifies a finding as FALSE POSITIVE, persist
that verdict so it is never re-argued:

```yaml
suppress:
  - F401                    # suppress rule everywhere
  - SC2086@scripts/legacy.sh  # suppress rule in one file only
```

Suppressed findings are dropped before reports are written and before
the CI exit-code gate, so they never reappear in a later run.

A **mitigated** finding is a legitimate `suppress:` candidate too —
e.g. a taint flow that fires despite the schema allowlist guarding it:
the tool cannot see the mitigation, you can. Persist the verdict with a
comment explaining it, so the suppression documents the mitigation
instead of silently hiding a bug.

### The dev-cycle trigger: pre-push gate

Wire polycheck into the development loop so quality is checked before it
leaves your machine:

```bash
polycheck init --scope project --git-hook pre-push
```

This installs a `.git/hooks/pre-push` gate that runs
`polycheck run . --parallel --profile pr` and blocks the push on HIGH+
findings in the changed tracked files (it never overwrites an existing
hook). Triage or suppress, then push. Pair it with `polycheck baseline`
+ `run --diff` so the gate only judges what changed.

### The reviewer subagent (keeps the main chat clean)

`polycheck init` also writes a **`polycheck-reviewer` subagent** for each
host (Kilo: `.kilo/agent/`, OpenCode: `.opencode/agent/`, Claude:
`.claude/agents/`). The review flow then looks like this:

1. You (or the LLM, or a pre-push trigger) ask for a code review.
2. The main LLM **delegates to the `polycheck-reviewer` subagent** — your
   main chat stays clean, no report noise.
3. The subagent runs polycheck, triages every finding
   (REAL BUG / REAL SMELL / FALSE POSITIVE / DEFERRED), and writes a
   **ranked, actionable checklist** to
   `polycheck-reports/polycheck-review-checklist.md` — each item with
   severity, `tool:rule`, exact location, a concrete suggested action, and
   an effort estimate. FALSE-POSITIVE verdicts land durably in
   `.polycheck.yml` `suppress:`.
4. The subagent returns only a compact summary (counts + top actions).
5. The main LLM walks the checklist with you: tackle everything, or only
   HIGH+, and re-judges any item before acting on it.

Skip the agents with `--no-agents`, or write only them with `--agents-only`:

```bash
polycheck init --host all --scope project --agents-only
```

### The Triage Prompt

The guided MCP workflow handles triage automatically. If you run the CLI
manually, you can still print the prompt and pair it with a report:

```bash
polycheck prompt --plain    # prints just the prompt
```

The LLM reads the report (not the source code) and triages each finding
as REAL BUG, REAL SMELL, FALSE POSITIVE, or DEFERRED.

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
| Python             | tach            | Module boundaries + circular imports (`tach.toml`, deep profile) |
| JS / TS            | eslint          | Linter (ESLint v9 flat config + legacy) |
| JS / TS            | tsc             | TypeScript type checker                 |
| JS / TS            | knip            | Unused files, exports, dependencies     |
| JS / TS            | npm-audit       | CVE scan in dependencies                |
| JS / TS            | depcheck        | Missing / unused dependencies           |
| JS / TS            | dependency-cruiser | Module boundaries + circular deps (`.dependency-cruiser.*` config, deep profile) |
| Universal          | gitleaks        | Secrets in the working tree             |
| Universal          | scb-check       | AI-slop metrics: duplicated AST blocks, slop patterns (`range(len(x))`, `dict.get(k, None)`, trivial wrappers), and erosion (complexity-mass concentration) — the measurable DRY/KISS proxies, built for the [SlopCodeBench](https://www.scbench.ai) erosion model |
| Universal          | semgrep         | Pattern-based security (multi-language) |
| TypeScript         | ts-slop         | Polycheck-authored TS slop rules (ast-grep): index loops, `as any`/`as unknown as` escape hatches, `@ts-ignore`, empty catch, `!!` casts |
| Universal          | **sonarless**   | **SonarQube: bugs, vulns, code smells (30+ languages, requires Docker)** |
| GitHub Actions     | actionlint      | Workflow file linter                    |
| Shell              | shellcheck      | Shell script linter                     |
| GitHub Actions     | zizmor          | CI/CD security semantics: template injection, credential persistence, excessive permissions (actionlint checks syntax; zizmor checks security) |
| Tests              | coverage        | Runs your pytest suite, reports untested modules and per-file coverage gaps (deep profile; needs `coverage` + `pytest` in the environment you run polycheck from) |
| Docker             | hadolint        | Dockerfile linter                       |

Install hints are exposed via `polycheck explain <tool>`.

---

## How It Works

```
                ┌────────────────────────────────────────────┐
                │              polycheck.run                 │
                └─────────────────────┬──────────────────────┘
                                      │
       dependency check → install approval → detect → filter → run → dedupe → group
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
- Install manually: `curl -sSL https://raw.githubusercontent.com/gitricko/sonarless/main/install.sh | bash`
- polycheck never pipes remote scripts into a shell itself — it shows the
  command above and you run it consciously
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

## MCP Server Reference

polycheck ships an MCP server with a deliberately slim surface: **two
tools**. Fewer tools means the LLM reliably picks the right one —
diagnostics, listings, explanations, and installs belong to the CLI.

### Tools

| Tool | Description |
|------|-------------|
| `polycheck.run` | Primary guided workflow: dependency check, optional install approval, scan, reports, coverage metadata, optional baseline diff (`diff: true`), and next action. Emits spec-standard MCP progress notifications when the client requests them. |
| `polycheck.audit_run` | Low-level scan primitive: report paths, dependency context, and a one-line summary. |

### Resources

| Resource | Description |
|----------|-------------|
| `polycheck://session/latest` | Latest `polycheck.run` workflow summary. |
| `polycheck://triage/prompt` | The interactive LLM triage prompt. |
| `polycheck://setup` | Setup and operations guide for LLM agents: profiles, prerequisites (Docker for sonarless), install policy, the daily loop. |
| `polycheck://findings/markdown` | Last run's markdown report. |
| `polycheck://findings/json` | Last run's JSON report. |

CLI equivalents of the retired MCP tools: `polycheck doctor`,
`polycheck install`, `polycheck list-tools`, `polycheck explain`.

**Driving polycheck with an LLM?** Point the agent at
`polycheck://setup` and `polycheck doctor --json` first: the resource
explains when to use which profile, that sonarless runs the SonarQube
engine in a Docker container the sonarless CLI manages (manual install
by design, Docker never auto-installed), and what polycheck will and
will not install itself. The scan responses carry the same
`profile_guidance` block, so the agent learns the modes even without
reading the resource.

### Manual MCP setup

If you prefer not to use `polycheck init`, configure the MCP server manually.

**Claude Code** — add to project `.mcp.json`, `~/.claude/settings.json`, or
your Claude user MCP config:

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

**Kilo Code (VSCode Extension)** — add to `kilo.jsonc` in your project root
or `~/.config/kilo/kilo.jsonc`:

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

**OpenCode** — add to `opencode.jsonc` in your project root or
`~/.config/opencode/opencode.jsonc`:

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

**Docker / SonarQube:** SonarQube analysis through sonarless requires
both Docker running and the `sonarless` binary installed. polycheck keeps
sonarless enabled by default when those are available. If Docker is
missing, polycheck reports it as a skipped system dependency and suggests
asking your LLM coding assistant for OS-specific Docker setup help. If
Docker is available but sonarless is missing, the guided MCP workflow
offers to install sonarless before rerunning `polycheck.run`.

### Code Mode friendly

polycheck follows the [Code Mode](https://blog.cloudflare.com/code-mode/)
guidance (Cloudflare, Anthropic *programmatic tool calling*, OpenCode 2.0
default): tool definitions stay tiny (two state-changing tools plus one
read-only doctor, not ten), tool responses
are compact summaries, and the heavy data lives in report **files** the
agent reads selectively — only the final result ever needs to reach the
model. For orchestration and ad-hoc composition, the CLI is the scripting
layer (`polycheck run . --diff --fail-on HIGH | …`), which is the same
pattern as Cloudflare's command-line approach. An execute-code MCP tool
would duplicate the CLI, so there isn't one. polycheck also composes fine
with agents that route MCP calls through a code-mode interpreter by default
(OpenCode 2.x): responses are already compact, and the install-approval
flow is result-based (`needs_user_input`), not mid-call.

---

## Use polycheck from an LLM skill

The fastest way to teach any coding agent how to drive polycheck well:
install the ready-made skill.

```bash
# Kilo Code (global)
mkdir -p ~/.kilo/skills/polycheck
curl -fsSL https://raw.githubusercontent.com/Phhofm/polycheck/main/polycheck-skill.md \
  -o ~/.kilo/skills/polycheck/SKILL.md

# Or from a local clone:
cp polycheck-skill.md ~/.kilo/skills/polycheck/SKILL.md
```

The skill encodes the optimal usage: readiness check first
(`polycheck doctor --json`), which profile for which situation, the
triage → suppress → baseline loop, and the hard rules (findings come
from reports only; never auto-install Docker; never pipe remote
scripts). Claude Code users already get a skill via
`polycheck init`; the file above is the standalone version for hosts
without init support.

---

## Verifying every supported analyzer

Use `polycheck verify-tools` when changing analyzer wrappers or installer
logic. It creates synthetic repositories and verifies every registered tool:

```bash
polycheck verify-tools
```

Installed tools are run. Missing tools are reported as skipped. To attempt
automatic installation for installable tools first:

```bash
polycheck verify-tools --install --yes
```

Docker/network-heavy tools are skipped by default because they can start
Docker or reach package registries. Include them explicitly when that is
acceptable:

```bash
polycheck verify-tools --include-heavy
```

For a full install-and-run verification of every supported analyzer, use:

```bash
polycheck verify-tools --install --yes --include-heavy
```

The heavy set currently includes `sonarless`, `semgrep`, `pip-audit`, and
`npm-audit`:

- `sonarless` requires Docker and the `sonarless` binary. Its installer is
  Docker-aware and only runs when Docker is available.
- `gitleaks`, `actionlint`, `hadolint`, and `shellcheck` are not downloaded
  by polycheck (no unverified binaries); install them via your package
  manager (`brew`, `apt`, `scoop`, …) or their GitHub releases — the exact
  hint is shown by `polycheck doctor` / `verify-tools`.
- `semgrep` may download rules when using `--config=auto`.
- `pip-audit` queries PyPI to audit Python dependencies.
- `npm-audit` queries the npm registry to audit Node dependencies.

To verify every supported tool in the pytest suite, run the heavy marker:

```bash
pytest -m heavy
```

The default `pytest` run includes the heavy smoke test only when the tools are
already installed or can be skipped safely; use `polycheck verify-tools
--install --yes --include-heavy` when you explicitly want install-and-run
coverage for every supported analyzer.

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

The token savings come free with the architecture. The deeper claim is
[the No AI Slop manifesto's](https://www.slopmanifesto.com/) resolution 12:
*"Anything a linter, type checker, or automated check can catch, we let it
catch."* polycheck is that catch-all for agent-written code — including the
[measurable slop metrics](https://www.scbench.ai) (verbosity, erosion) that
quantify how agents degrade codebases over repeated changes.

## Acknowledgments

polycheck stands on the shoulders of the analyzers it orchestrates —
[ruff](https://github.com/astral-sh/ruff), [mypy](https://www.mypy-lang.org/),
[vulture](https://github.com/jendrikse/vulture),
[semgrep](https://semgrep.dev), [gitleaks](https://github.com/gitleaks/gitleaks),
[deptry](https://github.com/fpgmaas/deptry),
[depcheck](https://github.com/depcheck/depcheck),
[pip-audit](https://github.com/pypa/pip-audit),
[npm-audit](https://docs.npmjs.com/cli/commands/npm-audit),
[knip](https://knip.dev),
[shellcheck](https://www.shellcheck.net),
[hadolint](https://github.com/hadolint/hadolint),
[actionlint](https://github.com/rhysd/actionlint),
[tsc](https://www.typescriptlang.org/), eslint, and
[SonarQube](https://www.sonarsource.com/open-code-edition/) via
[sonarless](https://github.com/gitricko/sonarless) — plus
[ast-grep](https://ast-grep.github.io) via
[scb-check](https://github.com/gabeorlanski/scb-check).

The anti-slop metrics build on **"SlopCodeBench: Benchmarking How Coding
Agents Degrade Over Long-Horizon Iterative Tasks"**
([arXiv:2603.24755](https://arxiv.org/abs/2603.24755),
[scbench.ai](https://www.scbench.ai)) and are aligned with the
[No AI Slop Manifesto](https://www.slopmanifesto.com/).

Built with [MCP](https://modelcontextprotocol.io),
[typer](https://typer.tiangolo.com/), [rich](https://rich.readthedocs.io/),
[pydantic](https://docs.pydantic.dev/), and tree-sitter.

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

## One-command setup

Want polycheck **and** the vibecode skill wired into your coding agent in one go? See [vibecode-harness](https://github.com/Phhofm/vibecode-harness).
