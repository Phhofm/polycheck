"""Tool registry — the single source of truth for available tools.

The registry collects all bundled tool classes (auto-discovered from the
``polycheck.tools`` subpackage) and lets the runner look them up by
language or applicability.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from pathlib import Path

from .tools.base import Tool


class ToolRegistry:
    """Container for ``Tool`` subclasses.

    Tools are registered either:
      * automatically, by being subclasses of ``Tool`` in the
        ``polycheck.tools`` subpackage (see ``discover()``)
      * programmatically, via ``register()`` (used by tests and by
        downstream packages that want to add their own tools)
    """

    def __init__(self) -> None:
        self._tools: dict[str, type[Tool]] = {}

    def register(self, tool_class: type[Tool]) -> type[Tool]:
        """Register a tool class. Idempotent; same class can be registered
        multiple times. Returns the class for decorator use."""
        if not tool_class.name:
            raise ValueError(f"{tool_class.__name__}.name must be set")
        self._tools[tool_class.name] = tool_class
        return tool_class

    def all(self) -> list[type[Tool]]:
        return list(self._tools.values())

    def get(self, name: str) -> type[Tool] | None:
        return self._tools.get(name)

    def for_language(self, language: str) -> list[type[Tool]]:
        """Tools that advertise support for the given language slug, or
        are universal (i.e. apply to every repo)."""
        out: list[type[Tool]] = []
        for c in self._tools.values():
            if c.universal or language in c.languages:
                out.append(c)
        return out

    def applicable(self, repo: Path) -> list[type[Tool]]:
        """All tools that are both installed and applicable to this repo.

        Note: this instantiates each tool and runs ``is_applicable``.
        Instances are not cached — cheap, no I/O.
        """
        out: list[type[Tool]] = []
        for cls in self._tools.values():
            instance = cls()
            if not instance.is_installed():
                continue
            if not instance.is_applicable(repo):
                continue
            out.append(cls)
        return out

    def discover(self) -> int:
        """Auto-import every module in ``polycheck.tools`` and register
        any ``Tool`` subclasses found. Returns the number of tools
        registered (including ones that were already there)."""
        import inspect
        import sys

        from . import tools as tools_pkg  # local import to avoid cycle

        self._import_tool_modules(tools_pkg)
        self._register_tool_classes(tools_pkg)
        return len(self._tools)

    def _import_tool_modules(self, tools_pkg) -> None:
        """Import all tool modules from the tools package."""
        import sys

        for _finder, name, _is_pkg in pkgutil.iter_modules(tools_pkg.__path__):
            if name == "base" or not name.isidentifier():
                continue
            try:
                importlib.import_module(f"{tools_pkg.__name__}.{name}")  # nosemgrep
            except ImportError as e:
                # A tool may fail to import if its 3rd-party SDK is
                # missing (e.g. knip). Don't fail the whole discovery.
                print(f"polycheck: skipping tool {name}: {e}", file=sys.stderr)

    def _register_tool_classes(self, tools_pkg) -> None:
        """Register all Tool subclasses from imported modules."""
        import inspect
        import sys

        for module_name, module in list(sys.modules.items()):
            if not module_name.startswith(tools_pkg.__name__ + "."):
                continue
            if module_name == tools_pkg.__name__ + ".base":
                continue
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if self._should_register(obj, module_name):
                    self.register(obj)

    def _should_register(self, obj, module_name: str) -> bool:
        """Determine if a class should be registered as a tool."""
        return (
            issubclass(obj, Tool)
            and obj is not Tool
            and obj.__module__ == module_name
        )

    def __iter__(self) -> Iterator[type[Tool]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)


# Module-level singleton. Tests can replace it via monkeypatching the
# ``default_registry`` attribute if they want a clean slate.
default_registry = ToolRegistry()
