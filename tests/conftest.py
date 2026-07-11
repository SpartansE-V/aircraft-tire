"""Shared pytest fixtures.

The full synthetic dataset is generated once per session (in memory, no disk I/O) and
reused across tests. Generation is ~1s, so this keeps the suite fast without a small-fleet
override — and it exercises the real, committed generator config.
"""

from __future__ import annotations

import pytest

from treadcast.config import get_generator_config, get_threshold_config
from treadcast.generate_data import generate


@pytest.fixture(scope="session")
def gen_config():
    return get_generator_config()


@pytest.fixture(scope="session")
def threshold_config():
    return get_threshold_config()


@pytest.fixture(scope="session")
def tables(gen_config):
    """All generated tables, keyed by name (fleets, aircraft, tires, ...)."""
    return generate(gen_config)
