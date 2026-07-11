"""Strict request validation and public error-shape tests."""

import json
import math

import pytest
from httpx import AsyncClient

CALCULATE_URL = "/api/v1/wear-severity/calculate"

FIELD_BOUNDS: dict[str, tuple[float, float]] = {
    "touchdown_speed_ms": (58, 82),
    "landing_weight_kg": (50_000, 73_500),
    "crosswind_kt": (0, 25),
    "taxi_distance_km": (0.5, 8),
    "outside_air_temperature_c": (5, 45),
    "under_inflation_pct": (0, 10),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "bounds"), FIELD_BOUNDS.items())
@pytest.mark.parametrize("bound_index", [0, 1])
async def test_numeric_minimum_and_maximum_are_valid(
    client: AsyncClient,
    nominal_payload: dict[str, object],
    field: str,
    bounds: tuple[float, float],
    bound_index: int,
) -> None:
    nominal_payload[field] = bounds[bound_index]

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "bounds"), FIELD_BOUNDS.items())
@pytest.mark.parametrize("direction", [-1, 1])
async def test_out_of_range_numeric_value_is_rejected(
    client: AsyncClient,
    nominal_payload: dict[str, object],
    field: str,
    bounds: tuple[float, float],
    direction: int,
) -> None:
    nominal_payload[field] = bounds[0] - 1 if direction < 0 else bounds[1] + 1

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


@pytest.mark.asyncio
@pytest.mark.parametrize("field", FIELD_BOUNDS)
async def test_missing_numeric_field_is_rejected(
    client: AsyncClient,
    nominal_payload: dict[str, object],
    field: str,
) -> None:
    del nominal_payload[field]

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0] == {
        "field": field,
        "message": "Field is required.",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("field", FIELD_BOUNDS)
@pytest.mark.parametrize("invalid_value", [None, "69", True, math.nan, math.inf])
async def test_invalid_numeric_types_and_non_finite_values_are_rejected(
    client: AsyncClient,
    nominal_payload: dict[str, object],
    field: str,
    invalid_value: object,
) -> None:
    nominal_payload[field] = invalid_value

    if isinstance(invalid_value, float) and not math.isfinite(invalid_value):
        response = await client.post(
            CALCULATE_URL,
            content=json.dumps(nominal_payload, allow_nan=True),
            headers={"Content-Type": "application/json"},
        )
    else:
        response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_gear", [None, "wing", 1, True])
async def test_unsupported_gear_is_rejected(
    client: AsyncClient,
    nominal_payload: dict[str, object],
    invalid_gear: object,
) -> None:
    nominal_payload["gear"] = invalid_gear

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "gear"


@pytest.mark.asyncio
async def test_missing_gear_is_rejected(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    del nominal_payload["gear"]

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_field_is_rejected(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    nominal_payload["internal_override"] = 123

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0] == {
        "field": "internal_override",
        "message": "Unknown field.",
    }


@pytest.mark.asyncio
async def test_malformed_json_returns_400(client: AsyncClient) -> None:
    response = await client.post(
        CALCULATE_URL,
        content=b'{"gear": "main",',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "MALFORMED_JSON",
            "message": "The request body contains malformed JSON.",
            "details": [{"field": "body", "message": "Malformed JSON request body."}],
        }
    }


@pytest.mark.asyncio
async def test_validation_error_shape(
    client: AsyncClient,
    nominal_payload: dict[str, object],
) -> None:
    nominal_payload["touchdown_speed_ms"] = 57

    response = await client.post(CALCULATE_URL, json=nominal_payload)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INVALID_INPUT",
            "message": "One or more calculator inputs are invalid.",
            "details": [
                {
                    "field": "touchdown_speed_ms",
                    "message": "Value must be between 58 and 82.",
                }
            ],
        }
    }
