"""Polycheck CLI.

Subcommands
-----------

``polycheck run [PATH]``
    Detect languages, run all applicable tools, write reports.

``polycheck list-tools``
    Print every available tool and which languages it supports.

``polycheck explain RULE``
    Print a short explanation of a tool/rule identifier.

``polycheck mcp``
    Start the MCP server (stdio transport).
"""
from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Config
from .detect import detect
from .registry import default_registry
from .reporters import render as render_report
from .runner import Runner, dedupe, filter_by_severity

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
    install: bool = typer.Option(
        False,
        "--install",
        help="Auto-install any missing analyzers before running",
    ),
    fail_on: str = typer.Option(
        "MEDIUM",
        "--fail-on",
        help="Exit non-zero if any finding is at or above this severity (INFO, LOW, MEDIUM, HIGH, CRITICAL). Default MEDIUM.",
    ),
) -> None:
    """Run all applicable tools and write reports."""
    cfg = _load_config(config, path, severity, output, report_dir)
    repo = path.resolve()
    console.print(f"[bold]polycheck[/bold] {__version__} — {repo}")

    _print_detected_languages(repo)

    if install:
        _auto_install_missing(only=tool or None, repo=repo)

    runner = Runner(repo=repo, config=cfg)
    findings, results = runner.run(parallel=parallel, tools=tool or None)

    if not no_dedupe:
        findings = dedupe(findings)
    findings = filter_by_severity(findings, cfg.severity_threshold)

    written = _write_reports(cfg, repo, findings, results)
    _print_summary(results, findings, written)

    failed = [r for r in results if r.status in ("error", "timeout")]
    if failed:
        _print_failures(failed)

    not_run = _missing_tools(repo, only=tool or None, exclude={r.tool for r in results})
    if not_run:
        _print_missing(not_run)

    raise typer.Exit(code=_exit_code(findings, fail_on.upper()))


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
    for r in sorted(results, key=lambda r: r.tool):
        by_tool.add_row(
            r.tool, r.status, str(len(r.findings)), f"{r.duration_sec:.1f}"
        )
    console.print(by_tool)
    console.print(f"\n[bold]{len(findings)}[/bold] findings after filtering")
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
def doctor() -> None:
    """Check which bundled analyzers are installed and which are missing.

    For each missing tool, prints the install command. For each
    installed tool, prints its version. This is the recommended first
    step on a fresh machine.
    """
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
            f"Install them all with: [cyan]polycheck install --all[/cyan]"
        )
        raise typer.Exit(code=1)
    console.print("\n[green]All bundled tools are installed.[/green]")


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


def _resolve_named_tools(names: list[str]) -> list[type]:
    """Resolve tool names to tool classes, exiting on unknown names."""
    targets = []
    for name in names:
        cls = default_registry.get(name)
        if cls is None:
            console.print(f"[red]Unknown tool:[/red] {name}")
            raise typer.Exit(code=1)
        targets.append(cls)
    return targets


def _confirm_install(targets: list[type], yes: bool) -> None:
    """Show installation plan and confirm with user."""
    console.print(f"Will install {len(targets)} tool(s):")
    for cls in targets:
        console.print(f"  [cyan]{cls.name}[/cyan]: {cls().install_hint()}")
    if not yes and not typer.confirm("Proceed?"):
        raise typer.Abort()


def _execute_installs(targets: list[type]) -> list[tuple[str, str]]:
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
) -> list[type]:
    """Tool classes that *would* be applicable to ``repo`` but whose
    binary is not on PATH. Excludes any name in ``exclude`` (typically
    the set of tools that already ran)."""
    langs = detect(repo)
    lang_slugs = {lang.slug for lang in langs}
    out: list[type] = []
    for cls in default_registry.all():
        if cls.name in exclude:
            continue
        if only and cls.name not in only:
            continue
        if not cls.universal and lang_slugs and not any(
            s in lang_slugs for s in cls.languages
        ):
            continue
        if cls.universal and not lang_slugs:
            # A universal tool still won't run on a totally empty
            # repo with no source. Skip it.
            continue
        inst = cls()
        if not inst.is_installed():
            out.append(cls)
    return out


def _exit_code(findings: list, fail_on: str) -> int:
    """Return 0 if all findings are below ``fail_on``; 1 otherwise.

    The default is MEDIUM, so LOW and INFO findings don't fail the build.
    """
    if not findings:
        return 0
    from .finding import Severity
    try:
        threshold = Severity[fail_on]
    except KeyError:
        return 0
    return 1 if any(f.severity >= threshold for f in findings) else 0


def main() -> None:
    """Entry point declared in pyproject.toml."""
    app()


if __name__ == "__main__":
    sys.exit(app())
