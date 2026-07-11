"""RUL prediction HTTP API tests."""

import json
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.services.tire_rul_service import tire_rul_service


@pytest.fixture
def rul_payload() -> dict[str, Any]:
    return {
        "position": "mlg_r_inbd",
        "current_cycles": 190,
        "landings_per_day": 4.0,
        "as_of_date": "2026-07-11",
        "readings": [
            {"cycles_since_install": 0, "measured_groove_mm": 12.0},
            {"cycles_since_install": 90, "measured_groove_mm": 9.0},
            {"cycles_since_install": 190, "measured_groove_mm": 6.1},
        ],
    }


@pytest.mark.asyncio
async def test_successful_prediction(client: AsyncClient, rul_payload: dict[str, Any]) -> None:
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 200
    body = response.json()
    UUID(body["prediction_id"])
    assert body["position"] == "mlg_r_inbd"
    assert body["readings_used"] == 3
    assert body["low_confidence"] is False
    assert body["wear_limit_mm"] == 2.0
    assert body["landings_per_day"] == 4.0
    assert body["model_version"].startswith("rul-mixedlm-")
    assert "does not replace physical inspection" in body["disclaimer"]

    quantiles = body["rul_landings"]
    assert 0 < quantiles["p10"] <= quantiles["median"] <= quantiles["p90"]

    dates = body["wear_to_limit_dates"]
    earliest = date.fromisoformat(dates["earliest_credible_p10"])
    median = date.fromisoformat(dates["median"])
    latest = date.fromisoformat(dates["p90"])
    assert date(2026, 7, 11) < earliest <= median <= latest

    assert 0.0 <= body["p_cross_before_next_check"] <= 1.0
    assert body["status"]["status"] in {"healthy", "monitor", "schedule", "replace_now"}
    assert body["status"]["severity"] in {"info", "warning", "critical"}
    assert body["status"]["headline"]
    assert body["status"]["recommended_action"]


