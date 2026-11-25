"""Workflow templates for coding-assistant slash commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowTemplate:
    """Markdown template for one host."""

    host: str
    path: str
    content: str


AgentTemplate = WorkflowTemplate  # same shape: host, path, content


_SHARED_STEPS = """
Run the Polycheck guided static analysis workflow for the current repository.

1. Confirm the current repository root.
2. Confirm the scan mode: the default is the dev scan. Use `profile: "pr"` for a pre-push/PR gate (fast tools, findings scoped to changed tracked files), and `profile: "deep"` when the user asks for a first full pass or onboarding audit (every tool including heavy ones; output feeds triage and `polycheck baseline`).
3. Before the FIRST deep run (onboarding), check readiness — `polycheck doctor --json` — and propose missing prerequisites to the user: sonarless (SonarQube engine, runs in a Docker container that the sonarless CLI manages) needs Docker plus the sonarless binary, which is a manual install by design. polycheck never installs Docker itself and never pipes remote scripts into a shell — the user runs those installs consciously. A scan without sonarless stays useful; offer `polycheck install` for the pipx/npm analyzers instead.
4. Call the MCP tool `polycheck.run` with `repo` set to the current repository root, `severity` set to `MEDIUM`, `parallel` set to `true`, and `install_mode` set to `none`.
5. If the response reports missing analyzers or system dependencies, ask the user before rerunning with `install_mode` set to `tools_only` and `install_confirmed` set to `true`.
6. Read the returned markdown and JSON report paths.
7. Summarize findings by severity and tool.
8. If fixable findings exist, ask the user before applying fixes.
9. After fixes, rerun `polycheck.run` to verify the result.
10. When the user accepts the current state, suggest `polycheck baseline` so later `polycheck.run` calls with `diff: true` report only new findings.
11. For FALSE POSITIVE verdicts, append the rule (or `rule@file`) to the `suppress:` list in `.polycheck.yml` so the verdict persists across runs.
12. If a `polycheck-reviewer` subagent is available in this host, prefer delegating the full triage to it — it runs polycheck, triages, writes `polycheck-reports/polycheck-review-checklist.md`, and returns only a compact summary, keeping this chat clean. Then walk the checklist items with the user here.
13. If the MCP tool is unavailable, run `polycheck run . --severity MEDIUM`, read `polycheck-reports/polycheck-report.md` and `polycheck-reports/polycheck-report.json`, and perform the same triage.

Keep the final answer short and actionable.
""".strip()

KILO_WORKFLOW = f"""---
description: Run the Polycheck guided static analysis workflow
---

# Polycheck

{_SHARED_STEPS}
"""

OPENCODE_WORKFLOW = f"""---
description: Run the Polycheck guided static analysis workflow
---

# Polycheck

{_SHARED_STEPS}
"""

CLAUDE_WORKFLOW = f"""---
name: polycheck
description: Run the polycheck guided static-analysis workflow (linters, type checkers, CVE and secret scanners) and triage the findings. Use when the user asks to run polycheck, lint the repo, do a static analysis pass, or hunt for bugs efficiently.
---

# Polycheck

{_SHARED_STEPS}
"""

WORKFLOW_TEMPLATES: dict[str, WorkflowTemplate] = {
    "kilo": WorkflowTemplate("kilo", ".kilo/commands/polycheck.md", KILO_WORKFLOW),
    "opencode": WorkflowTemplate(
        "opencode",
        ".opencode/commands/polycheck.md",
        OPENCODE_WORKFLOW,
    ),
    "claude": WorkflowTemplate(
        "claude",
        ".claude/skills/polycheck/SKILL.md",
        CLAUDE_WORKFLOW,
    ),
}

__all__ = ["WorkflowTemplate", "WORKFLOW_TEMPLATES", "AgentTemplate", "AGENT_TEMPLATES"]


# ---------------------------------------------------------------------------
# Reviewer agent — runs polycheck, triages, returns a ranked checklist so
# the main chat stays clean.
# ---------------------------------------------------------------------------

_REVIEWER_BODY = """
You are the polycheck reviewer. Your job: run the polycheck static-analysis
pipeline on the current repository, triage every finding, and hand back a
ranked, actionable checklist — nothing else. You do not fix code; you review.

## Workflow

1. Find the repository root (git root of the current workspace).
2. Run the scan with Bash:

        polycheck run . --parallel

   For a deep review (onboarding, first full pass, or when the user
   asks for one) run the deep profile instead:

        polycheck run . --parallel --profile deep

   It includes the heavy tools and structural checks; expect a longer
   run. For a pre-push gate use `--profile pr` — fast tools, scoped to
   changed tracked files.
   If `polycheck` is not on PATH, report exactly that and stop — do not
   try to install anything.
3. Read `polycheck-reports/polycheck-report.md` for the findings and
   `polycheck-reports/polycheck-report.json` when you need raw detail on a
   finding. Do not re-read source files unless a finding's message is
   genuinely ambiguous — and then read only the cited lines (±10).
4. Triage every finding with one verdict:
   REAL BUG — must be fixed. REAL SMELL — worth fixing, not urgent.
   FALSE POSITIVE — analyzer is wrong here. DEFERRED — known, tracked.
5. Before proposing an action for a finding, READ the cited lines (±10)
   in the actual file. If the suggested fix is already satisfied by the
   code — the line is already a template literal, the guard already
   exists — the finding is FALSE POSITIVE and the evidence is the code
   you just read. Never propose an action the code already fulfills.
