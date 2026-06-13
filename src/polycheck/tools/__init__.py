"""Tool adapters.

The package directory for tool implementations. Each module exports
a class named ``*Tool`` that subclasses :class:`polycheck.tools.base.Tool`.

Concrete tools are auto-discovered by ``ToolRegistry.discover()`` via
``pkgutil.iter_modules``.
"""

# tool modules
