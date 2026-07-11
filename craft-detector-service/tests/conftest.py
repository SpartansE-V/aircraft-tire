"""Shared API test fixtures."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


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
