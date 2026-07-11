"""Canonical combined tire-assessment API tests."""

import copy
import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.services.tire_assessor import tire_assessor

ASSESSMENT_URL = "/api/tire-assessments"


@pytest.mark.asyncio
async def test_assessment_returns_cycle_and_forecast_from_one_request(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 200
    body = response.json()
    UUID(body["assessment_id"])
    UUID(body["representative_cycle"]["result"]["calculation_id"])
    assert body["profile_id"] == "pilot-main-v1"
    assert body["gear"] == "main"
    assert body["representative_cycle"]["basis"] == "MOST_LIKELY_FUTURE_CONDITIONS"
    assert body["representative_cycle"]["operating_conditions"] == {
        "gear": "main",
        "touchdown_speed_ms": 69.0,
        "landing_weight_kg": 64000.0,
        "crosswind_kt": 8.0,
        "taxi_distance_km": 4.2,
        "outside_air_temperature_c": 29.0,
        "under_inflation_pct": 5.0,
    }
    assert body["representative_cycle"]["result"]["severity"]["index"] > 0
    assert body["forecast"]["horizon_cycles"] == 50
    assert body["approved_limits"]["status"] == "NOT_AVAILABLE"
    assert body["unscheduled_removal_risk"]["status"] == "NOT_MODELED"
    assert body["confidence"]["level"] == "LOW"
    assert body["model_versions"] == {
        "severity": "pilot-1.0.0",
        "simulation": "pilot-sim-2.0.0",
    }


@pytest.mark.asyncio
async def test_assessment_is_numerically_reproducible(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    first = (await client.post(ASSESSMENT_URL, json=simulation_payload)).json()
    second = (await client.post(ASSESSMENT_URL, json=simulation_payload)).json()

    first.pop("assessment_id")
    second.pop("assessment_id")
    first["representative_cycle"]["result"].pop("calculation_id")
    second["representative_cycle"]["result"].pop("calculation_id")
    assert first == second


@pytest.mark.asyncio
async def test_assessment_rejects_pressure_outside_model_domain(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    payload = copy.deepcopy(simulation_payload)
    condition = payload["current_condition"]
    assert isinstance(condition, dict)
    condition["measured_cold_pressure_psi"] = 180.0
    condition["reference_cold_pressure_psi"] = 205.0

    response = await client.post(ASSESSMENT_URL, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert response.json()["error"]["details"] == [
        {"field": "body", "message": "Value is invalid."}
    ]


@pytest.mark.asyncio
async def test_assessment_contract_is_documented_without_private_coefficients(
    client: AsyncClient,
) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert ASSESSMENT_URL in document["paths"]
    assert "/api/v1/wear-severity/calculate" not in document["paths"]
    assert "/api/v2/tire-profiles" not in document["paths"]
    assert "/api/v2/tire-simulations" not in document["paths"]
    serialized = json.dumps(document)
    for private_name in (
        "SPIN_WEIGHT",
        "SIMULATION_YAW_FACTOR",
        "SIMULATION_UNCERTAINTY_SIGMA",
    ):
        assert private_name not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/wear-severity/calculate"),
        ("GET", "/api/v2/tire-profiles"),
        ("POST", "/api/v2/tire-simulations"),
    ],
)
async def test_removed_tire_routes_return_not_found(
    client: AsyncClient,
    method: str,
    path: str,
) -> None:
    response = await client.request(method, path, json={})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_assessment_request_id_is_generated(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    UUID(response.headers["X-Request-ID"])


@pytest.mark.asyncio
async def test_assessment_request_id_is_propagated(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(
        ASSESSMENT_URL,
        json=simulation_payload,
        headers={"X-Request-ID": "frontend-request-42"},
    )

    assert response.headers["X-Request-ID"] == "frontend-request-42"


@pytest.mark.asyncio
async def test_assessment_cors_preflight(client: AsyncClient) -> None:
    response = await client.options(
        ASSESSMENT_URL,
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") != "true"


@pytest.mark.asyncio
async def test_assessment_malformed_json_returns_400(client: AsyncClient) -> None:
    response = await client.post(
        ASSESSMENT_URL,
        content=b'{"profile_id": "pilot-main-v1",',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_JSON"


@pytest.mark.asyncio
async def test_assessment_unexpected_errors_are_sanitized(
    client: AsyncClient,
    simulation_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_request: Any) -> Any:
        raise RuntimeError("sensitive implementation detail")

    monkeypatch.setattr(tire_assessor, "assess", explode)
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "sensitive implementation detail" not in response.text
