"""Tests for the runner's filtering logic.

We don't run real tools here — we just verify that the runner
correctly handles enable/disable lists, applicability, and result
shapes. Real tool subprocesses are exercised in the smoke test.
"""
from __future__ import annotations

from pathlib import Path

from polycheck.config import Config
from polycheck.finding import Category, Finding, Severity
from polycheck.runner import dedupe, filter_by_severity, group_by_category
from polycheck.tools.base import Tool


class _StubTool(Tool):
    name = "stub"
    category = Category.LINT
    languages = ["python"]

    def is_applicable(self, repo):
        return True

    def is_installed(self):
        return True

    def run(self, repo):
        return [
            Finding(
                tool="stub", rule="X1", severity=Severity.HIGH,
                category=Category.LINT, message="real", file="a.py", line=1,
            ),
            Finding(
                tool="stub", rule="X1", severity=Severity.HIGH,
                category=Category.LINT, message="dup", file="a.py", line=1,
            ),
            Finding(
                tool="stub", rule="X2", severity=Severity.INFO,
                category=Category.LINT, message="info", file="a.py", line=2,
            ),
        ]


def test_dedupe_collapses_fingerprints():
    f1 = Finding(tool="t", rule="r", severity=Severity.HIGH,
                 category=Category.LINT, message="a", file="x", line=1)
    f2 = Finding(tool="t", rule="r", severity=Severity.LOW,
                 category=Category.LINT, message="b", file="x", line=1)
    out = dedupe([f1, f2])
    assert len(out) == 1
    # The first one wins; severity doesn't affect fingerprint.
    assert out[0].message == "a"


def test_filter_by_severity_threshold():
    f_high = Finding(tool="t", rule="r", severity=Severity.HIGH,
                     category=Category.LINT, message="", file="x", line=1)
    f_low = Finding(tool="t", rule="r", severity=Severity.LOW,
                    category=Category.LINT, message="", file="x", line=2)
    f_info = Finding(tool="t", rule="r", severity=Severity.INFO,
                     category=Category.LINT, message="", file="x", line=3)
    out = filter_by_severity([f_high, f_low, f_info], "MEDIUM")
    assert out == [f_high]
    out = filter_by_severity([f_high, f_low, f_info], "INFO")
    assert len(out) == 3
    out = filter_by_severity([f_high, f_low, f_info], "BOGUS")
    assert len(out) == 3  # unknown threshold → no filtering


def test_group_by_category():
    f1 = Finding(tool="t", rule="r", severity=Severity.HIGH,
                 category=Category.SECURITY, message="", file="x", line=1)
    f2 = Finding(tool="t", rule="r", severity=Severity.HIGH,
                 category=Category.LINT, message="", file="x", line=2)
    out = group_by_category([f1, f2])
    assert Category.SECURITY in out
    assert Category.LINT in out
    assert f1 in out[Category.SECURITY]


def test_runner_picks_up_stub(tmp_path: Path):
    """The runner should at least be able to drive a stub tool end-to-end."""
    from polycheck.registry import ToolRegistry
    from polycheck.runner import Runner

    # Make the dir "look like Python" so the language detector picks it up.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    reg = ToolRegistry()
    reg.register(_StubTool)
    cfg = Config()
    runner = Runner(repo=tmp_path, config=cfg, registry=reg)
    findings, results = runner.run()
    assert len(findings) == 3
    assert results[0].status == "ok"
    assert results[0].tool == "stub"


def test_runner_profile_skips_heavy_and_structural(tmp_path: Path):
    """pr = fast tools only: heavy and structural adapters stay out;
    deep and the default scan keep them."""
    from polycheck.profiles import resolve_profile
    from polycheck.registry import ToolRegistry
    from polycheck.runner import Runner

    class _Heavy(Tool):
        name = "pip-audit"
        category = Category.CVE
        languages = []
        universal = True

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return True

        def run(self, repo):
            return []

    class _Structural(Tool):
        name = "tach"
        category = Category.ARCHITECTURE
        languages = []
        universal = True
        structural = True

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return True

        def run(self, repo):
            return []

    (tmp_path / "app.py").write_text("x = 1\n")
    reg = ToolRegistry()
    reg.register(_Heavy)
    reg.register(_Structural)

    runner = Runner(repo=tmp_path, config=Config(), registry=reg)
    names = lambda results: sorted(r.tool for r in results)  # noqa: E731

    assert names(runner.run(profile=resolve_profile("pr"))[1]) == []
    assert names(runner.run(profile=resolve_profile("deep"))[1]) == [
        "pip-audit", "tach",
    ]
    assert names(runner.run()[1]) == ["pip-audit", "tach"]  # default unchanged


def test_runner_marks_errors(tmp_path: Path):
    class _Boom(Tool):
        name = "boom"
        category = Category.LINT
        languages = ["python"]

        def is_applicable(self, repo):
            return True

        def is_installed(self):
            return True

        def run(self, repo):
            raise RuntimeError("kaboom")

    from polycheck.registry import ToolRegistry
    from polycheck.runner import Runner

    # Create a Python file so the language is detected
    (tmp_path / "test.py").write_text("x = 1\n")

    reg = ToolRegistry()
    reg.register(_Boom)
    runner = Runner(repo=tmp_path, config=Config(), registry=reg)
    findings, results = runner.run()
    assert findings == []
    assert results[0].status == "error"
    assert "kaboom" in (results[0].error or "")