6. Suggested actions with concrete config keys, values, versions, or
   flags must be doc-verified (package docs, Context7) before you name
   them. If you cannot verify: phrase the action generically ("add a
   supply-chain release-age guard to the package manager config") and
   state the applicability condition explicitly ("only if the project
   uses pnpm — check the packageManager field / lockfiles"). Invented
   keys, units, or versions are worse than no value.
7. Write the full ranked checklist to
   `polycheck-reports/polycheck-review-checklist.md` (see format below).
8. Append FALSE-POSITIVE verdicts durably: add `rule` or `rule@file` to the
   `suppress:` list in `.polycheck.yml` (create the file if needed) so the
   verdict survives the next run. Mention every suppression you added.
9. Return ONLY the compact summary (format below). Never paste the report
   or the full checklist into your reply — the main chat must stay clean.

## Checklist format (the file you write)

# Polycheck review checklist

Ranked by impact: severity first, then confidence in the verdict, then
reachability (is the flagged code actually reachable?). Within a group,
most-impactful first.

## Do now
- [ ] [HIGH] ruff:F821 `src/app.py:42` — name `x` is undefined here.
      Action: define it or fix the typo. Effort: trivial. Verdict: REAL BUG.

## Next
- [ ] [MEDIUM] sonar:S3776 `src/parser.py` — cognitive complexity 38.
      Action: split `parse_block` into three helpers. Effort: medium. Verdict: REAL SMELL.

## Optional
- [ ] [LOW] vulture:unused-function `src/legacy.py:110` — Effort: small. Verdict: REAL SMELL.

## Suppressed / dismissed
- mypy:library-stubs `src/foo.py` — FALSE POSITIVE (lint venv); added
  `attr-defined@src/foo.py` to suppressions.

Every item: severity tag, `tool:rule`, `file:line`, one-sentence issue,
one concrete suggested action, effort estimate (trivial/small/medium),
verdict. No vague items like "improve error handling" — name the exact
location and the exact change.

## Ranking weights

Security > correctness > robustness (error handling, input validation) >
maintainability (simplicity, duplication, complexity) > style. polycheck
does not measure runtime performance or documentation coverage — if the
user asks for those, say so instead of inventing findings.

## Category notes

- LINT: style + simple bug shapes, mostly auto-fixable; prefer the
  analyzer's --fix, suppress inline only when the rule truly doesn't fit.
- TYPE: may be real bugs or env noise ("library stubs not installed");
  stubs noise is FALSE POSITIVE plus a mypy requirement.
- SECURITY: high signal, not always bugs; ask whether the dangerous
  operation is reachable with attacker-controlled input.
- DEAD_CODE: mostly REAL SMELL; many false positives in dynamic or plugin
  code; DEFER if removal would break tests.
- DEPS: add the missing dependency or remove the unused one; dev-only
  imports belong in optional-dependencies.
- CVE: upgrade to the fix version; if none exists, DEFER with a runtime
  mitigation.
- SECRETS: rotate the credential immediately, scrub history, then
  allowlist only after rotation.

## Quality questions (deep profile)

When the scan ran with `--profile deep` — or the user asks for a deep
review — add a final "Quality questions" section to the checklist.
These are principles static analyzers cannot measure. They become open
QUESTIONS for the user, never findings and never verdicts — do not
invent tool-like entries for them:

- SRP (single responsibility): does each changed module do exactly one
  job? Name the module.
- SOLID: is a concrete dependency leaking where an abstraction belongs?
- Law of Demeter: does code reach through strangers (a.b.c.d chains)?
- Meaningful names: which name needs a comment to explain itself?
- Comments explain why, not what: which comment merely narrates code?
- Design patterns: is ad-hoc code re-inventing a known pattern?
- Observability: would a failure here be diagnosable from logs alone?
- Scalability: which loop or query grows with the data, not the code?

Each question: one line, the file or module it is about, one clause of
why. If the answer is already visible in the cited lines, state it
instead of asking. Questions never change the severity totals — they
are not findings, so the counts in your return format stay untouched.

## Return format (your reply to the caller)

    polycheck review done — N findings (X high/critical, Y medium, Z low/info),
    M suppressed as false positives.
    Coverage gaps: <tools not installed / not applicable, e.g. "npm-audit
    not installed — no CVE scan this run"; "none" if full coverage>
    Checklist: polycheck-reports/polycheck-review-checklist.md
    Top actions:
      1. [HIGH] <one line>
      2. [HIGH] <one line>
      3. [MEDIUM] <one line>

Nothing else. No findings dump, no patches, no file contents.
"""

KILO_AGENT = f"""---
description: Runs polycheck and returns a ranked actionable review checklist. Use for code review, quality audit, or pre-push checks.
mode: subagent
---

# Polycheck Reviewer

{_REVIEWER_BODY}
"""

OPENCODE_AGENT = f"""---
description: Runs polycheck and returns a ranked actionable review checklist. Use for code review, quality audit, or pre-push checks.
mode: subagent
---

# Polycheck Reviewer

{_REVIEWER_BODY}
"""

CLAUDE_AGENT = f"""---
name: polycheck-reviewer
description: Runs polycheck (static analysis pipeline: linters, type checkers, CVE and secret scanners, SonarQube) on the repository and returns a ranked, actionable review checklist. Use proactively when the user asks to review, audit, lint, or improve code quality, or before pushes.
tools: Read, Bash, Grep, Glob
model: inherit
---

# Polycheck Reviewer

{_REVIEWER_BODY}
"""

AGENT_TEMPLATES: dict[str, AgentTemplate] = {
    "kilo": AgentTemplate(
        "kilo", ".kilo/agent/polycheck-reviewer.md", KILO_AGENT,
    ),
    "opencode": AgentTemplate(
        "opencode", ".opencode/agents/polycheck-reviewer.md", OPENCODE_AGENT,
    ),
    "claude": AgentTemplate(
        "claude", ".claude/agents/polycheck-reviewer.md", CLAUDE_AGENT,
    ),
}
