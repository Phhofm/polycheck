"""Adapter regression tests for the analyzers that were silently broken.

These tests capture the adapter contract that the seeded-defect verifier
(implementation_plan 1.13) relies on:

* eslint builds a valid argv both for a PATH eslint and for the npx fallback.
* shellcheck receives file arguments, never the directory `.`.
* gitleaks writes its JSON report to --report-path (parsed from the file),
  scans the working tree (--no-git), and surfaces real failures as errors.
* ruff severity mapping ranks bug-shaped rules above style noise.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from polycheck.finding import Category, Severity
from polycheck.tools.base import npx_command
from polycheck.tools.eslint import EslintTool
from polycheck.tools.gitleaks import GitleaksTool
from polycheck.tools.ruff import RuffTool
from polycheck.tools.shellcheck import ShellcheckTool


def test_eslint_argv_has_no_duplicate_when_on_path(monkeypatch, tmp_path: Path):
    (tmp_path / "app.js").write_text("const x = 1;\n")
    monkeypatch.setattr(
        "polycheck.tools.eslint.shutil.which",
        lambda name: "/usr/local/bin/eslint" if name == "eslint" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.eslint.subprocess.run", fake_run)

    EslintTool().run(tmp_path)

    assert captured["cmd"] == ["eslint", "--format=json", "--no-warn-ignored", "app.js"]


def test_eslint_falls_back_to_npx_with_eslint_arg(monkeypatch, tmp_path: Path):
    (tmp_path / "app.js").write_text("const x = 1;\n")
    monkeypatch.setattr(
        "polycheck.tools.eslint.shutil.which",
        lambda name: "/usr/local/bin/npx" if name == "npx" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.eslint.subprocess.run", fake_run)

    EslintTool().run(tmp_path)

    assert captured["cmd"] == [
        *npx_command(), "eslint", "--format=json", "--no-warn-ignored", "app.js",
    ]


def test_shellcheck_receives_files_not_directory(monkeypatch, tmp_path: Path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "deploy.sh").write_text("echo hi\n")
    (tmp_path / "setup.sh").write_text("echo hi\n")

    monkeypatch.setattr(
        "polycheck.tools.shellcheck.shutil.which",
        lambda name: "/usr/bin/shellcheck" if name == "shellcheck" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.shellcheck.subprocess.run", fake_run)

    findings = ShellcheckTool().run(tmp_path)

    assert findings == []
    assert "." not in captured["cmd"]
    assert captured["cmd"][:4] == ["shellcheck", "-f", "gcc", "--severity=style"]
    # Path separators differ on Windows; compare as POSIX-style paths.
    files = sorted(Path(f).as_posix() for f in captured["cmd"][4:])
    assert files == ["scripts/deploy.sh", "setup.sh"]


def test_shellcheck_returns_empty_without_shell_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "polycheck.tools.shellcheck.shutil.which",
        lambda name: "/usr/bin/shellcheck" if name == "shellcheck" else None,
    )
    called = {"run": False}

    def fake_run(cmd, **kwargs):
        called["run"] = True
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.shellcheck.subprocess.run", fake_run)

    assert ShellcheckTool().run(tmp_path) == []
    assert called["run"] is False


def _fake_gitleaks(monkeypatch, tmp_path: Path, returncode: int, report: list | None):
    monkeypatch.setattr(
        "polycheck.tools.gitleaks.shutil.which",
        lambda name: "/usr/bin/gitleaks" if name == "gitleaks" else None,
    )
    captured = {}
    written_configs = []

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        if "--config" in cmd:
            config_path = Path(cmd[cmd.index("--config") + 1])
            written_configs.append(config_path.read_text(encoding="utf-8"))
        if report is not None:
            report_path = Path(cmd[cmd.index("--report-path") + 1])
            report_path.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.gitleaks.subprocess.run", fake_run)
    captured["configs"] = written_configs
    return captured


def test_gitleaks_parses_report_file_and_scans_working_tree(
    monkeypatch, tmp_path: Path,
):
    report = [{
        "RuleID": "aws-access-key-id",
        "File": "src/config.py",
        "StartLine": 3,
        "StartColumn": 7,
        "Description": "AWS Access Key",
        "Match": "AKIA********",
    }]
    captured = _fake_gitleaks(monkeypatch, tmp_path, returncode=1, report=report)

    findings = GitleaksTool().run(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "aws-access-key-id"
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].file == "src/config.py"
    assert findings[0].line == 3
    assert "--no-git" in captured["cmd"]
    assert "--report-path" in captured["cmd"]
    assert "--report-format" in captured["cmd"]
    # The generated config must exclude polycheck's own artifacts and
    # vendored trees — otherwise gitleaks re-scans our report files.
    assert captured["configs"], "no --config written"
    assert "polycheck" in captured["configs"][0]
    assert "node_modules/" in captured["configs"][0]


def test_gitleaks_no_report_file_means_no_findings(monkeypatch, tmp_path: Path):
    _fake_gitleaks(monkeypatch, tmp_path, returncode=0, report=None)

    assert GitleaksTool().run(tmp_path) == []


def test_gitleaks_surfaces_real_failures_as_errors(monkeypatch, tmp_path: Path):
    _fake_gitleaks(monkeypatch, tmp_path, returncode=2, report=None)

    with pytest.raises(RuntimeError, match="gitleaks exited 2"):
        GitleaksTool().run(tmp_path)


def _fake_ruff(monkeypatch, tmp_path: Path, items: list):
    monkeypatch.setattr(
        "polycheck.tools.ruff.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps(items), stderr="",
        ),
    )


def test_ruff_severity_mapping_ranks_bugs_above_style(monkeypatch, tmp_path: Path):
    items = [
        {"code": "F821", "message": "undefined name 'x'",
         "location": {"row": 1, "column": 1}, "filename": "a.py", "fix": None},
        {"code": "E722", "message": "Do not use bare except",
         "location": {"row": 2, "column": 1}, "filename": "a.py", "fix": None},
        {"code": "N801", "message": "Class naming style",
         "location": {"row": 3, "column": 1}, "filename": "a.py", "fix": None},
        {"code": "E501", "message": "Line too long",
         "location": {"row": 4, "column": 1}, "filename": "a.py", "fix": None},
    ]
    _fake_ruff(monkeypatch, tmp_path, items)

    findings = RuffTool().run(tmp_path)
    by_rule = {f.rule: f.severity for f in findings}

    assert by_rule["F821"] is Severity.HIGH
    assert by_rule["E722"] is Severity.MEDIUM
    assert by_rule["N801"] is Severity.INFO
    assert by_rule["E501"] is Severity.LOW


# --- parsers verified against real tool output (mypy/shellcheck/vulture/
# --- deptry were silently returning nothing before these fixes)


def test_mypy_parses_show_column_output(monkeypatch, tmp_path: Path):
    from polycheck.tools.mypy import MypyTool

    (tmp_path / "app.py").write_text("x: int = 'bad'\n")
    monkeypatch.setattr(
        "polycheck.tools.mypy.shutil.which",
        lambda name: "/usr/local/bin/mypy" if name == "mypy" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.mypy.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1,
            stdout="app.py:3:10: error: Incompatible types in assignment "
                   '(expression has type "str", variable has type "int")  [assignment]\n',
            stderr="",
        ),
    )

    findings = MypyTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "assignment"
    assert f.severity is Severity.HIGH
    assert f.file == "app.py"
    assert f.line == 3
    assert f.column == 10


def test_shellcheck_parses_gcc_note_level(monkeypatch, tmp_path: Path):
    (tmp_path / "script.sh").write_text("echo $HOME\n")
    monkeypatch.setattr(
        "polycheck.tools.shellcheck.shutil.which",
        lambda name: "/usr/bin/shellcheck" if name == "shellcheck" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.shellcheck.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1,
            stdout="script.sh:2:6: note: Double quote to prevent globbing "
                   "and word splitting. [SC2086]\n",
            stderr="",
        ),
    )

    findings = ShellcheckTool().run(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "SC2086"
    assert findings[0].severity is Severity.LOW
    assert findings[0].line == 2


def test_vulture_parses_output_despite_finding_count_exit_code(
    monkeypatch, tmp_path: Path,
):
    from polycheck.tools.vulture import VultureTool

    (tmp_path / "app.py").write_text("import os\n")
    monkeypatch.setattr(
        "polycheck.tools.vulture.shutil.which",
        lambda name: "/usr/local/bin/vulture" if name == "vulture" else None,
    )
    # vulture exits with the number of findings (3 here), not 0/1.
    monkeypatch.setattr(
        "polycheck.tools.vulture.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 3,
            stdout="app.py:1: unused import 'os' (90% confidence)\n"
                   "app.py:3: unused variable 'x' (60% confidence)\n"
                   "app.py:5: unused function 'unused_helper' (60% confidence)\n",
            stderr="",
        ),
    )

    findings = VultureTool().run(tmp_path)

    assert len(findings) == 3
    assert findings[0].rule == "unused-import"
    assert findings[2].message == "Unused function 'unused_helper'"


def test_tsc_argv_has_no_duplicate_when_on_path(monkeypatch, tmp_path: Path):
    from polycheck.tools.tsc import TscTool

    monkeypatch.setattr(
        "polycheck.tools.tsc.shutil.which",
        lambda name: "/usr/local/bin/tsc" if name == "tsc" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.tsc.subprocess.run", fake_run)

    TscTool().run(tmp_path)

    assert captured["cmd"] == ["tsc", "--noEmit", "--pretty", "false"]


def test_tsc_parses_real_output_format(monkeypatch, tmp_path: Path):
    from polycheck.tools.tsc import TscTool

    monkeypatch.setattr(
        "polycheck.tools.tsc.shutil.which",
        lambda name: "/usr/local/bin/tsc" if name == "tsc" else None,
    )
    # Verbatim line from `tsc --noEmit --pretty false` on bad.ts.
    monkeypatch.setattr(
        "polycheck.tools.tsc.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 2,
            stdout="bad.ts(1,7): error TS2322: Type 'string' is not "
                   "assignable to type 'number'.\n",
            stderr="",
        ),
    )

    findings = TscTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "TS2322"
    assert f.severity is Severity.HIGH
    assert f.file == "bad.ts"
    assert f.line == 1
    assert f.column == 7


def test_depcheck_parses_heading_and_bullet_format(monkeypatch, tmp_path: Path):
    from polycheck.tools.depcheck import DepcheckTool

    monkeypatch.setattr(
        "polycheck.tools.depcheck.shutil.which",
        lambda name: "/usr/local/bin/depcheck" if name == "depcheck" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.depcheck.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 0,
            stdout="Unused dependencies\n* left-pad\nUnused devDependencies\n"
                   "* eslint\n* typescript\n",
            stderr="",
        ),
    )

    findings = DepcheckTool().run(tmp_path)

    assert len(findings) == 3
    assert findings[0].rule == "depcheck-unused"
    assert findings[0].file == "left-pad"
    assert findings[1].file == "eslint"


def test_deptry_reads_stderr_findings(monkeypatch, tmp_path: Path):
    from polycheck.tools.deptry import DeptryTool

    monkeypatch.setattr(
        "polycheck.tools.deptry.shutil.which",
        lambda name: "/usr/local/bin/deptry" if name == "deptry" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.deptry.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1, stdout="Scanning 1 file...\n",
            stderr="pyproject.toml: DEP002 'requests' defined as a dependency "
                   "but not used in the codebase\n",
        ),
    )

    findings = DeptryTool().run(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "DEP002"


def test_knip_argv_has_no_duplicate_when_on_path(monkeypatch, tmp_path: Path):
    from polycheck.tools.knip import KnipTool

    monkeypatch.setattr(
        "polycheck.tools.knip.shutil.which",
        lambda name: "/usr/local/bin/knip" if name == "knip" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.knip.subprocess.run", fake_run)

    KnipTool().run(tmp_path)

    assert captured["cmd"] == ["knip", "--reporter=json", "--no-progress"]


def test_depcheck_argv_has_no_duplicate_when_on_path(monkeypatch, tmp_path: Path):
    from polycheck.tools.depcheck import DepcheckTool

    monkeypatch.setattr(
        "polycheck.tools.depcheck.shutil.which",
        lambda name: "/usr/local/bin/depcheck" if name == "depcheck" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.depcheck.subprocess.run", fake_run)

    DepcheckTool().run(tmp_path)

    assert captured["cmd"] == ["depcheck", ".", "-q", "--no-dev"]


def test_deptry_parses_file_level_findings(monkeypatch, tmp_path: Path):
    from polycheck.tools.deptry import DeptryTool

    monkeypatch.setattr(
        "polycheck.tools.deptry.shutil.which",
        lambda name: "/usr/local/bin/deptry" if name == "deptry" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.deptry.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1,
            stdout="pyproject.toml: DEP002 'requests' defined as a dependency "
                   "but not used in the codebase\n",
            stderr="",
        ),
    )

    findings = DeptryTool().run(tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule == "DEP002"
    assert f.file == "pyproject.toml"
    assert f.line is None
    assert "requests" in f.message


# --- vendored/build dirs must never be scanned (false-positive source) ---


def _seed_noisy_repo(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import os\n")
    (tmp_path / "app.js").write_text("const x = 1;\n")
    (tmp_path / "script.sh").write_text("echo hi\n")
    (tmp_path / "Dockerfile").write_text("FROM ubuntu\n")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "vendored.py").write_text("x = 1\n")
    (venv / "vendored.js").write_text("var x = 1;\n")
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "Dockerfile").write_text("FROM node\n")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("var y = 2;\n")


def test_iter_source_files_skips_vendored_dirs(tmp_path: Path):
    from polycheck.tools.base import iter_source_files

    _seed_noisy_repo(tmp_path)

    rel = [p.as_posix() for p in iter_source_files(tmp_path, ("*.py", "*.js"))]

    assert "app.py" in rel
    assert "app.js" in rel
    assert not any(".venv" in p for p in rel)
    assert not any("node_modules" in p for p in rel)
    assert not any("dist/" in p for p in rel)


def test_mypy_scans_only_project_files(tmp_path: Path, monkeypatch):
    from polycheck.tools.mypy import MypyTool

    _seed_noisy_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.mypy.shutil.which",
        lambda name: "/usr/local/bin/mypy" if name == "mypy" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.mypy.subprocess.run", fake_run)

    MypyTool().run(tmp_path)

    py_args = [a for a in captured["cmd"] if a.endswith(".py")]
    assert py_args == ["app.py"]
    assert not any(".venv" in a for a in captured["cmd"])


def test_eslint_scans_only_project_files(tmp_path: Path, monkeypatch):
    _seed_noisy_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.eslint.shutil.which",
        lambda name: "/usr/local/bin/eslint" if name == "eslint" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr("polycheck.tools.eslint.subprocess.run", fake_run)

    EslintTool().run(tmp_path)

    targets = [a for a in captured["cmd"][3:]]
    assert targets == ["app.js"]
    assert not any(".venv" in a or "dist" in a for a in captured["cmd"])


def test_shellcheck_skips_vendored_scripts(tmp_path: Path, monkeypatch):
    _seed_noisy_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.shellcheck.shutil.which",
        lambda name: "/usr/bin/shellcheck" if name == "shellcheck" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.shellcheck.subprocess.run", fake_run)

    ShellcheckTool().run(tmp_path)

    assert captured["cmd"][4:] == ["script.sh"]


def test_hadolint_skips_dockerfiles_in_node_modules(tmp_path: Path, monkeypatch):
    from polycheck.tools.hadolint import HadolintTool

    _seed_noisy_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.hadolint.shutil.which",
        lambda name: "/usr/local/bin/hadolint" if name == "hadolint" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.hadolint.subprocess.run", fake_run)

    HadolintTool().run(tmp_path)

    assert captured["cmd"][4:] == ["Dockerfile"]


def test_vulture_scans_only_project_files(tmp_path: Path, monkeypatch):
    from polycheck.tools.vulture import VultureTool

    _seed_noisy_repo(tmp_path)
    monkeypatch.setattr(
        "polycheck.tools.vulture.shutil.which",
        lambda name: "/usr/local/bin/vulture" if name == "vulture" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.vulture.subprocess.run", fake_run)

    VultureTool().run(tmp_path)

    py_args = [a for a in captured["cmd"] if a.endswith(".py")]
    assert py_args == ["app.py"]


# --- scb-check (SlopCodeBench verbosity/erosion) ---


def test_scb_check_parses_real_output_shapes(monkeypatch, tmp_path: Path):
    from polycheck.tools.scb_check import ScbCheckTool

    (tmp_path / "app.py").write_text("x = 1\n")
    monkeypatch.setattr(
        "polycheck.tools.scb_check.shutil.which",
        lambda name: "/usr/bin/scb-check" if name == "scb-check" else None,
    )
    # Verbatim shapes from real scb-check 0.x output.
    stdout = (
        "warning[for-range-len]: `for i in range(len(x))` - use `enumerate(x)` or iterate `x` directly\n"
        "  ┌─ slop.py:3:5\n"
        "  │\n"
        "3 │     for i in range(len(files)):\n"
        "  │\n"
        "\n"
        "warning[dict-get-default-none]: `d.get(k, None)` - drop the `None`, it is already the default\n"
        "  ┌─ slop.py:8:12\n"
        "  │\n"
        "\n"
        "erosion: function `run` exceeds complexity threshold\n"
        "   ┌─ src/cli.py:84\n"
        "   │\n"
        "   = complexity: 12, sloc: 63 (threshold: complexity > 10)\n"
        "\n"
        "erosion: function `parse` exceeds cognitive complexity threshold\n"
        "   ┌─ src/parser.py:20\n"
        "   │\n"
        "   = cognitive complexity: 13, sloc: 84 (threshold: cognitive complexity > 10)\n"
        "\n"
        "duplicate-structure: duplicated block (3 lines, 2 instances)\n"
        "    ┌─ src/a.py:10\n"
        "    │\n"
        "    ┌─ src/b.py:20\n"
        "    │\n"
    )
    monkeypatch.setattr(
        "polycheck.tools.scb_check.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr=""),
    )

    findings = ScbCheckTool().run(tmp_path)

    by_rule: dict[str, list] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    assert len(by_rule["for-range-len"]) == 1
    f = by_rule["for-range-len"][0]
    assert f.file == "slop.py" and f.line == 3 and f.column == 5
    assert f.severity is Severity.LOW and f.category is Category.LINT

    assert by_rule["dict-get-default-none"][0].line == 8

    assert by_rule["cyclomatic-erosion"][0].file == "src/cli.py"
    assert by_rule["cyclomatic-erosion"][0].line == 84
    assert by_rule["cyclomatic-erosion"][0].severity is Severity.MEDIUM
    assert by_rule["cyclomatic-erosion"][0].category is Category.COMPLEXITY
    assert by_rule["cognitive-erosion"][0].line == 20
    assert by_rule["cognitive-erosion"][0].category is Category.COMPLEXITY

    assert len(by_rule["duplicate-structure"]) == 1
    dup = by_rule["duplicate-structure"][0]
    assert dup.file == "src/a.py" and dup.line == 10
    assert dup.category is Category.DUPLICATION
    assert "2 instances" in dup.message


def test_scb_check_clean_run_returns_empty(monkeypatch, tmp_path: Path):
    from polycheck.tools.scb_check import ScbCheckTool

    monkeypatch.setattr(
        "polycheck.tools.scb_check.shutil.which",
        lambda name: "/usr/bin/scb-check" if name == "scb-check" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.scb_check.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )

    assert ScbCheckTool().run(tmp_path) == []


def test_scb_check_usage_error_surfaces(monkeypatch, tmp_path: Path):
    from polycheck.tools.scb_check import ScbCheckTool

    monkeypatch.setattr(
        "polycheck.tools.scb_check.shutil.which",
        lambda name: "/usr/bin/scb-check" if name == "scb-check" else None,
    )
    monkeypatch.setattr(
        "polycheck.tools.scb_check.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 2, stdout="", stderr="bad config"),
    )

    with pytest.raises(RuntimeError, match="scb-check exited 2"):
        ScbCheckTool().run(tmp_path)


def test_iter_source_files_respects_gitignore(tmp_path: Path):
    """Git repos: files ignored by .gitignore must never be scanned —
    foreign harness code in gitignored dirs is the #1 noise source."""
    import subprocess

    from polycheck.tools.base import iter_source_files

    (tmp_path / "script.sh").write_text("echo hi\n")
    logs = tmp_path / "logs" / "run_evaluation" / "case1"
    logs.mkdir(parents=True)
    (logs / "eval.sh").write_text("echo foreign\n")
    (tmp_path / ".gitignore").write_text("logs/\n")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    rel = [p.as_posix() for p in iter_source_files(tmp_path, ("*.sh",))]

    assert rel == ["script.sh"]