def _finding(rule: str, file: str = "a.py", line: int = 1) -> Finding:
    return Finding(
        tool="t", rule=rule, severity=Severity.MEDIUM,
        category=Category.LINT, message=f"{rule} in {file}:{line}",
        file=file, line=line,
    )


def test_apply_suppressions_rule_only():
    from polycheck.runner import apply_suppressions

    f1 = _finding("F401")
    f2 = _finding("F821")
    out = apply_suppressions([f1, f2], ["F401"])

    assert out == [f2]


def test_apply_suppressions_rule_at_file():
    from polycheck.runner import apply_suppressions

    f1 = _finding("SC2086", file="script.sh")
    f2 = _finding("SC2086", file="other.sh")
    out = apply_suppressions([f1, f2], ["SC2086@script.sh"])

    assert out == [f2]


def test_apply_suppressions_file_match_ignores_fileless():
    """A finding without a file cannot match a rule@file suppression."""
    from polycheck.runner import apply_suppressions

    f1 = _finding("F401")
    f1.file = None
    assert apply_suppressions([f1], ["F401@a.py"]) == [f1]


def test_apply_suppressions_empty_pattern_list_is_identity():
    from polycheck.runner import apply_suppressions

    findings = [_finding("F401"), _finding("F821")]
    assert apply_suppressions(findings, []) == findings
    assert apply_suppressions(findings, ["  "]) == findings


def test_filter_by_baseline_keeps_only_new():
    from polycheck.runner import filter_by_baseline

    known = _finding("F401", line=1)
    new = _finding("F401", line=2)
    baseline = {known.fingerprint()}

    assert filter_by_baseline([known, new], baseline) == [new]


def test_filter_by_baseline_none_is_identity():
    from polycheck.runner import filter_by_baseline

    findings = [_finding("F401")]
    assert filter_by_baseline(findings, None) == findings


def test_actionlint_eligible_when_github_actions_detected(tmp_path: Path):
    """Regression: actionlint declared no languages, so the candidate
    filter silently dropped it from every run (external live test).

    Hermetic (0.3.8, CI failure): the test used the real registry and
    passed only where the actionlint BINARY is installed — CI runs it
    on machines without actionlint. A stub mirroring the real
    declaration (languages=["github-actions"]) tests the filter logic
    without environment dependence."""
    from polycheck.registry import ToolRegistry
    from polycheck.runner import Runner
    from polycheck.tools.base import Tool

    class _ActionlintStub(Tool):
        name = "actionlint"
        category = Category.LINT
        languages = ["github-actions"]
        installer = "github-release:rhysd/actionlint"

        def is_applicable(self, repo):
            return (repo / ".github" / "workflows").is_dir()

        def is_installed(self):
            return True

        def run(self, repo):
            return []

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "tests.yml").write_text("on: [push]\njobs: {}\n")

    reg = ToolRegistry()
    reg.register(_ActionlintStub)
    runner = Runner(repo=tmp_path, config=Config(), registry=reg)
    applicable = {t.name for t in runner._applicable_tools()}

    assert "actionlint" in applicable


def test_annotate_track_status_buckets(tmp_path: Path):
    """Tracked/untracked/ignored classification per finding (0.3.3)."""
    import subprocess

    from polycheck.runner import annotate_track_status

    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "local.env").write_text("SECRET=1\n")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "trace.json").write_text("{}\n")
    (tmp_path / ".gitignore").write_text("logs/\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "app.py", ".gitignore"], cwd=tmp_path, check=True)
    # local.env exists but is neither tracked nor ignored → untracked

    f_tracked = _finding("F401")
    f_tracked.file = "app.py"
    f_ignored = _finding("G101")
    f_ignored.file = "logs/trace.json"
    f_untracked = _finding("E501")
    f_untracked.file = "local.env"
    f_nopath = _finding("DEP001")
    f_nopath.file = None
    f_pseudo = _finding("depcheck-missing")
    f_pseudo.file = "left-pad"  # package name, not a real path

    out = annotate_track_status(
        tmp_path, [f_tracked, f_ignored, f_untracked, f_nopath, f_pseudo]
    )
    by_file = {f.file: f.track for f in out}

    assert by_file["app.py"] == "tracked"
    assert by_file["logs/trace.json"] == "ignored"
    assert by_file["local.env"] == "untracked"
    assert by_file[None] is None
    assert by_file["left-pad"] is None


def test_annotate_track_status_non_git_repo_all_none(tmp_path: Path):
    from polycheck.runner import annotate_track_status

    f = _finding("F401")
    f.file = "app.py"

    out = annotate_track_status(tmp_path, [f])

    assert out[0].track is None


def test_exit_code_ignores_gitignored_findings():
    """The pre-push gate counts findings that can reach the repo —
    gitignored files cannot, so they must not block."""
    from polycheck.cli import _exit_code

    f_ok = _finding("F401")
    f_ok.file = "app.py"
    f_ok.severity = Severity.CRITICAL
    f_ok.track = "tracked"
    f_ignored = _finding("G101")
    f_ignored.file = "logs/trace.json"
    f_ignored.severity = Severity.CRITICAL
    f_ignored.track = "ignored"

    assert _exit_code([f_ignored], "CRITICAL") == 0
    assert _exit_code([f_ok], "CRITICAL") == 1
    assert _exit_code([f_ok, f_ignored], "HIGH") == 1


def test_exit_code_counts_untracked():
    """Untracked files can be added to the commit — they block."""
    from polycheck.cli import _exit_code

    f = _finding("F401")
    f.severity = Severity.HIGH
    f.track = "untracked"

    assert _exit_code([f], "HIGH") == 1
