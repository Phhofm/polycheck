"""Tests for the language detector."""
from __future__ import annotations

from pathlib import Path

from polycheck.detect import detect


def test_detect_python(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "main.py").write_text("print('hi')")
    langs = detect(tmp_path)
    slugs = {lang.slug for lang in langs}
    assert "python" in slugs


def test_detect_javascript(tmp_path: Path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "index.js").write_text("// js")
    langs = detect(tmp_path)
    slugs = {lang.slug for lang in langs}
    assert "javascript" in slugs


def test_detect_typescript(tmp_path: Path):
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "index.ts").write_text("// ts")
    langs = detect(tmp_path)
    slugs = {lang.slug for lang in langs}
    assert "typescript" in slugs


def test_detect_docker(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text("FROM scratch")
    langs = detect(tmp_path)
    slugs = {lang.slug for lang in langs}
    assert "docker" in slugs


def test_detect_github_actions(tmp_path: Path):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "workflows").mkdir()
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    langs = detect(tmp_path)
    slugs = {lang.slug for lang in langs}
    assert "github-actions" in slugs


def test_detect_empty(tmp_path: Path):
    langs = detect(tmp_path)
    assert langs == []


def test_detect_multi(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "package.json").write_text("{}")
    langs = detect(tmp_path)
    slugs = {lang.slug for lang in langs}
    assert "python" in slugs
    assert "javascript" in slugs


def test_detect_python_from_subdir_files_without_manifest(tmp_path: Path):
    """Repos like polycheck-less script collections: scripts/*.py with no
    pyproject.toml must still detect Python (first external live test)."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_eval.py").write_text("print('hi')\n")

    slugs = {lang.slug for lang in detect(tmp_path)}

    assert "python" in slugs


def test_detect_typescript_from_subdir_without_tsconfig(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.ts").write_text("const x = 1;\n")

    slugs = {lang.slug for lang in detect(tmp_path)}

    assert "typescript" in slugs


def test_detect_shell_from_nested_script(tmp_path: Path):
    deep = tmp_path / "tools" / "bin"
    deep.mkdir(parents=True)
    (deep / "deploy.sh").write_text("echo hi\n")

    slugs = {lang.slug for lang in detect(tmp_path)}

    assert "shell" in slugs


def test_detect_ignores_vendored_extensions(tmp_path: Path):
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "vendored.py").write_text("x = 1\n")

    slugs = {lang.slug for lang in detect(tmp_path)}

    assert "python" not in slugs
