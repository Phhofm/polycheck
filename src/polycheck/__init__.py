"""polycheck — polyglot static analysis pipeline with LLM-ready output.

The package is structured as:

    polycheck/
    ├── cli.py             # Typer-based CLI entry point
    ├── config.py          # .polycheck.yml loader
    ├── detect.py          # language detection
    ├── finding.py         # unified Finding schema
    ├── registry.py        # tool/plugin registry
    ├── runner.py          # runs tools, collects findings
    ├── reporters/         # JSON, markdown, SARIF output
    ├── tools/             # one module per analyzer
    └── languages/         # per-language tool defaults
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
