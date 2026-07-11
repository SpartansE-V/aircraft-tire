"""Canonical combined tire-assessment API tests."""

import copy
import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.domain.assessment_schemas import TireAssessmentRequest
from app.services.model_registry import ModelEvidenceIntegrityError
from app.services.tire_assessor import tire_assessor

ASSESSMENT_URL = "/api/v1/tire-assessments"
EXPECTED_SUPPORTING_EVIDENCE_SHA256 = (
    "1c499db6c7fa0463f3a58856d6a8decb02378a9d23fdc8596482233178b0a943"
)


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
    assert body["approved_limits"] == {
        "status": "NOT_AVAILABLE",
        "demonstration_planning_threshold_mm": 1.0,
        "basis": "SYNTHETIC_PILOT_ASSUMPTION",
        "message": (
            "This is a demonstration planning threshold, not an approved removal or "
            "serviceability limit."
        ),
    }
    assert body["unscheduled_removal_risk"]["status"] == "SYNTHETIC_DEMONSTRATION"
    assert (
        body["unscheduled_removal_risk"]["probability_interpretation"]
        == "NOT_EMPIRICAL_FAILURE_PROBABILITY"
    )
    assert body["confidence"]["level"] == "LOW"
    assert body["model_versions"] == {
        "severity": "pilot-1.0.0",
        "simulation": "pilot-sim-2.0.0",
    }
    assert body["governance"]["lifecycle"] == "DEVELOPMENT"
    assert body["governance"]["requested_use"] == "SCENARIO_PLANNING"
    assert body["governance"]["requested_use_permitted"] is True
    assert body["governance"]["operational_decision_authorized"] is False
    assert body["governance"]["calibration_status"] == "NOT_PERFORMED"
    assert body["governance"]["validation_status"] == "NOT_PERFORMED"
    assert body["governance"]["authorization_status"] == "NOT_AUTHORIZED"
    assert "release_target_identity" not in body["governance"]
    assert "request_asset_identity" not in body["governance"]
    assert body["governance"]["implementation_id"] == "pilot-physics-simulation-2.0.0"
    assert len(body["governance"]["implementation_sha256"]) == 64
    assert body["governance"]["supporting_evidence"] == [
        {
            "evidence_id": "nasa-tp-3626-ittv-table4",
            "source_kind": "PHYSICAL_TEST",
            "sha256": EXPECTED_SUPPORTING_EVIDENCE_SHA256,
        }
    ]
    assert body["model_factor_usage"] == [
        {
            "field": field,
            "wear_forecast": "RECORDED_NOT_USED",
            "removal_demo": "USED_AS_SYNTHETIC_PROXY",
        }
        for field in ("cycles_since_install", "retread_count", "tire_temperature_c")
    ]


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
    assert response.json()["error"]["code"] == "MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN"


@pytest.mark.asyncio
async def test_exact_ten_percent_pressure_deficit_withholds_forecast(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    condition = simulation_payload["current_condition"]
    assert isinstance(condition, dict)
    condition["reference_cold_pressure_psi"] = 205.0
    condition["measured_cold_pressure_psi"] = 184.5

    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ASSESSMENT_WITHHELD"


@pytest.mark.asyncio
async def test_pressure_above_reference_is_not_silently_modeled(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    condition = simulation_payload["current_condition"]
    assert isinstance(condition, dict)
    condition["reference_cold_pressure_psi"] = 205.0
    condition["measured_cold_pressure_psi"] = 206.0

    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN"


@pytest.mark.asyncio
@pytest.mark.parametrize("intended_use", ["MAINTENANCE_PLANNING", "DISPATCH_SUPPORT"])
async def test_operational_use_is_fail_closed_without_evidence(
    client: AsyncClient,
    simulation_payload: dict[str, object],
    intended_use: str,
) -> None:
    simulation_payload["intended_use"] = intended_use

    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "MODEL_NOT_AUTHORIZED_FOR_INTENDED_USE"
    assert "forecast" not in body


@pytest.mark.asyncio
async def test_intended_use_is_required(
    client: AsyncClient,
    simulation_payload: dict[str, object],
) -> None:
    del simulation_payload["intended_use"]

    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 422
    assert any(detail["field"] == "intended_use" for detail in response.json()["error"]["details"])


@pytest.mark.asyncio
async def test_assessment_contract_is_documented_without_private_coefficients(
    client: AsyncClient,
) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    document = response.json()
    assert ASSESSMENT_URL in document["paths"]
    assert "/api/tire-assessments" not in document["paths"]
    assert "/api/v1/wear-severity/calculate" not in document["paths"]
    assert "/api/v2/tire-profiles" not in document["paths"]
    assert "/api/v2/tire-simulations" not in document["paths"]
    request_schema = document["components"]["schemas"]["TireAssessmentRequest"]
    assert "asset_identity" not in request_schema["properties"]
    documented_example = request_schema["examples"][0]
    assert documented_example["intended_use"] == "SCENARIO_PLANNING"

    validated_example = TireAssessmentRequest.model_validate(documented_example)
    assert validated_example.intended_use == "SCENARIO_PLANNING"

    serialized = json.dumps(document)
    assert "parameter_status" not in serialized
    response_schema = document["components"]["schemas"]["AssessmentGovernance"]
    assert "release_target_identity" not in response_schema["properties"]
    assert "request_asset_identity" not in response_schema["properties"]
    evidence_schema = document["components"]["schemas"]["AssessmentSupportingEvidence"]
    assert "applicability" not in evidence_schema["properties"]
    assert "use" not in evidence_schema["properties"]
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
        ("POST", "/api/tire-assessments"),
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


@pytest.mark.asyncio
async def test_assessment_returns_503_when_release_integrity_fails(
    client: AsyncClient,
    simulation_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_release(_release_id: str) -> Any:
        raise ModelEvidenceIntegrityError("implementation checksum mismatch")

    monkeypatch.setattr(tire_assessor._registry, "load_release", reject_release)
    response = await client.post(ASSESSMENT_URL, json=simulation_payload)

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "MODEL_EVIDENCE_UNAVAILABLE",
            "message": (
                "The active model evidence package is unavailable or failed integrity checks."
            ),
        }
    }
