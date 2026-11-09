"""Execute every docstring example in the package."""

from __future__ import annotations

import doctest
import importlib
import importlib.util
import pkgutil
from types import ModuleType

import pytest

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


def test_optional_gate_matches_the_environment() -> None:
    """The gate's verdict has to match what importing the gated module actually does.

    Without this the gate certifies itself. A key naming a root no install provides reads
    as "extra absent" in every environment, the module is dropped everywhere, and nothing
    in this file notices: :data:`MIN_MODULES` counts the names the walk yields, and the
    walk yields a module whether or not it imports, so the count does not move; and the
    package attempts 0 examples today with :data:`MIN_EXAMPLES` at 0, so the examples that
    stop running are not visible in that number either. Both floors are met by a gate that
    has gone wrong, in both directions, which is why the verdict is checked here against
    the import -- the one thing the key cannot influence.

    Three outcomes, each asserted rather than assumed. The extra is present, so the module
    must import. The extra is absent and the module fails, so the root it failed on must be
    one the key names, or this is a broken module being read as an absent extra. The extra
    is absent and the module imports fine, so the key names something the module does not
    need and a lean install is skipping examples it could have run.

    The third one is asserted per module, and that is sound only because of how
    :data:`OPTIONAL_IMPORTS` is keyed: one entry per module, listing that module's own
    unguarded module-scope roots. Under that invariant an absent root means the import
    cannot succeed, so a module whose verdict is "absent" has to fail.

    Keep that invariant. A key shared across several modules whose roots differ -- one
    entry for a whole subtree -- breaks it, and this assertion then goes red on correct
    code: with a half-installed extra, the subtree members that do not need the missing
    root still import, which is a supported environment with nothing wrong in it. tdfpy
    measured exactly that, `pydantic` present and `mcp` absent, and its gate needs the
    weaker pair instead: every failure names a root the key lists, and at least one failure
    exists. That pair costs real strictness here, so it is not what this file uses --
    measured 2026-11-08 on a two-entry key where one module legitimately fails and the
    other is over-listed, the per-module assertion catches the over-listing and the weaker
    pair passes, because the legitimate failure satisfies it.
    """
    assert OPTIONAL_IMPORTS, "OPTIONAL_IMPORTS is empty, so this test asserts nothing"
    for name, roots in OPTIONAL_IMPORTS.items():
        assert roots, f"{name} is listed with no roots, so every environment reads as present"
        if not _extra_is_absent(roots):
            importlib.import_module(name)
            continue
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            missing = (exc.name or "").split(".")[0]
            assert missing in roots, (
                f"{name} is missing {missing!r}, which the gate's key {roots} does not name, "
                "so this is a broken module and not an absent extra"
            )
        else:
            pytest.fail(
                f"the gate skipped {name} but it imports fine, so a lean install drops its "
                f"examples: either the key {roots} names something the module does not need, "
                "or _extra_is_absent is wrong"
            )


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