@pytest.mark.asyncio
async def test_prediction_is_deterministic_for_fixed_date(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    first = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    second = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    for volatile_field in ("prediction_id",):
        first.pop(volatile_field)
        second.pop(volatile_field)
    assert first == second


@pytest.mark.asyncio
async def test_no_readings_falls_back_to_fleet_prior(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["readings"] = []
    rul_payload["current_cycles"] = 0
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["readings_used"] == 0
    assert body["low_confidence"] is True
    assert body["rul_landings"]["median"] > 0


@pytest.mark.asyncio
async def test_readings_field_is_optional(client: AsyncClient, rul_payload: dict[str, Any]) -> None:
    del rul_payload["readings"]
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 200
    assert response.json()["readings_used"] == 0


@pytest.mark.asyncio
async def test_planned_landings_updates_forecast_horizon(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    baseline = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    rul_payload["planned_landings"] = 20
    planned = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    assert planned["rul_landings"]["median"] < baseline["rul_landings"]["median"]
    assert planned["rul_landings"]["median"] == pytest.approx(
        baseline["rul_landings"]["median"] - 20, abs=0.2
    )


@pytest.mark.asyncio
async def test_severe_flight_conditions_reduce_rul_and_report_exposure(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    normal = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    rul_payload["flight_conditions"] = {
        "landing_load_factor": 1.3,
        "braking_energy_factor": 1.5,
        "takeoff_severity_factor": 1.2,
        "taxi_heat_factor": 1.2,
        "temperature_factor": 1.1,
        "inflation_factor": 1.3,
        "runway_roughness_factor": 1.2,
        "hard_landing_factor": 1.5,
        "crosswind_factor": 1.2,
    }
    severe = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    assert normal["wear_exposure_multiplier"] == 1.0
    assert severe["wear_exposure_multiplier"] > 1.0
    assert severe["effective_planned_landings"] > normal["effective_planned_landings"]
    assert severe["rul_landings"]["median"] < normal["rul_landings"]["median"]


_NEUTRAL_SENSORS = {
    "indicated_airspeed_kt": 140.0,
    "vertical_speed_fpm": 180.0,
    "normal_acceleration_g": 1.0,
    "outside_air_temperature_c": 15.0,
    "altitude_msl_ft": 0.0,
}
_SEVERE_SENSORS = {
    "indicated_airspeed_kt": 170.0,
    "vertical_speed_fpm": 600.0,
    "normal_acceleration_g": 1.9,
    "outside_air_temperature_c": 43.0,
    "altitude_msl_ft": 5400.0,
}


@pytest.mark.asyncio
async def test_omitted_sensors_report_unit_multiplier(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    body = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    assert body["sensor_wear_multiplier"] == 1.0


@pytest.mark.asyncio
async def test_neutral_ngafid_sensors_report_unit_multiplier(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = _NEUTRAL_SENSORS
    body = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    assert body["sensor_wear_multiplier"] == 1.0
    assert body["wear_exposure_multiplier"] == 1.0
    assert body["effective_planned_landings"] == pytest.approx(10.0, abs=0.2)


@pytest.mark.asyncio
async def test_severe_ngafid_sensors_reduce_rul_and_report_exposure(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    normal = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    rul_payload["flight_sensors"] = _SEVERE_SENSORS
    severe = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    assert normal["sensor_wear_multiplier"] == 1.0
    assert severe["sensor_wear_multiplier"] > 1.0
    assert severe["wear_exposure_multiplier"] > 1.0
    assert severe["effective_planned_landings"] > normal["effective_planned_landings"]
    assert severe["rul_landings"]["median"] < normal["rul_landings"]["median"]


@pytest.mark.asyncio
async def test_gentle_ngafid_sensors_report_below_unit_and_extend_life(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = _NEUTRAL_SENSORS
    neutral = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    rul_payload["flight_sensors"] = {
        "indicated_airspeed_kt": 115.0,
        "vertical_speed_fpm": 90.0,
        "normal_acceleration_g": 1.05,
        "outside_air_temperature_c": -5.0,
        "altitude_msl_ft": 0.0,
    }
    gentle = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    assert gentle["sensor_wear_multiplier"] < 1.0
    # A gentle multiplier must actually be applied downstream, not just reported.
    assert gentle["effective_planned_landings"] < neutral["effective_planned_landings"]
    assert gentle["rul_landings"]["median"] > neutral["rul_landings"]["median"]


@pytest.mark.asyncio
async def test_empty_sensor_block_uses_reference_defaults(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    # An empty block exercises the all-defaults compute path (distinct from the None early-return).
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = {}
    body = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    assert body["sensor_wear_multiplier"] == 1.0


@pytest.mark.asyncio
async def test_partial_sensor_block_falls_back_to_reference(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    # Only NormAc supplied; the other four fall back to their reference values, so the multiplier
    # is the load term alone (NormAc / 1.0).
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = {"normal_acceleration_g": 1.5}
    body = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    assert body["sensor_wear_multiplier"] == pytest.approx(1.5, abs=0.01)


@pytest.mark.asyncio
async def test_ngafid_sensors_and_flight_conditions_combine_as_product(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10

    rul_payload.pop("flight_sensors", None)
    rul_payload["flight_conditions"] = {"landing_load_factor": 1.2}
    factors_only = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    rul_payload["flight_conditions"] = {}
    rul_payload["flight_sensors"] = {**_NEUTRAL_SENSORS, "indicated_airspeed_kt": 155.0}
    sensors_only = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    rul_payload["flight_conditions"] = {"landing_load_factor": 1.2}
    both = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    # The combined exposure is the PRODUCT of the two multipliers — not max() or either-or.
    assert both["sensor_wear_multiplier"] == pytest.approx(sensors_only["sensor_wear_multiplier"])
    assert both["wear_exposure_multiplier"] == pytest.approx(
        factors_only["wear_exposure_multiplier"] * sensors_only["sensor_wear_multiplier"], abs=0.01
    )
    assert both["wear_exposure_multiplier"] > factors_only["wear_exposure_multiplier"]
    assert both["wear_exposure_multiplier"] > sensors_only["sensor_wear_multiplier"]


@pytest.mark.asyncio
async def test_sensor_multiplier_is_clipped_at_bounds(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = {
        "indicated_airspeed_kt": 250.0,
        "vertical_speed_fpm": 1500.0,
        "normal_acceleration_g": 4.0,
        "outside_air_temperature_c": 55.0,
        "altitude_msl_ft": 15000.0,
    }
    hot = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    assert hot["sensor_wear_multiplier"] == 6.0  # raw product ~45 -> clipped to the upper bound

    rul_payload["flight_sensors"] = {
        "indicated_airspeed_kt": 40.0,
        "vertical_speed_fpm": 0.0,
        "normal_acceleration_g": 0.5,
        "outside_air_temperature_c": -40.0,
        "altitude_msl_ft": -1500.0,
    }
    minimal = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    assert minimal["sensor_wear_multiplier"] == 0.25  # clipped to the lower bound


@pytest.mark.asyncio
async def test_zero_sink_does_not_collapse_a_severe_landing(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    # Regression: a fast, hard landing recorded with VSpd == 0 must still read as high wear — the
    # floored sink term must not drag the product to the lower clip.
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = {
        "indicated_airspeed_kt": 250.0,
        "vertical_speed_fpm": 0.0,
        "normal_acceleration_g": 4.0,
        "outside_air_temperature_c": 15.0,
        "altitude_msl_ft": 0.0,
    }
    body = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    assert body["sensor_wear_multiplier"] > 3.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("indicated_airspeed_kt", 40.0),
        ("indicated_airspeed_kt", 250.0),
        ("vertical_speed_fpm", 0.0),
        ("vertical_speed_fpm", 1500.0),
        ("normal_acceleration_g", 0.5),
        ("normal_acceleration_g", 4.0),
        ("outside_air_temperature_c", -40.0),
        ("outside_air_temperature_c", 55.0),
        ("altitude_msl_ft", -1500.0),
        ("altitude_msl_ft", 15000.0),
    ],
)
async def test_inclusive_sensor_boundaries_accepted(
    client: AsyncClient, rul_payload: dict[str, Any], field: str, value: float
) -> None:
    rul_payload["flight_sensors"] = {**_NEUTRAL_SENSORS, field: value}
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_prediction_with_sensors_is_deterministic(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = _SEVERE_SENSORS
    first = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    second = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    for volatile_field in ("prediction_id",):
        first.pop(volatile_field)
        second.pop(volatile_field)
    assert first == second


@pytest.mark.asyncio
async def test_ngafid_sensors_downweight_nose_versus_main(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = _SEVERE_SENSORS

    rul_payload["position"] = "mlg_r_inbd"
    main = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    rul_payload["position"] = "nlg_l"
    nose = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    # Nose tires steer rather than absorb the landing impact, so identical sensors wear them less.
    assert nose["sensor_wear_multiplier"] < main["sensor_wear_multiplier"]
    assert nose["sensor_wear_multiplier"] > 1.0


@pytest.mark.asyncio
async def test_field_altitude_raises_sensor_exposure(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    rul_payload["planned_landings"] = 10
    rul_payload["flight_sensors"] = {**_NEUTRAL_SENSORS, "altitude_msl_ft": 0.0}
    sea_level = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()
    rul_payload["flight_sensors"] = {**_NEUTRAL_SENSORS, "altitude_msl_ft": 5400.0}
    denver = (await client.post("/api/v1/tire_rul/predict", json=rul_payload)).json()

    # Thin air makes the same indicated airspeed a faster true touchdown -> more spin-up scrub.
    assert sea_level["sensor_wear_multiplier"] == 1.0  # neutral + sea level is the anchor
    assert denver["sensor_wear_multiplier"] > sea_level["sensor_wear_multiplier"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("indicated_airspeed_kt", 30.0),
        ("indicated_airspeed_kt", 260.0),
        ("vertical_speed_fpm", -1.0),
        ("normal_acceleration_g", 0.4),
        ("normal_acceleration_g", 10.0),
        ("outside_air_temperature_c", 90.0),
        ("altitude_msl_ft", 20_000.0),
    ],
)
async def test_out_of_range_ngafid_sensor_rejected(
    client: AsyncClient, rul_payload: dict[str, Any], field: str, value: float
) -> None:
    rul_payload["flight_sensors"] = {**_NEUTRAL_SENSORS, field: value}
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_ngafid_sensor_field_rejected(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    # Only tire-relevant channels are accepted; an engine channel (e.g. E1 RPM) must be refused.
    rul_payload["flight_sensors"] = {**_NEUTRAL_SENSORS, "engine_rpm": 2400}
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_worn_tire_reports_replace_now(
    client: AsyncClient, rul_payload: dict[str, Any]
) -> None:
    # Readings already at/below the 2.0 mm wear limit -> RUL collapses toward zero.
    rul_payload["readings"] = [
        {"cycles_since_install": 0, "measured_groove_mm": 12.0},
        {"cycles_since_install": 150, "measured_groove_mm": 5.0},
        {"cycles_since_install": 280, "measured_groove_mm": 2.1},
    ]
    rul_payload["current_cycles"] = 285
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["status"] in {"schedule", "replace_now"}
    assert body["rul_landings"]["median"] < 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "position",
    ["nlg_l", "nlg_r", "mlg_l_inbd", "mlg_l_outbd", "mlg_r_inbd", "mlg_r_outbd"],
)
async def test_all_wheel_positions_accepted(
    client: AsyncClient, rul_payload: dict[str, Any], position: str
) -> None:
    rul_payload["position"] = position
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 200
    assert response.json()["position"] == position


@pytest.mark.asyncio
async def test_invalid_position_rejected(client: AsyncClient, rul_payload: dict[str, Any]) -> None:
    rul_payload["position"] = "left_wheel"
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_INPUT"
    assert any(detail["field"] == "position" for detail in body["error"]["details"])


@pytest.mark.asyncio
async def test_unknown_field_rejected(client: AsyncClient, rul_payload: dict[str, Any]) -> None:
    rul_payload["tire_serial"] = "T-1234"
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"


@pytest.mark.asyncio
async def test_missing_required_fields_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/tire_rul/predict", json={"position": "nlg_l"})

    assert response.status_code == 422
    fields = {detail["field"] for detail in response.json()["error"]["details"]}
    assert {"current_cycles", "landings_per_day"} <= fields


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_cycles", -1),
        ("current_cycles", 20_001),
        ("planned_landings", -1),
        ("planned_landings", 20_001),
        ("landings_per_day", 0),
        ("landings_per_day", 21),
    ],
)
async def test_out_of_range_inputs_rejected(
    client: AsyncClient, rul_payload: dict[str, Any], field: str, value: float
) -> None:
    rul_payload[field] = value
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_reading_rejected(client: AsyncClient, rul_payload: dict[str, Any]) -> None:
    rul_payload["readings"] = [{"cycles_since_install": 10, "measured_groove_mm": 0}]
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_malformed_json_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/tire_rul/predict",
        content=b'{"position": "nlg_l",',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_JSON"


@pytest.mark.asyncio
async def test_endpoint_in_openapi(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/tire_rul/predict" in response.json()["paths"]


@pytest.mark.asyncio
async def test_openapi_does_not_expose_model_internals(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    serialized_schema = json.dumps(response.json()).lower()

    for internal_term in ("mixedlm_covariance", "eb_posterior", "monte_carlo_crossing", "mc_seed"):
        assert internal_term not in serialized_schema


@pytest.mark.asyncio
async def test_unexpected_errors_are_sanitized(
    client: AsyncClient,
    rul_payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_request: Any) -> Any:
        raise RuntimeError("prior artifact path leaked")

    monkeypatch.setattr(tire_rul_service, "predict", explode)
    response = await client.post("/api/v1/tire_rul/predict", json=rul_payload)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred while processing the request.",
        }
    }
    assert "prior artifact path" not in response.text
