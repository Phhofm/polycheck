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
