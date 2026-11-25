"""Polycheck CLI.

Subcommands
-----------

``polycheck run [PATH]``
    Detect languages, run all applicable tools, write reports.

``polycheck list-tools``
    Print every available tool and which languages it supports.

``polycheck explain RULE``
    Print a short explanation of a tool/rule identifier.

``polycheck init``
    Initialize `/polycheck` for Kilo Code, OpenCode, and Claude Code.

``polycheck mcp``
    Start the MCP server (stdio transport).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__
from .config import Config
from .detect import detect
from .finding import Finding
from .initializer import (
    GIT_HOOKS,
    HOSTS,
    apply_plan,
    build_plan,
    format_action,
    normalize_hosts,
)
from .profiles import (
    ProfileError,
    changed_files,
    effective_fail_on,
    filter_by_scope,
    is_skipped,
    resolve_profile,
)
from .registry import default_registry
from .reporters import render as render_report
from .runner import (
    Runner,
    apply_suppressions,
    dedupe,
    filter_by_baseline,
    filter_by_severity,
    load_baseline,
    save_baseline,
)
from .tools.base import Tool
from .verify import HEAVY_TOOLS, verify_tools

# Auto-discover all bundled tools on import so the CLI is ready to go.
default_registry.discover()


app = typer.Typer(
    name="polycheck",
    no_args_is_help=True,
    help="Static-first, LLM-triage-ready code analysis. See `polycheck run --help`.",
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"polycheck {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    """polycheck — static-first, LLM-triage-ready code analysis."""


@app.command()
def run(
    path: Path = typer.Argument(
        Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True
    ),
    parallel: bool = typer.Option(False, "--parallel", help="Run tools in parallel"),
    tool: list[str] = typer.Option(
        None, "--tool", "-t", help="Restrict to specific tool name(s) (repeatable)"
    ),
    severity: str = typer.Option(
        None,
        "--severity",
        help="Minimum severity to keep (INFO, LOW, MEDIUM, HIGH, CRITICAL)",
    ),
    config: Path = typer.Option(
        None, "--config", "-c", help="Path to a .polycheck.yml"
    ),
    output: list[str] = typer.Option(
        None, "--output", "-o", help="Report format(s): markdown, json, sarif"
    ),
    report_dir: Path = typer.Option(
        None, "--report-dir", help="Where to write reports (default: polycheck-reports)"
    ),
    no_dedupe: bool = typer.Option(False, "--no-dedupe"),
    diff: bool = typer.Option(
        False,
        "--diff",
        help="Only report findings that are new since the last "
        "`polycheck baseline` (reports everything when no baseline exists).",
    ),
    install: bool = typer.Option(
        False,
        "--install",
        help="Auto-install any missing analyzers before running",
    ),
    fail_on: str = typer.Option(
        None,
        "--fail-on",
        help="Exit non-zero if any finding is at or above this severity "
        "(INFO, LOW, MEDIUM, HIGH, CRITICAL). Default: MEDIUM — HIGH with "
        "--profile pr, no gate with --profile deep.",
    ),
    profile: str = typer.Option(
        None,
        "--profile",
        help="Scan preset: 'pr' (fast tools, changed-file scope, HIGH gate) "
        "or 'deep' (all tools incl. heavy ones, no gate). Default: full "
        "scan with the MEDIUM gate.",
    ),
) -> None:
    """Run all applicable tools and write reports."""
    try:
        profile_spec = resolve_profile(profile)
    except ProfileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    cfg = _load_config(config, path, severity, output, report_dir)
    repo = path.resolve()
    console.print(f"[bold]polycheck[/bold] {__version__} — {repo}")

    _print_detected_languages(repo)

    if install:
        _auto_install_missing(only=tool or None, repo=repo)

    runner = Runner(repo=repo, config=cfg, registry=default_registry)
    findings, results = runner.run(parallel=parallel, tools=tool or None,
                                   profile=profile_spec)

    if not no_dedupe:
        findings = dedupe(findings)
    findings = filter_by_severity(findings, cfg.severity_threshold)
    findings = apply_suppressions(findings, cfg.suppress)

    if profile_spec and profile_spec.scoped_to_changes:
        findings = _apply_change_scope(profile_spec, repo, findings)

    if diff:
        findings = _apply_diff_baseline(cfg, repo, findings)

    written = _write_reports(cfg, repo, findings, results)
    _print_summary(results, findings, written)

    failed = [r for r in results if r.status in ("error", "timeout")]
    if failed:
        _print_failures(failed)

    not_run = _missing_tools(repo, only=tool or None, exclude={r.tool for r in results})
    not_run = [cls for cls in not_run if not is_skipped(cls, profile_spec)]
    if not_run:
        _print_missing(not_run)

    gate = effective_fail_on(profile_spec, fail_on)
    raise typer.Exit(code=_exit_code(findings, gate))


def _apply_change_scope(profile_spec, repo: Path, findings: list) -> list:
    """pr profile: findings in files that did not change are out of scope."""
    changed = changed_files(repo)
    if changed is None:
        console.print(
            f"[red]--profile {profile_spec.name} requires a git repository.[/red]"
        )
        raise typer.Exit(code=2)
    console.print(
        f"[cyan]--profile {profile_spec.name}:[/cyan] "
        f"{len(changed)} changed tracked file(s) in scope"
    )
    return filter_by_scope(findings, changed)


def _apply_diff_baseline(cfg: Config, repo: Path, findings: list) -> list:
    """Filter findings to those newer than the baseline, with an
    honest console note when no baseline exists yet."""
    baseline = load_baseline(repo / cfg.output.report_dir)
    if baseline is None:
        console.print(
            "[yellow]--diff:[/yellow] no baseline yet — run "
            "[bold]polycheck baseline[/bold] first; reporting all findings"
        )
        return findings
    new = filter_by_baseline(findings, baseline)
    known = len(findings) - len(new)
    console.print(
        f"[cyan]--diff:[/cyan] baseline has {len(baseline)} finding(s) — "
        f"{known} known, [bold]{len(new)} new[/bold]"
    )
    return new


@app.command()
def baseline(
    path: Path = typer.Argument(
        Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True
    ),
    parallel: bool = typer.Option(False, "--parallel", help="Run tools in parallel"),
    tool: list[str] = typer.Option(
        None, "--tool", "-t", help="Restrict to specific tool name(s) (repeatable)"
    ),
    severity: str = typer.Option(
        None,
        "--severity",
        help="Minimum severity to keep (INFO, LOW, MEDIUM, HIGH, CRITICAL)",
    ),
    config: Path = typer.Option(
        None, "--config", "-c", help="Path to a .polycheck.yml"
    ),
    report_dir: Path = typer.Option(
        None, "--report-dir", help="Where to write the baseline (default: polycheck-reports)"
    ),
) -> None:
    """Snapshot today's findings as the baseline for `run --diff`.

    Run this once on a repo whose current findings are accepted; later
    `polycheck run --diff` then reports only NEW findings. Re-run it
    after fixing or triaging to move the needle forward.
    """
    cfg = _load_config(config, path, severity, None, report_dir)
    repo = path.resolve()
    console.print(f"[bold]polycheck[/bold] {__version__} — {repo}")

    runner = Runner(repo=repo, config=cfg, registry=default_registry)
    findings, _results = runner.run(parallel=parallel, tools=tool or None)
    findings = dedupe(findings)
    findings = filter_by_severity(findings, cfg.severity_threshold)
    findings = apply_suppressions(findings, cfg.suppress)

    baseline_path = save_baseline(repo / cfg.output.report_dir, findings)
    console.print(
        f"[green]Baseline saved:[/green] {len(findings)} findings "
        f"→ {baseline_path}"
    )


def _load_config(
    config: Path | None,
    path: Path,
    severity: str | None,
    output: list[str] | None,
    report_dir: Path | None,
) -> Config:
    """Load and apply CLI overrides to the config."""
    cfg = Config.load(config) if config else Config.load(path)
    if severity:
        cfg.severity_threshold = severity.upper()
    if output:
        cfg.output.formats = list(output)
    if report_dir:
        cfg.output.report_dir = str(report_dir)
    return cfg


def _print_detected_languages(repo: Path) -> None:
    """Print detected languages to the console."""
    langs = detect(repo)
    if langs:
        console.print(
            "Detected: " + ", ".join(f"[cyan]{lang.slug}[/cyan]" for lang in langs)
        )
    else:
        console.print("[yellow]No supported languages detected.[/yellow]")


def _write_reports(
    cfg: Config, repo: Path, findings: list, results: list
) -> list[Path]:
    """Write reports in all configured formats."""
    out_dir = repo / cfg.output.report_dir
    written: list[Path] = []
    for fmt in cfg.output.formats:
        written.extend(
            render_report(fmt, repo, findings, results, report_dir=out_dir)
        )
    return written


def _print_summary(results: list, findings: list, written: list[Path]) -> None:
    """Print the tool summary table and findings count."""
    by_tool = Table(title="Tools")
    by_tool.add_column("Tool", style="cyan")
    by_tool.add_column("Status")
    by_tool.add_column("Findings", justify="right")
    by_tool.add_column("Time (s)", justify="right")
    by_tool.add_column("Message")
    for r in sorted(results, key=lambda r: r.tool):
        # Escape cell content: adapter reasons may contain bracket
        # tokens like [tool.tach], which rich would otherwise swallow
        # as style markup (Loop-2 finding).
        by_tool.add_row(
            escape(r.tool), escape(r.status), escape(str(len(r.findings))),
            escape(f"{r.duration_sec:.1f}"), escape(r.message),
        )
    console.print(by_tool)
    console.print(f"\n[bold]{len(findings)}[/bold] findings after filtering")
    tracks = [f.track for f in findings]
    if any(t for t in tracks):
        tracked_n = sum(1 for t in tracks if t == "tracked")
        untracked_n = sum(1 for t in tracks if t == "untracked")
        ignored_n = sum(1 for t in tracks if t == "ignored")
        console.print(
            f"[cyan]Git buckets:[/cyan] tracked {tracked_n}, untracked "
            f"{untracked_n}, gitignored {ignored_n} — the fail-on gate "
            "counts tracked + untracked (gitignored files cannot reach the repo)."
        )
    if written:
        console.print("\nReports written:")
        for p in written:
            console.print(f"  [green]{p}[/green]")


def _print_failures(failed: list) -> None:
    """Print failed tool information."""
    console.print(
        f"[yellow]{len(failed)} tool(s) failed:[/yellow] "
        + ", ".join(r.tool for r in failed)
    )
    for r in failed:
        if r.error:
            console.print(f"  [red]{r.tool}[/red]: {r.error}")


def _print_missing(not_run: list) -> None:
    """Print missing tool information."""
    console.print(f"\n[yellow]{len(not_run)} tool(s) not installed:[/yellow]")
    for cls in not_run:
        inst = cls()
        console.print(f"  [cyan]{inst.name}[/cyan]: {inst.install_hint()}")


@app.command(name="list-tools")
def list_tools() -> None:
    """Print every available tool and which languages it supports."""
    table = Table(title="Available tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Category")
    table.add_column("Languages")
    table.add_column("Universal?", justify="center")
    table.add_column("Installer")
    for cls in default_registry.all():
        langs = ", ".join(cls.languages) if not cls.universal else "—"
        installer = cls.installer or "—"
        table.add_row(
            cls.name, cls.category.value, langs, "yes" if cls.universal else "",
            installer,
        )
    console.print(table)


@app.command(name="verify-tools")
def verify_tools_cmd(
    tool: list[str] | None = typer.Option(
        None,
        "--tool",
        "-t",
        help="Restrict verification to specific tool name(s) (repeatable)",
    ),
    install_missing: bool = typer.Option(
        False,
        "--install",
        help="Attempt automatic installation for missing installable tools before running them.",
    ),
    yes: bool = typer.Option(
        False,
        "-y",
        "--yes",
        help="Skip confirmation when --install is used.",
    ),
    include_heavy: bool = typer.Option(
        False,
        "--include-heavy",
        help="Run Docker/network-heavy tools such as sonarless, semgrep, pip-audit, and npm-audit.",
    ),
) -> None:
    """Verify every supported analyzer can install and run.

    By default this checks installed tools against synthetic repositories and
    skips missing tools. Use --install to attempt automatic installs, and
    --include-heavy only when Docker/network access are acceptable.
    """
    selected = list(tool or [])
    known = {cls.name for cls in default_registry.all()}
    unknown = [name for name in selected if name not in known]
    if unknown:
        console.print(f"[red]Unknown tool(s): {', '.join(unknown)}[/red]")
        raise typer.Exit(2)

    if install_missing and not yes:
        missing = [
            cls for cls in default_registry.all()
            if (not selected or cls.name in selected)
            and not cls().is_installed()
            and cls().can_auto_install()
        ]
        if missing:
            console.print("Will attempt to install missing tools:")
            for cls in missing:
                console.print(f"  [cyan]{cls.name}[/cyan]: {cls().install_hint()}")
            if not typer.confirm("Proceed?"):
                raise typer.Abort()

    results = verify_tools(
        default_registry,
        install=install_missing,
        include_heavy=include_heavy,
        tools=selected,
    )

    table = Table(title="polycheck verify-tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Status")
    table.add_column("Installed")
    table.add_column("Applicable")
    table.add_column("Findings", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Message")
    for result in results:
        table.add_row(
            result.tool,
            result.status,
            "yes" if result.installed else "no",
            "yes" if result.applicable else "no",
            str(result.findings),
            f"{result.duration_sec:.1f}",
            result.message,
        )
    console.print(table)

    failed = [r for r in results if r.status in {"error", "timeout", "install-failed"}]
    if failed:
        console.print(
            "[red]Verification failed:[/red] "
            + ", ".join(f"{r.tool} ({r.status})" for r in failed)
        )
        raise typer.Exit(1)

    heavy = ", ".join(sorted(HEAVY_TOOLS))
    console.print(
        "[green]Verification complete.[/green] "
        f"Heavy tools skipped by default: {heavy}. Use --include-heavy to run them."
    )


@app.command()
def explain(
    tool: str = typer.Argument(..., help="Tool name (e.g. ruff)"),
    rule: str = typer.Argument(None, help="Optional rule id (e.g. I001)"),
) -> None:
    """Explain a tool or a specific rule. Prints a doc URL when known."""
    cls = default_registry.get(tool)
    if cls is None:
        console.print(f"[red]Unknown tool:[/red] {tool}")
        raise typer.Exit(1)
    inst = cls()
    console.print(f"[bold]{tool}[/bold] — {inst.category.value}")
    console.print(f"Languages: {', '.join(cls.languages) or '*'}")
    console.print(f"Install hint: {inst.install_hint}")
    if rule:
        # Most tool adapters expose a per-rule doc_url; this is a
        # best-effort guess based on common conventions.
        candidates = [
            f"https://docs.astral.sh/ruff/rules/{rule.lower()}",
            f"https://eslint.org/docs/rules/{rule.lower()}",
            f"https://mypy.readthedocs.io/en/stable/_refs.html#code-{rule}",
        ]
        for url in candidates:
            console.print(f"  [blue]{url}[/blue]")


@app.command()
def mcp() -> None:
    """Start the polycheck MCP server (stdio transport)."""
    from .mcp_server import run_server
    run_server()


@app.command(name="init")
def init_cmd(
    host: list[str] | None = typer.Option(
        None,
        "--host",
        "-H",
        help=f"Host(s) to configure: {', '.join((*HOSTS, 'all'))}. Repeatable; default: all.",
    ),
    scope: str = typer.Option(
        "global",
        "--scope",
        help="Write project-local or global workflow/config files.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be written without modifying files.",
    ),
    yes: bool = typer.Option(
        False,
        "-y",
        "--yes",
        help="Write files without an interactive confirmation prompt.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing workflow files. MCP config is merged when valid JSON.",
    ),
    no_mcp: bool = typer.Option(
        False,
        "--no-mcp",
        help="Write slash-command workflow files only.",
    ),
    mcp_only: bool = typer.Option(
        False,
        "--mcp-only",
        help="Write MCP config only; do not write slash-command workflow files.",
    ),
    no_agents: bool = typer.Option(
        False,
        "--no-agents",
        help="Do not write the polycheck-reviewer subagent definitions.",
    ),
    agents_only: bool = typer.Option(
        False,
        "--agents-only",
        help="Write only the polycheck-reviewer subagent definitions.",
    ),
    git_hook: str = typer.Option(
        None,
        "--git-hook",
        help="Install a git hook as a dev-cycle trigger. Supported: pre-push.",
    ),
) -> None:
    """Initialize /polycheck for Kilo Code, OpenCode, and Claude Code."""
    selected_scope = scope.lower()
    if selected_scope not in {"global", "project"}:
        console.print("[red]Invalid scope. Use --scope global or --scope project.[/red]")
        raise typer.Exit(2)
    if no_mcp and mcp_only:
        console.print("[red]Use either --no-mcp or --mcp-only, not both.[/red]")
        raise typer.Exit(2)
    if no_agents and agents_only:
        console.print("[red]Use either --no-agents or --agents-only, not both.[/red]")
        raise typer.Exit(2)
    if git_hook and git_hook not in GIT_HOOKS:
        console.print(
            f"[red]Unknown git hook '{git_hook}'. Supported: {', '.join(GIT_HOOKS)}.[/red]"
        )
        raise typer.Exit(2)
    if git_hook and selected_scope != "project":
        console.print(
            "[red]--git-hook writes into .git/hooks and requires --scope project.[/red]"
        )
        raise typer.Exit(2)

    try:
        selected_hosts = normalize_hosts(host)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    project_root = Path.cwd().resolve()
    home = Path.home().resolve()
    plan = build_plan(
        hosts=selected_hosts,
        scope=selected_scope,
        project_root=project_root,
        home=home,
        include_workflows=not mcp_only and not agents_only,
        include_mcp=not no_mcp and not agents_only,
        include_agents=not no_agents and not mcp_only,
        git_hook=git_hook,
    )

    console.print(f"[bold]polycheck init[/bold] — {selected_scope} scope")
    for action in plan:
        console.print(format_action(action))

    if dry_run:
        console.print("\nDry run complete; no files were changed.")
        return

    if not yes and not typer.confirm("Write these files?"):
        raise typer.Abort()

    results = apply_plan(plan, force=force, dry_run=False)
    for action in results:
        console.print(format_action(action))

    _print_init_next_steps(selected_hosts, selected_scope)


def _print_init_next_steps(hosts: list[str], scope: str) -> None:
    """Print concise next steps after initialization."""
    console.print("\nNext steps:")
    console.print("  1. Restart your LLM coding assistant so it reloads commands and MCP servers.")
    console.print("  2. Run `/polycheck` in any project.")


@app.command()
def detected(
    path: Path = typer.Argument(Path("."), exists=True, resolve_path=True),
) -> None:
    """Show the languages polycheck detected in PATH."""
    for lang in detect(path):
        console.print(f"  [cyan]{lang.slug}[/cyan]")


@app.command(name="prompt")
def show_prompt(
    plain: bool = typer.Option(
        False,
        "--plain",
        help="Print the prompt without the surrounding explanation (for piping)",
    ),
) -> None:
    """Print the LLM triage prompt.

    Pipe the output to your LLM tool of choice, or copy it from the
    terminal. Use ``--plain`` to drop the surrounding explanation.
    """
    from .mcp_server import _TRIAGE_PROMPT
    if plain:
        typer.echo(_TRIAGE_PROMPT)
        return
    console.print("[bold]The LLM triage prompt[/bold]")
    console.print(
        "Pipe this to your LLM tool, or copy-paste it together with the "
        "markdown report into a chat. Use [cyan]--plain[/cyan] to drop "
        "this explanation."
    )
    console.print()
    console.print("─" * 60)
    console.print(_TRIAGE_PROMPT)
    console.print("─" * 60)


@app.command(name="doctor")
def doctor(
    fail_on_missing: bool = typer.Option(
        False,
        "--fail-on-missing",
        help="Exit non-zero if any bundled analyzer is missing. Default: exit 0.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print a machine-readable readiness payload instead of the "
        "table — tools with profile participation, system prerequisites "
        "(Docker for sonarless), profile guidance, and the install "
        "policy. Designed for LLM coding assistants.",
    ),
) -> None:
    """Check which bundled analyzers are installed and which are missing.

    For each missing tool, prints the install command. For each
    installed tool, prints its version. This is the recommended first
    step on a fresh machine.
    """
    if as_json:
        from .readiness import readiness

        payload = readiness(default_registry)
        console.print_json(json.dumps(payload))
        if payload["summary"]["missing"] and fail_on_missing:
            raise typer.Exit(code=1)
        return

    table = Table(title="polycheck doctor")
    table.add_column("Tool", style="cyan")
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Install")
    missing = 0
    for cls in sorted(default_registry.all(), key=lambda c: c.name):
        inst = cls()
        if inst.is_installed():
            table.add_row(
                inst.name, "[green]installed[/green]", inst.version() or "?", ""
            )
        else:
            missing += 1
            table.add_row(
                inst.name, "[yellow]missing[/yellow]", "—", inst.install_hint()
            )
    console.print(table)
    if missing:
        console.print(
            f"\n[yellow]{missing} tool(s) missing.[/yellow] "
            f"Install them with: [cyan]polycheck install[/cyan]"
        )
        if fail_on_missing:
            raise typer.Exit(code=1)
    console.print("\n[green]Doctor complete.[/green]")


@app.command(name="install")
def install_cmd(
    tool: list[str] = typer.Argument(
        None, help="Specific tool name(s) to install (default: all missing)"
    ),
    all_tools: bool = typer.Option(
        False, "--all", help="Install every bundled tool, not just the missing ones"
    ),
    yes: bool = typer.Option(
        False, "-y", "--yes", help="Skip confirmation prompt"
    ),
) -> None:
    """Install missing bundled analyzers.

    With no arguments, installs every tool whose ``is_installed()`` is
    currently False. Use ``--all`` to reinstall everything. Use
    ``polycheck install ruff mypy`` to install specific tools.

    Installation is delegated to the underlying package manager
    (``pipx``, ``npm``, ``brew``, ``apt``, …) as configured per-tool
    in the ``installer`` class attribute.
    """
    targets = _resolve_install_targets(tool, all_tools)
    if not targets:
        console.print("[green]Nothing to install — all selected tools are present.[/green]")
        return

    _confirm_install(targets, yes)
    failed = _execute_installs(targets)

    if failed:
        raise typer.Exit(code=1)


def _resolve_install_targets(tool: list[str] | None, all_tools: bool) -> list[type]:
    """Determine which tools to install based on CLI arguments."""
    if tool:
        return _resolve_named_tools(tool)
    if all_tools:
        return list(default_registry.all())
    return [cls for cls in default_registry.all() if not cls().is_installed()]


def _resolve_named_tools(names: list[str]) -> list[type[Tool]]:
    """Resolve tool names to tool classes, exiting on unknown names."""
    targets = []
    for name in names:
        cls = default_registry.get(name)
        if cls is None:
            console.print(f"[red]Unknown tool:[/red] {name}")
            raise typer.Exit(code=1)
        targets.append(cls)
    return targets


def _confirm_install(targets: list[type[Tool]], yes: bool) -> None:
    """Show installation plan and confirm with user."""
    console.print(f"Will install {len(targets)} tool(s):")
    for cls in targets:
        console.print(f"  [cyan]{cls.name}[/cyan]: {cls().install_hint()}")
    if not yes and not typer.confirm("Proceed?"):
        raise typer.Abort()


def _execute_installs(targets: list[type[Tool]]) -> list[tuple[str, str]]:
    """Install each target tool, returning list of failures."""
    failed: list[tuple[str, str]] = []
    for cls in targets:
        inst = cls()
        ok, msg = inst.install()
        if ok:
            console.print(f"  [green]✓[/green] {msg}")
        else:
            console.print(f"  [red]✗[/red] {inst.name}: {msg}")
            failed.append((inst.name, msg))
    return failed


def _auto_install_missing(
    *,
    only: list[str] | None,
    repo: Path,
) -> None:
    """Used by ``polycheck run --install`` to install any missing tools
    that would otherwise be skipped."""
    missing = _missing_tools(repo, only=only, exclude=set())
    if not missing:
        return
    console.print(
        f"[cyan]--install:[/cyan] installing {len(missing)} missing tool(s)…"
    )
    for cls in missing:
        inst = cls()
        ok, msg = inst.install()
        if ok:
            console.print(f"  [green]✓[/green] {msg}")
        else:
            console.print(f"  [red]✗[/red] {inst.name}: {msg}")


def _missing_tools(
    repo: Path,
    *,
    only: list[str] | None,
    exclude: set[str],
    config: Config | None = None,
) -> list[type[Tool]]:
    """Tool classes that *would* be applicable to ``repo`` but whose
    binary is not on PATH. Excludes any name in ``exclude`` (typically
    the set of tools that already ran).
    """
    langs = detect(repo)
    lang_slugs = {lang.slug for lang in langs}
    out: list[type[Tool]] = []
    for cls in default_registry.all():
        if cls.name in exclude:
            continue
        if only and cls.name not in only:
            continue
        if not _tool_enabled(cls, config):
            continue
        if not _language_matches(cls, lang_slugs):
            continue
        inst = cls()
        if not inst.is_installed():
            if not _tool_applicable(cls, repo):
                continue
            out.append(cls)
    return out


def _tool_enabled(cls: type[Tool], config: Config | None) -> bool:
    if config and config.enable and cls.name not in config.enable:
        return False
    if config and cls.name in config.disable:
        return False
    return True


def _language_matches(cls: type[Tool], lang_slugs: set[str]) -> bool:
    if cls.universal:
        return bool(lang_slugs)
    return bool(lang_slugs and any(slug in lang_slugs for slug in cls.languages))


def _tool_applicable(cls: type[Tool], repo: Path) -> bool:
    try:
        return cls().is_applicable(repo)
    except Exception:  # noqa: BLE001 — missing-tool checks should not crash
        return True


def _exit_code(findings: list[Finding], fail_on: str | None) -> int:
    """Return 0 if all findings are below ``fail_on``; 1 otherwise.

    ``None`` means "no gate" (--profile deep) — always exit 0. The
    default is MEDIUM, so LOW and INFO findings don't fail the build.
    Findings in gitignored files are excluded from the gate — they cannot
    reach the repo via push (0.3.3; the buckets stay visible in reports).
    """
    if fail_on is None:
        return 0
    gated = [f for f in findings if f.track != "ignored"]
    if not gated:
        return 0
    from .finding import Severity
    try:
        threshold = Severity[fail_on]
    except KeyError:
        return 0
    return 1 if any(f.severity >= threshold for f in gated) else 0


def main() -> None:
    """Entry point declared in pyproject.toml."""
    app()


if __name__ == "__main__":
    sys.exit(app())
