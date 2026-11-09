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
# the exclusion is visible and reviewable. The value is EVERY third-party root the module
# imports at module scope, and the skip is taken only when at least one of them is missing.
# Two things that look like shortcuts are not:
#
# - Do not match on the error's name. Which dependency an import trips on first is not
#   something this list can know. The first version of this file keyed on `mcp` and CI's
#   six base-install jobs failed on `anyio`, which `_mcp_server` imports two lines earlier.
# - Do not use the names the extra DECLARES. The rule is what the modules import, which is
#   not the same set: an extra can declare a package no module imports (then its absence
#   would skip a subtree that would have imported fine, silently), and a module can import
#   a root the extra gets only transitively, as `anyio` is here.
#
# `mcp` alone would in fact be sound today, since it is the extra's own distribution name
# and `anyio>=4.9` is a hard requirement of it, so "mcp present, anyio absent" is
# unreachable. Both names are listed anyway: that argument rests on an upstream package's
# requirements, which can change without anyone here touching a line.
#
# Wherever the extra IS installed -- the `dev` group, and CI's `test`, `coverage` and
# `mcp-install` jobs -- every ModuleNotFoundError from these modules fails the test, an
# undeclared dependency included, and their examples run normally. Only a lean install
# (CI's `base-install`, or `uv sync --locked --no-default-groups --group test`) skips them.
OPTIONAL_IMPORTS = {
    # `import anyio.to_thread` and `from mcp.server import MCPServer`, _mcp_server.py:11-15
    "mzmlpy._mcp_server": ("anyio", "mcp"),
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


def _installed(root: str) -> bool:
    """Is this top-level module importable in this environment?"""
    try:
        return importlib.util.find_spec(root) is not None
    except ModuleNotFoundError:
        return False


def _extra_is_absent(roots: tuple[str, ...]) -> bool:
    """True when any root the module needs is missing, so the module cannot import."""
    return not all(_installed(root) for root in roots)


def _import(name: str) -> ModuleType | None:
    """Import one module, tolerating only a named optional extra's absence."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        roots = OPTIONAL_IMPORTS.get(name)
        if roots is None or not _extra_is_absent(roots):
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
