"""V2 demonstration tire-simulation API tests."""

import asyncio
import copy
import json
from uuid import UUID

import pytest
from httpx import AsyncClient

SIMULATION_URL = "/api/v2/tire-simulations"


@pytest.mark.asyncio
async def test_profile_catalog_is_explicitly_demonstration_only(client: AsyncClient) -> None:
    response = await client.get("/api/v2/tire-profiles")

    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert {profile["profile_id"] for profile in profiles} == {
        "pilot-main-v1",
        "pilot-nose-v1",
    }
    assert all(profile["model_status"] == "DEMONSTRATION_ONLY" for profile in profiles)
    assert all(profile["certified_limits_available"] is False for profile in profiles)


@pytest.mark.asyncio
async def test_successful_simulation_has_safe_response_semantics(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    assert response.status_code == 200
    body = response.json()
    UUID(body["simulation_id"])
    assert body["profile_id"] == "pilot-main-v1"
    assert body["gear"] == "main"
    assert body["random_seed"] == 42
    assert body["approved_limits"]["status"] == "NOT_AVAILABLE"
    assert body["unscheduled_removal_risk"]["status"] == "NOT_MODELED"
    assert body["confidence"]["level"] == "LOW"
    assert "does not provide certified limits" in body["disclaimer"]
    assert 0 <= body["wear_forecast"]["probability_threshold_within_horizon"] <= 1


@pytest.mark.asyncio
async def test_same_seed_produces_same_numeric_result(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    first_response = await client.post(SIMULATION_URL, json=simulation_payload)
    second_response = await client.post(SIMULATION_URL, json=simulation_payload)
    first = first_response.json()
    second = second_response.json()
    first.pop("simulation_id")
    second.pop("simulation_id")

    assert first == second


@pytest.mark.asyncio
async def test_concurrent_simulations_do_not_share_random_state(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    responses = await asyncio.gather(
        *[client.post(SIMULATION_URL, json=simulation_payload) for _ in range(4)]
    )
    bodies = [response.json() for response in responses]
    for body in bodies:
        body.pop("simulation_id")

    assert all(response.status_code == 200 for response in responses)
    assert all(body == bodies[0] for body in bodies[1:])


@pytest.mark.asyncio
async def test_maintained_pressure_improves_median_planning_life(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    comparison = response.json()["pressure_policy_comparison"]
    assert (
        comparison["maintained_reference_pressure_median_cycles"]
        > comparison["current_pressure_policy_median_cycles"]
    )
    assert comparison["estimated_median_cycle_difference"] > 0


@pytest.mark.asyncio
async def test_higher_touchdown_speed_reduces_forecast_life(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    baseline = await client.post(SIMULATION_URL, json=simulation_payload)
    faster_payload = copy.deepcopy(simulation_payload)
    future = faster_payload["future_conditions"]
    assert isinstance(future, dict)
    future["touchdown_ground_speed_ms"] = {
        "minimum": 80.0,
        "most_likely": 81.0,
        "maximum": 82.0,
    }
    faster = await client.post(SIMULATION_URL, json=faster_payload)

    assert (
        faster.json()["wear_forecast"]["cycles_to_planning_threshold"]["p50"]
        < baseline.json()["wear_forecast"]["cycles_to_planning_threshold"]["p50"]
    )


@pytest.mark.asyncio
async def test_known_defect_requires_qualified_inspection(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    condition = simulation_payload["current_condition"]
    assert isinstance(condition, dict)
    condition["known_defects"] = ["BULGE"]
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    body = response.json()
    assert body["current_condition"]["status"] == "QUALIFIED_INSPECTION_REQUIRED"
    assert body["recommendation"]["attention"] == "QUALIFIED_INSPECTION_REQUIRED"


@pytest.mark.asyncio
async def test_nose_profile_uses_nose_gear(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    simulation_payload["profile_id"] = "pilot-nose-v1"
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    assert response.status_code == 200
    assert response.json()["gear"] == "nose"


@pytest.mark.asyncio
async def test_planning_threshold_has_zero_remaining_cycles(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    condition = simulation_payload["current_condition"]
    assert isinstance(condition, dict)
    condition["current_tread_depth_mm"] = 1.0
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    body = response.json()
    assert body["current_condition"]["status"] == "PLANNING_THRESHOLD_REACHED"
    assert body["wear_forecast"]["cycles_to_planning_threshold"] == {
        "p10": 0,
        "p50": 0,
        "p90": 0,
    }
    assert body["wear_forecast"]["probability_threshold_within_horizon"] == 1.0


@pytest.mark.asyncio
async def test_invalid_distribution_order_is_rejected(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    future = simulation_payload["future_conditions"]
    assert isinstance(future, dict)
    future["crosswind_kt"] = {"minimum": 10.0, "most_likely": 5.0, "maximum": 20.0}
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_out_of_domain_distribution_is_rejected(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    future = simulation_payload["future_conditions"]
    assert isinstance(future, dict)
    future["crosswind_kt"] = {"minimum": 0.0, "most_likely": 10.0, "maximum": 30.0}
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_simulation_field_is_rejected(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    simulation_payload["certified_override"] = True
    response = await client.post(SIMULATION_URL, json=simulation_payload)

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert any(detail["field"] == "certified_override" for detail in details)


@pytest.mark.asyncio
async def test_openapi_does_not_expose_simulation_coefficients(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    serialized = json.dumps(response.json())

    assert "/api/v2/tire-simulations" in response.json()["paths"]
    for internal_name in (
        "SIMULATION_SINK_RATE_FACTOR",
        "SIMULATION_YAW_FACTOR",
        "SIMULATION_UNCERTAINTY_SIGMA",
    ):
        assert internal_name not in serialized
