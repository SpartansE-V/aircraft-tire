"""Forecast behavior tests through the canonical tire-assessment API."""

import asyncio
import copy
import json
from uuid import UUID

import pytest
from httpx import AsyncClient

ASSESSMENT_URL = "/api/v1/tire-assessments"


def _mode_probability(body: dict[str, object], mode: str) -> float:
    risk = body["unscheduled_removal_risk"]
    assert isinstance(risk, dict)
    modes = risk["modes"]
    assert isinstance(modes, list)
    result = next(item for item in modes if isinstance(item, dict) and item["mode"] == mode)
    probability = result["synthetic_probability_pct"]
    assert isinstance(probability, float)
    return probability


@pytest.mark.asyncio
async def test_successful_simulation_has_safe_response_semantics(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 200
    body = response.json()
    UUID(body["assessment_id"])
    assert body["profile_id"] == "pilot-main-v1"
    assert body["gear"] == "main"
    assert body["random_seed"] == 42
    assert body["approved_limits"]["status"] == "NOT_AVAILABLE"
    assert body["approved_limits"]["demonstration_planning_threshold_mm"] == 1.0
    assert body["approved_limits"]["basis"] == "SYNTHETIC_PILOT_ASSUMPTION"
    risk = body["unscheduled_removal_risk"]
    assert risk["status"] == "SYNTHETIC_DEMONSTRATION"
    assert risk["horizon_cycles"] == 50
    assert risk["confidence"] == "LOW"
    assert risk["probability_interpretation"] == "NOT_EMPIRICAL_FAILURE_PROBABILITY"
    assert 0 <= risk["synthetic_probability_pct"] <= 100
    assert len(risk["modes"]) == 8
    assert all(0 <= mode["synthetic_probability_pct"] <= 100 for mode in risk["modes"])
    assert all(1 <= len(mode["drivers"]) <= 3 for mode in risk["modes"])
    assert body["confidence"]["level"] == "LOW"
    assert "does not provide certified limits" in body["disclaimer"]
    assert 0 <= body["forecast"]["probability_threshold_within_horizon"] <= 1


@pytest.mark.asyncio
async def test_same_seed_produces_same_numeric_result(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    first_response = await client.post(ASSESSMENT_URL, json=simulation_payload)
    second_response = await client.post(ASSESSMENT_URL, json=simulation_payload)
    first = first_response.json()
    second = second_response.json()
    first.pop("assessment_id")
    second.pop("assessment_id")
    first["representative_cycle"]["result"].pop("calculation_id")
    second["representative_cycle"]["result"].pop("calculation_id")

    assert first == second


@pytest.mark.asyncio
async def test_synthetic_removal_probability_increases_with_horizon(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    shorter_payload = copy.deepcopy(simulation_payload)
    shorter_payload["horizon_cycles"] = 25

    shorter = (await client.post(ASSESSMENT_URL, json=shorter_payload)).json()
    baseline = (await client.post(ASSESSMENT_URL, json=simulation_payload)).json()

    assert (
        shorter["unscheduled_removal_risk"]["synthetic_probability_pct"]
        < baseline["unscheduled_removal_risk"]["synthetic_probability_pct"]
    )
    for mode in (
        "FOD_DAMAGE",
        "CUT_OR_EXPOSED_CORD",
        "BULGE",
        "TREAD_SEPARATION",
        "HEAT_DAMAGE",
        "FLAT_SPOT",
        "CONTAMINATION",
        "SUDDEN_PRESSURE_LOSS",
    ):
        assert _mode_probability(shorter, mode) < _mode_probability(baseline, mode)


@pytest.mark.asyncio
async def test_synthetic_removal_probability_tracks_primary_proxy_drivers(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    low_proxy_payload = copy.deepcopy(simulation_payload)
    low_condition = low_proxy_payload["current_condition"]
    assert isinstance(low_condition, dict)
    low_condition.update(
        cycles_since_install=0,
        retread_count=0,
        tire_temperature_c=30.0,
    )
    high_proxy_payload = copy.deepcopy(low_proxy_payload)
    high_condition = high_proxy_payload["current_condition"]
    assert isinstance(high_condition, dict)
    high_condition.update(
        cycles_since_install=500,
        retread_count=3,
        tire_temperature_c=120.0,
    )
    low = (await client.post(ASSESSMENT_URL, json=low_proxy_payload)).json()
    high = (await client.post(ASSESSMENT_URL, json=high_proxy_payload)).json()

    assert low["forecast"] == high["forecast"]
    for mode in (
        "BULGE",
        "TREAD_SEPARATION",
        "HEAT_DAMAGE",
        "SUDDEN_PRESSURE_LOSS",
    ):
        assert _mode_probability(low, mode) < _mode_probability(high, mode)


@pytest.mark.asyncio
async def test_synthetic_removal_probability_tracks_operating_condition_drivers(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    low_payload = copy.deepcopy(simulation_payload)
    low_future = low_payload["future_conditions"]
    assert isinstance(low_future, dict)
    low_future["runway_condition"] = "DRY"
    low_future["heavy_braking_probability"] = 0.0
    low_future["brake_temperature_c"] = {
        "minimum": 200.0,
        "most_likely": 200.0,
        "maximum": 200.0,
    }

    high_payload = copy.deepcopy(low_payload)
    high_future = high_payload["future_conditions"]
    assert isinstance(high_future, dict)
    high_future["runway_condition"] = "ROUGH"
    high_future["heavy_braking_probability"] = 1.0
    high_future["brake_temperature_c"] = {
        "minimum": 600.0,
        "most_likely": 600.0,
        "maximum": 600.0,
    }

    low = (await client.post(ASSESSMENT_URL, json=low_payload)).json()
    high = (await client.post(ASSESSMENT_URL, json=high_payload)).json()

    for mode in ("FOD_DAMAGE", "HEAT_DAMAGE", "FLAT_SPOT", "CONTAMINATION"):
        assert _mode_probability(low, mode) < _mode_probability(high, mode)


@pytest.mark.asyncio
async def test_concurrent_simulations_do_not_share_random_state(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    responses = await asyncio.gather(
        *[client.post(ASSESSMENT_URL, json=simulation_payload) for _ in range(4)]
    )
    bodies = [response.json() for response in responses]
    for body in bodies:
        body.pop("assessment_id")
        body["representative_cycle"]["result"].pop("calculation_id")

    assert all(response.status_code == 200 for response in responses)
    assert all(body == bodies[0] for body in bodies[1:])


@pytest.mark.asyncio
async def test_maintained_pressure_improves_median_planning_life(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

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
    baseline = await client.post(ASSESSMENT_URL, json=simulation_payload)
    faster_payload = copy.deepcopy(simulation_payload)
    future = faster_payload["future_conditions"]
    assert isinstance(future, dict)
    future["touchdown_ground_speed_ms"] = {
        "minimum": 80.0,
        "most_likely": 81.0,
        "maximum": 82.0,
    }
    faster = await client.post(ASSESSMENT_URL, json=faster_payload)

    assert (
        faster.json()["forecast"]["cycles_to_planning_threshold"]["p50"]
        < baseline.json()["forecast"]["cycles_to_planning_threshold"]["p50"]
    )


@pytest.mark.asyncio
async def test_known_defect_requires_qualified_inspection(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    condition = simulation_payload["current_condition"]
    assert isinstance(condition, dict)
    condition["known_defects"] = ["BULGE"]
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "ASSESSMENT_WITHHELD"
    assert body["error"]["details"] == [
        {
            "field": "current_condition.known_defects",
            "message": "Observed defects: BULGE.",
        },
        {
            "field": "required_action",
            "message": (
                "Qualified physical inspection using approved maintenance data is required."
            ),
        },
    ]
    assert "forecast" not in body


@pytest.mark.asyncio
async def test_nose_profile_uses_nose_gear(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    simulation_payload["profile_id"] = "pilot-nose-v1"
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 200
    assert response.json()["gear"] == "nose"


@pytest.mark.asyncio
async def test_planning_threshold_withholds_numeric_forecast(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    condition = simulation_payload["current_condition"]
    assert isinstance(condition, dict)
    condition["current_tread_depth_mm"] = 1.0
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "ASSESSMENT_WITHHELD"
    assert "forecast" not in body


@pytest.mark.asyncio
async def test_invalid_distribution_order_is_rejected(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    future = simulation_payload["future_conditions"]
    assert isinstance(future, dict)
    future["crosswind_kt"] = {"minimum": 10.0, "most_likely": 5.0, "maximum": 20.0}
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

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
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_simulation_field_is_rejected(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    simulation_payload["certified_override"] = True
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert any(detail["field"] == "certified_override" for detail in details)


@pytest.mark.asyncio
async def test_openapi_exposes_only_the_canonical_tire_model_api(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    serialized = json.dumps(response.json())

    paths = response.json()["paths"]
    assert ASSESSMENT_URL in paths
    assert "/api/v1/wear-severity/calculate" not in paths
    assert "/api/v2/tire-profiles" not in paths
    assert "/api/v2/tire-simulations" not in paths
    for internal_name in (
        "SIMULATION_SINK_RATE_FACTOR",
        "SIMULATION_YAW_FACTOR",
        "SIMULATION_UNCERTAINTY_SIGMA",
    ):
        assert internal_name not in serialized
