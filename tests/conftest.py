"""Shared test fixtures for the API suite and the AI research-pipeline suite.

The AI research-pipeline tests (features/generator/evaluation/agent/cv) need the full ML stack
(`uv sync --extra ai`). With only the base API dependencies installed they are skipped at
collection so `make test` stays green for the backend. The scoring/grounding tests run either
way — app.rul.scoring is pure numpy.

The full synthetic dataset is generated once per session (in memory, no disk I/O) and reused
across tests: generation is ~1s, and it exercises the real, committed generator config.
"""

import importlib.util
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.rul.config import get_generator_config, get_threshold_config

collect_ignore: list[str] = []
if importlib.util.find_spec("pandas") is None:
    collect_ignore += [
        "test_agent.py",
        "test_evaluation.py",
        "test_features.py",
        "test_generator.py",
    ]
if importlib.util.find_spec("PIL") is None:
    collect_ignore += ["test_cv.py"]


# --- AI pipeline fixtures ---
@pytest.fixture(scope="session")
def gen_config() -> Any:
    return get_generator_config()


@pytest.fixture(scope="session")
def threshold_config() -> Any:
    return get_threshold_config()


@pytest.fixture(scope="session")
def tables(gen_config: Any) -> Any:
    """All generated tables, keyed by name (fleets, aircraft, tires, ...)."""
    # Imported lazily: generate_data needs pandas (the `ai` extra), and every test that uses
    # this fixture lives in a module that is collect-ignored when pandas is absent.
    from app.rul.generate_data import generate

    return generate(gen_config)


@pytest.fixture
def nominal_payload() -> dict[str, object]:
    return {
        "gear": "main",
        "touchdown_speed_ms": 69,
        "landing_weight_kg": 62000,
        "crosswind_kt": 6,
        "taxi_distance_km": 2.8,
        "outside_air_temperature_c": 30,
        "under_inflation_pct": 0,
    }


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
