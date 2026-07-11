"""Fail-closed intended-use and physical-condition gates for tire assessments."""

from dataclasses import dataclass

from app.domain.assessment_schemas import TireAssessmentRequest
from app.domain.governance_schemas import GovernanceDecision
from app.domain.model_parameter_schemas import ModelParameterSet, SimulationProfileParameters
from app.services.model_registry import LoadedModelRelease
from app.services.safety_policy import (
    FORECAST_WITHHOLD_PRESSURE_DEFICIT_PCT,
    calculate_pressure_deficit_pct,
)


@dataclass(frozen=True)
class AssessmentGateError(RuntimeError):
    code: str
    message: str
    status_code: int
    details: tuple[tuple[str, str], ...] = ()

    def __str__(self) -> str:
        return self.message


def evaluate_assessment_gate(
    request: TireAssessmentRequest,
    release: LoadedModelRelease,
    *,
    profile: SimulationProfileParameters,
) -> GovernanceDecision:
    """Permit only evidence-authorized use and withhold unsafe numeric forecasts."""

    release_target = release.manifest.target_identity
    if release_target is not None:
        raise AssessmentGateError(
            code="MODEL_TARGET_IDENTITY_UNAVAILABLE",
            message=(
                "This generic endpoint cannot serve a target-specific aircraft-tire model release."
            ),
            status_code=409,
        )

    validate_model_domain(request, release.parameters, profile)
    condition = request.current_condition
    if condition.known_defects:
        observed_defects = ", ".join(condition.known_defects)
        raise AssessmentGateError(
            code="ASSESSMENT_WITHHELD",
            message=(
                "A numeric forecast is withheld because a known tire defect requires qualified "
                "physical inspection and approved maintenance data."
            ),
            status_code=409,
            details=(
                ("current_condition.known_defects", f"Observed defects: {observed_defects}."),
                (
                    "required_action",
                    "Qualified physical inspection using approved maintenance data is required.",
                ),
            ),
        )
    if condition.current_tread_depth_mm <= profile.planning_threshold_mm:
        raise AssessmentGateError(
            code="ASSESSMENT_WITHHELD",
            message=(
                "A numeric forecast is withheld because the planning threshold has been reached."
            ),
            status_code=409,
        )
    pressure_deficit_pct = calculate_pressure_deficit_pct(
        measured_cold_pressure_psi=condition.measured_cold_pressure_psi,
        reference_cold_pressure_psi=condition.reference_cold_pressure_psi,
    )
    if pressure_deficit_pct >= FORECAST_WITHHOLD_PRESSURE_DEFICIT_PCT:
        raise AssessmentGateError(
            code="ASSESSMENT_WITHHELD",
            message=(
                "A numeric forecast is withheld because the pressure deficit requires qualified "
                "inspection using an approved procedure."
            ),
            status_code=409,
        )

    decision = release.evaluate_governance(request.intended_use)
    if not decision.permitted:
        raise AssessmentGateError(
            code="MODEL_NOT_AUTHORIZED_FOR_INTENDED_USE",
            message=(
                "The active model release is not authorized for the requested maintenance or "
                "dispatch use."
            ),
            status_code=409,
        )
    if request.intended_use != "SCENARIO_PLANNING":
        raise AssessmentGateError(
            code="CONTROLLED_OPERATIONAL_CONFIGURATION_UNAVAILABLE",
            message=(
                "Operational output remains disabled because this deployment does not resolve "
                "pressure and service limits from a controlled installation configuration."
            ),
            status_code=409,
        )
    return decision


def validate_model_domain(
    request: TireAssessmentRequest,
    parameters: ModelParameterSet,
    profile: SimulationProfileParameters,
) -> None:
    """Reject values outside the envelope recorded in the active release artifact."""

    condition = request.current_condition
    if condition.current_tread_depth_mm > profile.initial_tread_depth_mm:
        raise AssessmentGateError(
            code="MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN",
            message="Current tread depth is outside the active profile's modeled range.",
            status_code=422,
        )
    if condition.measured_cold_pressure_psi > condition.reference_cold_pressure_psi:
        raise AssessmentGateError(
            code="MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN",
            message="Pressure above the scenario reference is not modeled by this release.",
            status_code=422,
        )

    pressure_deficit_pct = calculate_pressure_deficit_pct(
        measured_cold_pressure_psi=condition.measured_cold_pressure_psi,
        reference_cold_pressure_psi=condition.reference_cold_pressure_psi,
    )
    pressure_domain = parameters.input_domain.under_inflation_pct
    if not pressure_domain.minimum <= pressure_deficit_pct <= pressure_domain.maximum:
        raise AssessmentGateError(
            code="MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN",
            message="Pressure deficit is outside the active release's modeled range.",
            status_code=422,
        )

    future = request.future_conditions
    domain = parameters.input_domain
    distributions = (
        ("landing_weight_kg", future.landing_weight_kg, domain.landing_weight_kg),
        (
            "touchdown_ground_speed_ms",
            future.touchdown_ground_speed_ms,
            domain.touchdown_speed_ms,
        ),
        ("crosswind_kt", future.crosswind_kt, domain.crosswind_kt),
        (
            "touchdown_sink_rate_ms",
            future.touchdown_sink_rate_ms,
            domain.touchdown_sink_rate_ms,
        ),
        (
            "touchdown_yaw_angle_deg",
            future.touchdown_yaw_angle_deg,
            domain.touchdown_yaw_angle_deg,
        ),
        ("taxi_distance_km", future.taxi_distance_km, domain.taxi_distance_km),
        (
            "average_taxi_speed_kt",
            future.average_taxi_speed_kt,
            domain.average_taxi_speed_kt,
        ),
        (
            "outside_air_temperature_c",
            future.outside_air_temperature_c,
            domain.outside_air_temperature_c,
        ),
        (
            "brake_temperature_c",
            future.brake_temperature_c,
            domain.brake_temperature_c,
        ),
    )
    for field_name, distribution, allowed in distributions:
        if distribution.minimum < allowed.minimum or distribution.maximum > allowed.maximum:
            raise AssessmentGateError(
                code="MODEL_INPUT_OUTSIDE_RELEASE_DOMAIN",
                message=f"{field_name} is outside the active release's modeled range.",
                status_code=422,
            )