def test_iter_source_files_non_git_falls_back_to_walker(tmp_path: Path):
    from polycheck.tools.base import iter_source_files

    (tmp_path / "script.sh").write_text("echo hi\n")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "x.sh").write_text("echo v\n")

    rel = [p.as_posix() for p in iter_source_files(tmp_path, ("*.sh",))]

    assert rel == ["script.sh"]


def test_mypy_receives_extra_args_from_config(tmp_path: Path, monkeypatch):
    """Meta-finding #4: `.polycheck.yml` extra_args must reach the tool's
    command line (mypy --python-executable for project venvs)."""
    from polycheck.config import Config
    from polycheck.tools.mypy import MypyTool

    (tmp_path / "app.py").write_text("import yaml\n")
    cfg = Config()
    cfg.extra_args = {"mypy": ["--python-executable", ".venv/bin/python"]}

    monkeypatch.setattr(
        "polycheck.tools.mypy.shutil.which",
        lambda name: "/usr/local/bin/mypy" if name == "mypy" else None,
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("polycheck.tools.mypy.subprocess.run", fake_run)

    MypyTool(config=cfg).run(tmp_path)

    assert "--python-executable" in captured["cmd"]
    assert ".venv/bin/python" in captured["cmd"]


def test_tool_without_config_has_no_extra_args(tmp_path: Path):
    from polycheck.tools.mypy import MypyTool

    tool = MypyTool()
    assert tool.extra_args() == []


def test_gitleaks_allowlist_excludes_gitignored_paths(monkeypatch, tmp_path: Path):
    """Bigger-repo live test: ~1690 gitleaks hits came from gitignored
    artifacts (build outputs, traces, backups). The generated config must
    exclude the repo's ignored paths too."""
    import subprocess

    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / ".gitignore").write_text("client/test-results/\ndb_backup/\n")
    traces = tmp_path / "client" / "test-results"
    traces.mkdir(parents=True)
    (traces / "trace.json").write_text('{"jwt": "x"}\n')
    backup = tmp_path / "db_backup"
    backup.mkdir()
    (backup / "dump.sql").write_text("-- dump\n")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    monkeypatch.setattr(
        "polycheck.tools.gitleaks.shutil.which",
        lambda name: "/usr/bin/gitleaks" if name == "gitleaks" else None,
    )
    captured: dict = {}
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        if "--config" in cmd:
            config_arg = cmd[cmd.index("--config") + 1]
            captured["config"] = Path(config_arg).read_text(encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        # git ls-files from _ignored_paths must run for real
        return real_run(cmd, **kwargs)

    monkeypatch.setattr("polycheck.tools.gitleaks.subprocess.run", fake_run)

    GitleaksTool().run(tmp_path)

    assert captured["cmd"], "gitleaks never ran"
    config = captured["config"]
    assert "test-results" in config, "gitignored dir missing from allowlist"
    assert "db_backup" in config
