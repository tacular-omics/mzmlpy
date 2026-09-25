"""Shared pytest setup: Hypothesis profiles and the opt-in ``slow`` marker.

The default run is kept fast. ``--run-slow`` (or ``RUN_SLOW=1``) also runs tests marked
``slow`` (subprocess launches, memory-flatness checks); ``HYPOTHESIS_PROFILE=thorough``
runs many more property-test examples. CI sets both.
"""

import os

import pytest

try:
    from hypothesis import settings
except ImportError:  # the wheel smoke job installs only pytest and runs non-property tests
    pass
else:
    settings.register_profile("default", max_examples=40, deadline=None)
    settings.register_profile("thorough", max_examples=1000, deadline=None)
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-slow", action="store_true", default=False, help="also run tests marked slow")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-slow") or os.environ.get("RUN_SLOW", "") not in ("", "0"):
        return
    skip = pytest.mark.skip(reason="slow test: pass --run-slow or set RUN_SLOW=1")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)
