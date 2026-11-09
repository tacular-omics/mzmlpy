"""Execute every docstring example in the package."""

from __future__ import annotations

import doctest
import importlib
import pkgutil
from types import ModuleType

import mzmlpy

# Measured 2026-11-08. Raise these when you add modules or examples; never lower them
# without saying why in the commit message.
MIN_MODULES = 41
MIN_EXAMPLES = 0

# Modules that cannot be imported at all without an optional extra, named one by one so
# the exclusion is visible and reviewable. The value is the single top-level module whose
# absence is tolerated: any other missing module, and any other error from the same file,
# still fails this test. `just install` (uv sync --locked) installs the `dev` group, which
# names all four extras, so in CI these modules ARE imported and their examples DO run;
# only a lean install such as `uv sync --locked --no-dev --group test` skips them.
OPTIONAL_IMPORTS = {
    "mzmlpy._mcp_server": "mcp",  # `from mcp.server import MCPServer` at module scope
}


def _walk_error(name: str) -> None:
    """Fail the walk instead of letting pkgutil swallow an ImportError."""
    raise RuntimeError(f"pkgutil.walk_packages could not import {name}")


def _discover() -> list[str]:
    """Every module name in the package, walked rather than hand-listed."""
    names = [mzmlpy.__name__]
    for _finder, name, _ispkg in pkgutil.walk_packages(
        mzmlpy.__path__, prefix=f"{mzmlpy.__name__}.", onerror=_walk_error
    ):
        names.append(name)
    return names


def _import(name: str) -> ModuleType | None:
    """Import one module, tolerating only a named optional extra's absence."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        tolerated = OPTIONAL_IMPORTS.get(name)
        if tolerated is None or error.name != tolerated:
            raise
        return None


def test_docstring_examples() -> None:
    names = _discover()
    assert len(names) >= MIN_MODULES, f"module walk found only {len(names)}"
    stale = sorted(set(OPTIONAL_IMPORTS) - set(names))
    assert not stale, f"OPTIONAL_IMPORTS names modules the walk does not find: {stale}"
    attempted = failed = 0
    for name in names:
        module = _import(name)
        if module is None:
            continue
        result = doctest.testmod(module, verbose=False)
        attempted += result.attempted
        failed += result.failed
    assert failed == 0, f"{failed} of {attempted} docstring examples failed"
    assert attempted >= MIN_EXAMPLES, f"only {attempted} examples ran, expected >= {MIN_EXAMPLES}"
