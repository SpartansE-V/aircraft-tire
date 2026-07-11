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
        "test_agent_api.py",
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


@pytest.fixture
def simulation_payload() -> dict[str, object]:
    return {
        "profile_id": "pilot-main-v1",
        "current_condition": {
            "cycles_since_install": 94,
            "current_tread_depth_mm": 6.8,
            "measured_cold_pressure_psi": 190.0,
            "reference_cold_pressure_psi": 200.0,
            "tire_temperature_c": 30.0,
            "retread_count": 1,
            "known_defects": [],
        },
        "horizon_cycles": 50,
        "simulation_runs": 100,
        "random_seed": 42,
        "future_conditions": {
            "landing_weight_kg": {
                "minimum": 58000.0,
                "most_likely": 64000.0,
                "maximum": 70000.0,
            },
            "touchdown_ground_speed_ms": {
                "minimum": 63.0,
                "most_likely": 69.0,
                "maximum": 76.0,
            },
            "crosswind_kt": {"minimum": 0.0, "most_likely": 8.0, "maximum": 18.0},
            "touchdown_sink_rate_ms": {
                "minimum": 0.5,
                "most_likely": 1.2,
                "maximum": 2.0,
            },
            "touchdown_yaw_angle_deg": {
                "minimum": 0.0,
                "most_likely": 2.0,
                "maximum": 6.0,
            },
            "taxi_distance_km": {
                "minimum": 2.0,
                "most_likely": 4.2,
                "maximum": 6.0,
            },
            "average_taxi_speed_kt": {
                "minimum": 8.0,
                "most_likely": 14.0,
                "maximum": 22.0,
            },
            "outside_air_temperature_c": {
                "minimum": 18.0,
                "most_likely": 29.0,
                "maximum": 39.0,
            },
            "brake_temperature_c": {
                "minimum": 100.0,
                "most_likely": 220.0,
                "maximum": 380.0,
            },
            "heavy_braking_probability": 0.05,
            "runway_condition": "DRY",
        },
    }


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
