"""Language-specific defaults.

Each submodule (e.g. ``polycheck.languages.python``) is responsible
for declaring which tools are *always* relevant for its language,
and any default config (e.g. ``ruff`` line-length, ``mypy`` strict
mode). This is the place to add per-language opinions without
hard-coding them in the runner.
"""

# No-op package marker. Concrete defaults are added in submodules.
