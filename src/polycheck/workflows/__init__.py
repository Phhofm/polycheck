"""Workflow templates for coding-assistant slash commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowTemplate:
    """Markdown template for one host."""

    host: str
    path: str
    content: str


_SHARED_STEPS = """
Run the Polycheck guided static analysis workflow for the current repository.

1. Confirm the current repository root.
2. Call the MCP tool `polycheck.run` with `repo` set to the current repository root, `severity` set to `MEDIUM`, `parallel` set to `true`, and `install_mode` set to `none`.
3. If the response reports missing analyzers or system dependencies, ask the user before rerunning with `install_mode` set to `tools_only` and `install_confirmed` set to `true`.
4. Read the returned markdown and JSON report paths.
5. Summarize findings by severity and tool.
6. If fixable findings exist, ask the user before applying fixes.
7. After fixes, rerun `polycheck.run` to verify the result.
8. When the user accepts the current state, suggest `polycheck baseline` so later `polycheck.run` calls with `diff: true` report only new findings.
9. For FALSE POSITIVE verdicts, append the rule (or `rule@file`) to the `suppress:` list in `.polycheck.yml` so the verdict persists across runs.
10. If the MCP tool is unavailable, run `polycheck run . --severity MEDIUM`, read `polycheck-reports/polycheck-report.md` and `polycheck-reports/polycheck-report.json`, and perform the same triage.

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

__all__ = ["WorkflowTemplate", "WORKFLOW_TEMPLATES"]
