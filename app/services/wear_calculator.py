"""Internal physics-informed wear-severity calculation."""

from dataclasses import dataclass
from uuid import uuid4

from app.domain.model_parameter_schemas import BaseSeverityParameters, ModelParameterSet
from app.domain.schemas import (
    GearValue,
    PressureEffect,
    Recommendation,
    SeverityLevel,
    SeverityResult,
    WearSeverityRequest,
    WearSeverityResponse,
)
from app.services import model_config
from app.services.model_registry import ACTIVE_MODEL_RELEASE_ID, ModelRegistry


@dataclass(frozen=True)
class RawWearResult:
    """Full-precision internal values shared by calculator services."""

    severity: float
    wear_rate_mm_per_cycle: float
    pressure_multiplier: float


def _default_parameters() -> ModelParameterSet:
    return ModelRegistry().load_release(ACTIVE_MODEL_RELEASE_ID).parameters


def classify_severity(
    severity_index: int,
    parameters: BaseSeverityParameters | None = None,
) -> SeverityLevel:
    """Map a severity index to its configured planning category."""

    active_parameters = parameters or _default_parameters().base_severity
    if severity_index < active_parameters.moderate_threshold:
        return "LOW"
    if severity_index < active_parameters.high_threshold:
        return "MODERATE"
    if severity_index < active_parameters.critical_threshold:
        return "HIGH"
    return "CRITICAL"


class WearCalculator:
    """Calculate a stateless tire wear-severity estimate."""

    def __init__(self, parameters: ModelParameterSet | None = None) -> None:
        self._parameters = parameters or _default_parameters()

    def calculate_raw_values(
        self,
        *,
        gear: GearValue,
        touchdown_speed_ms: float,
        landing_weight_kg: float,
        crosswind_kt: float,
        taxi_distance_km: float,
        outside_air_temperature_c: float,
        under_inflation_pct: float,
    ) -> RawWearResult:
        severity_parameters = self._parameters.base_severity
        spin_energy = (
            touchdown_speed_ms / severity_parameters.reference_touchdown_speed_ms
        ) ** severity_parameters.spin_exponent
        brake_energy = (
            landing_weight_kg / severity_parameters.reference_landing_weight_kg
        ) * spin_energy
        lateral_work = (
            1.0
            + severity_parameters.crosswind_factor * crosswind_kt
            + severity_parameters.taxi_distance_factor
            * (taxi_distance_km / severity_parameters.reference_taxi_distance_km - 1.0)
        )
        temperature_multiplier = 1.0 + severity_parameters.temperature_factor * (
            outside_air_temperature_c - severity_parameters.reference_temperature_c
        )
        pressure_multiplier = severity_parameters.pressure_base ** (
            under_inflation_pct / severity_parameters.reference_pressure_delta_pct
        )
        operational_severity = (
            severity_parameters.spin_weight * spin_energy
            + severity_parameters.brake_weight * brake_energy
            + severity_parameters.lateral_weight * lateral_work
        )
        severity = max(
            severity_parameters.minimum_severity,
            operational_severity * temperature_multiplier * pressure_multiplier,
        )

        gear_configuration = self._parameters.gear_configurations.for_gear(gear)
        wear_rate = gear_configuration.base_wear_rate_mm_per_cycle * severity

        return RawWearResult(
            severity=severity,
            wear_rate_mm_per_cycle=wear_rate,
            pressure_multiplier=pressure_multiplier,
        )

    def calculate_raw(self, request: WearSeverityRequest) -> RawWearResult:
        return self.calculate_raw_values(
            gear=request.gear,
            touchdown_speed_ms=request.touchdown_speed_ms,
            landing_weight_kg=request.landing_weight_kg,
            crosswind_kt=request.crosswind_kt,
            taxi_distance_km=request.taxi_distance_km,
            outside_air_temperature_c=request.outside_air_temperature_c,
            under_inflation_pct=request.under_inflation_pct,
        )

    def calculate(self, request: WearSeverityRequest) -> WearSeverityResponse:
        raw_result = self.calculate_raw(request)
        severity_parameters = self._parameters.base_severity
        gear_configuration = self._parameters.gear_configurations.for_gear(request.gear)
        profile = next(
            profile for profile in self._parameters.profiles if profile.gear == request.gear
        )
        estimated_tread_life_cycles = round(
            (profile.initial_tread_depth_mm - profile.planning_threshold_mm)
            / raw_result.wear_rate_mm_per_cycle
        )
        severity_index = round(raw_result.severity * severity_parameters.severity_index_scale)
        severity_level = classify_severity(severity_index, severity_parameters)
        severity_configuration = model_config.SEVERITY_CONFIGURATIONS[severity_level]
        pressure_warning = (
            request.under_inflation_pct >= severity_parameters.pressure_warning_threshold_pct
        )

        return WearSeverityResponse(
            calculation_id=uuid4(),
            gear=request.gear,
            gear_label=gear_configuration.label,
            severity=SeverityResult(
                index=severity_index,
                level=severity_level,
                label=severity_configuration.label,
            ),
            estimated_wear_rate_mm_per_cycle=round(
                raw_result.wear_rate_mm_per_cycle, model_config.WEAR_RATE_OUTPUT_DECIMALS
            ),
            estimated_total_tread_life_cycles=estimated_tread_life_cycles,
            pressure_effect=PressureEffect(
                multiplier=round(
                    raw_result.pressure_multiplier,
                    model_config.PRESSURE_MULTIPLIER_OUTPUT_DECIMALS,
                ),
                warning=pressure_warning,
                message=model_config.PRESSURE_WARNING_MESSAGE if pressure_warning else None,
            ),
            recommendation=Recommendation(
                attention=severity_configuration.attention,
                message=severity_configuration.message,
            ),
            model_version=severity_parameters.model_version,
            disclaimer=model_config.DISCLAIMER,
        )
