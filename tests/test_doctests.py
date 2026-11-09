"""Execute every docstring example in the package."""

from __future__ import annotations

import doctest
import importlib
import importlib.util
import pkgutil
from types import ModuleType

import mzmlpy

# Measured 2026-11-08. Raise these when you add modules or examples; never lower them
# without saying why in the commit message.
MIN_MODULES = 41
MIN_EXAMPLES = 0

# Modules that cannot be imported at all without an optional extra, named one by one so
# the exclusion is visible and reviewable. The value is the extra's own top-level module,
# and the skip is gated on THAT being absent rather than on which name the error happens
# to carry, because a missing extra takes its transitive dependencies with it: without the
# `mcp` extra, `_mcp_server` fails on `anyio` before it ever reaches `mcp.server`, and
# pinning the names would mean editing this list every time an extra changes its own
# dependencies. So wherever the extra IS installed -- the dev group names all four, as do
# the `test`, `coverage` and `mcp-install` CI jobs -- every ModuleNotFoundError from these
# modules fails the test, an undeclared dependency included, and their examples run
# normally. Only a lean install (CI's `base-install`, or
# `uv sync --locked --no-default-groups --group test`) skips them.
OPTIONAL_IMPORTS = {
    "mzmlpy._mcp_server": "mcp",  # imports anyio.to_thread and mcp.server at module scope
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


def _extra_is_absent(root: str) -> bool:
    """Is the optional extra genuinely not installed in this environment?"""
    try:
        return importlib.util.find_spec(root) is None
    except ModuleNotFoundError:
        return True


def _import(name: str) -> ModuleType | None:
    """Import one module, tolerating only a named optional extra's absence."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        extra = OPTIONAL_IMPORTS.get(name)
        if extra is None or not _extra_is_absent(extra):
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
