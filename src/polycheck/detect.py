"""Language detection.

A polyglot repo can contain many languages. We detect each language
by looking for a marker file at the repo root (or anywhere, for some
languages). The detection is conservative — a missing marker means
"don't run language-specific tools", not "this language is absent".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Language:
    """A detected language in the repo."""

    slug: str           # e.g. "python", "javascript", "typescript"
    display: str        # e.g. "Python", "JavaScript", "TypeScript"
    markers: tuple[str, ...]  # files that indicate this language
    note: str = ""      # human note, e.g. "transpiled to JS"


# Marker-based detection. We deliberately use a *tuple* of file globs per
# language, because any one of them is sufficient. The matcher is
# conservative: missing markers → language not detected, not "absent".
LANGUAGES: tuple[Language, ...] = (
    Language("python", "Python",
             ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
              "Pipfile", "poetry.lock", "uv.lock")),
    Language("javascript", "JavaScript",
             ("package.json", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
              "jsconfig.json")),
    Language("typescript", "TypeScript",
             ("tsconfig.json",)),
    Language("go", "Go",
             ("go.mod", "go.sum")),
    Language("rust", "Rust",
             ("Cargo.toml", "Cargo.lock")),
    Language("java", "Java",
             ("pom.xml", "build.gradle", "build.gradle.kts")),
    Language("ruby", "Ruby",
             ("Gemfile", ".ruby-version")),
    Language("php", "PHP",
             ("composer.json",)),
    Language("csharp", "C# / .NET",
             ()),  # placeholder — no C#-specific tools yet; semgrep covers it
    Language("kotlin", "Kotlin",
             ()),  # placeholder — no Kotlin-specific tools yet; semgrep covers it
    Language("swift", "Swift",
             ("Package.swift",)),
    Language("scala", "Scala",
             ("build.sbt",)),
    Language("elixir", "Elixir",
             ("mix.exs",)),
    Language("haskell", "Haskell",
             ("stack.yaml", "cabal.project")),
    Language("docker", "Docker",
             ("Dockerfile",)),
    Language("github-actions", "GitHub Actions",
             (".github/workflows",)),
    Language("shell", "Shell",
             ()),  # matched by file extension elsewhere
)


def detect(repo: Path) -> list[Language]:
    """Return the languages detected in ``repo``. The order is stable
    (LANGUAGES tuple order), so tests can rely on it.

    Detection is shallow: any marker at the repo root (or under the
    .github/workflows subtree for GitHub Actions) is enough. The
    function does NOT walk the whole tree — that would be slow on
    monorepos, and most tools work off the root anyway.
    """
    repo = Path(repo).resolve()
    if not repo.is_dir():
        raise NotADirectoryError(f"{repo} is not a directory")

    found: list[Language] = []
    for lang in LANGUAGES:
        for marker in lang.markers:
            if marker.endswith("/"):
                # Directory marker (e.g. ".github/workflows")
                if (repo / marker).is_dir():
                    found.append(lang)
                    break
            else:
                if (repo / marker).exists():
                    found.append(lang)
                    break

    # Shell: also detect by file extension if any .sh files exist at root.
    if any(p.suffix == ".sh" for p in repo.iterdir() if p.is_file()):
        if not any(lang.slug == "shell" for lang in found):
            found.append(Language("shell", "Shell", ()))

    return found
