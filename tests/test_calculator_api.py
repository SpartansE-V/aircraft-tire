"""Wear-severity HTTP API tests."""

import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.services.wear_calculator import calculator


@pytest.mark.asyncio
async def test_successful_calculation(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    response = await client.post("/api/v1/wear-severity/calculate", json=nominal_payload)

    assert response.status_code == 200
    body = response.json()
    UUID(body["calculation_id"])
    assert body["gear"] == "main"
    assert body["gear_label"] == "Main gear"
    assert body["severity"] == {
        "index": 110,
        "level": "MODERATE",
        "label": "Moderate wear conditions",
    }
    assert body["estimated_wear_rate_mm_per_cycle"] == 0.044
    assert body["estimated_total_tread_life_cycles"] == 225
    assert body["pressure_effect"] == {"multiplier": 1.0, "warning": False}
    assert body["model_version"] == "pilot-1.0.0"
    assert "does not replace physical inspection" in body["disclaimer"]


@pytest.mark.asyncio
async def test_nose_gear_label(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    nominal_payload["gear"] = "nose"
    response = await client.post("/api/v1/wear-severity/calculate", json=nominal_payload)

    assert response.status_code == 200
    assert response.json()["gear_label"] == "Nose gear"


@pytest.mark.asyncio
async def test_pressure_warning(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    nominal_payload["under_inflation_pct"] = 5
    response = await client.post("/api/v1/wear-severity/calculate", json=nominal_payload)

    pressure_effect = response.json()["pressure_effect"]
    assert pressure_effect["warning"] is True
    assert "Verify cold tire pressure" in pressure_effect["message"]


@pytest.mark.asyncio
async def test_request_id_is_generated(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    response = await client.post("/api/v1/wear-severity/calculate", json=nominal_payload)

    UUID(response.headers["X-Request-ID"])


@pytest.mark.asyncio
async def test_request_id_is_propagated(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    response = await client.post(
        "/api/v1/wear-severity/calculate",
        json=nominal_payload,
        headers={"X-Request-ID": "frontend-request-42"},
    )

    assert response.headers["X-Request-ID"] == "frontend-request-42"


@pytest.mark.asyncio
async def test_swagger_and_openapi_are_available(client: AsyncClient) -> None:
    docs_response = await client.get("/docs")
    openapi_response = await client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert openapi_response.status_code == 200
    assert "/api/v1/wear-severity/calculate" in openapi_response.json()["paths"]


@pytest.mark.asyncio
async def test_openapi_does_not_expose_internal_calculation(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    serialized_schema = json.dumps(response.json()).lower()

    for internal_term in ("spin_energy", "brake_energy", "crosswind_factor", "0.012"):
        assert internal_term not in serialized_schema


@pytest.mark.asyncio
async def test_cors_preflight(
    client: AsyncClient,
) -> None:
    response = await client.options(
        "/api/v1/wear-severity/calculate",
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
async def test_unexpected_errors_are_sanitized(
    client: AsyncClient,
    nominal_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_request: Any) -> Any:
        raise RuntimeError("sensitive implementation detail")

    monkeypatch.setattr(calculator, "calculate", explode)
    response = await client.post("/api/v1/wear-severity/calculate", json=nominal_payload)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred while processing the request.",
        }
    }
    assert "sensitive implementation detail" not in response.text
