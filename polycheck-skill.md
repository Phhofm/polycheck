---
name: polycheck
description: Static-analysis quality gate driven through the polycheck CLI/MCP. Use when the user asks to run polycheck, review code quality, triage findings, set up a quality gate, or before pushing. Covers readiness checks, scan profiles (pr/deep), the triage → suppress → baseline loop, and the install policy.
---

# polycheck — how to drive it well

polycheck runs the applicable static analyzers on a repository and hands
you located, reproducible findings (tool, rule, file, line) to triage.
Your job is triage and verification — never inventing findings.

## First move in a repo

1. **Readiness before the first full scan:** `polycheck doctor --json`.
   Parse: `tools[].installed` / `install_hint` / `profiles`,
   `system_dependencies` (sonarless needs Docker), `profile_guidance`,
   `install_policy`.
2. **Default scan:** MCP tool `polycheck.run` with
   `{repo: <root>, severity: "MEDIUM", parallel: true, install_mode: "none"}`
   — or CLI `polycheck run . --parallel`. Reports land in
   `polycheck-reports/polycheck-report.md` (+ `.json`, `.sarif`).
3. If `install_mode: "tools_only"` would be needed (missing analyzers),
   ask the user first. Always.

## Picking the profile

- **default** (no profile) — the everyday dev scan. Whole repo, MEDIUM
  gate, fast tools that are installed.
- **`profile: "pr"`** — pre-push/PR gate: fast tools only, findings
  scoped to changed tracked files, HIGH gate. Use before pushing or for
  review of a change set. `polycheck init --git-hook pre-push` wires it
  into the push automatically.
- **`profile: "deep"`** — onboarding / first full pass / periodic audit:
  every tool including heavy ones (sonarless/SonarQube needs Docker,
  semgrep, pip-audit, npm-audit) and the structural adapters (tach,
  dependency-cruiser). No gate — the report feeds triage, then
  `polycheck baseline`. Check `polycheck doctor --json` first and
  propose missing prerequisites to the user.

## Triage (the part the LLM does)

- Read the markdown report and the cited lines in the code before
  judging. Classify every finding: REAL BUG / REAL SMELL /
  FALSE POSITIVE / DEFERRED.
- Suggested actions must be doc-verified or phrased generically with an
  applicability condition — invented config keys/units are worse than
  no value.
- FALSE POSITIVES → append the rule (or `rule@file`) to `suppress:` in
  `.polycheck.yml` so the verdict persists.
- After fixes: rerun the scan to verify. Never claim "clean" without a
  fresh run.
- If a `polycheck-reviewer` subagent exists, delegate the triage to it
  and work from its checklist.

## The loop after acceptance

```bash
polycheck baseline .     # snapshot accepted findings
polycheck run . --diff   # only NEW findings from now on
```

## Hard rules

- **Findings come from the reports only.** Never fabricate a finding;
  never present a suspicion as a tool result.
- **Install policy:** polycheck auto-installs only analyzers marked
  auto-installable, and only after the user approves. It never installs
  Docker itself and never pipes remote scripts into a shell — sonarless
  is a manual `curl -sSL … | bash` the USER runs consciously.
- **Docker/sonarless:** if Docker is missing, propose the official
  Docker installer and continue without sonarless — the scan stays
  useful. If Docker runs but sonarless is missing, offer the manual
  install command; the SonarQube server then runs in a Docker container
  managed by the sonarless CLI (web UI port 9234,
  `sonarless docker-clean` to clean up).
- **Secrets are CRITICAL.** gitleaks findings are never LOW-severity
  noise; treat them as blocking.
- **Suppressed ≠ fixed.** A suppression is a decision with a reason —
  say which suppression hid a finding if the user asks about it.

## Reference

- MCP resource `polycheck://setup` — the full setup/operations guide.
- `polycheck doctor --json` — the machine-readable readiness payload.
- MCP tools: `polycheck.run` (guided), `polycheck.audit_run`
  (low-level). CLI mirrors everything.
- `polycheck verify-tools` — verifies every adapter against seeded
  defects (run it after changing analyzer wrappers).
