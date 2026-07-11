"""Internal physics-informed wear-severity calculation."""

from dataclasses import dataclass
from uuid import uuid4

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


@dataclass(frozen=True)
class RawWearResult:
    """Full-precision internal values shared by calculator services."""

    severity: float
    wear_rate_mm_per_cycle: float
    pressure_multiplier: float


def classify_severity(severity_index: int) -> SeverityLevel:
    """Map a severity index to its configured planning category."""

    if severity_index < model_config.MODERATE_THRESHOLD:
        return "LOW"
    if severity_index < model_config.HIGH_THRESHOLD:
        return "MODERATE"
    if severity_index < model_config.CRITICAL_THRESHOLD:
        return "HIGH"
    return "CRITICAL"


class WearCalculator:
    """Calculate a stateless tire wear-severity estimate."""

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
        spin_energy = (
            touchdown_speed_ms / model_config.REFERENCE_TOUCHDOWN_SPEED_MS
        ) ** model_config.SPIN_EXPONENT
        brake_energy = (landing_weight_kg / model_config.REFERENCE_LANDING_WEIGHT_KG) * spin_energy
        lateral_work = (
            model_config.UNIT_MULTIPLIER
            + model_config.CROSSWIND_FACTOR * crosswind_kt
            + model_config.TAXI_DISTANCE_FACTOR
            * (
                taxi_distance_km / model_config.REFERENCE_TAXI_DISTANCE_KM
                - model_config.UNIT_MULTIPLIER
            )
        )
        temperature_multiplier = model_config.UNIT_MULTIPLIER + model_config.TEMPERATURE_FACTOR * (
            outside_air_temperature_c - model_config.REFERENCE_TEMPERATURE_C
        )
        pressure_multiplier = model_config.PRESSURE_BASE ** (
            under_inflation_pct / model_config.REFERENCE_PRESSURE_DELTA_PCT
        )
        operational_severity = (
            model_config.SPIN_WEIGHT * spin_energy
            + model_config.BRAKE_WEIGHT * brake_energy
            + model_config.LATERAL_WEIGHT * lateral_work
        )
        severity = max(
            model_config.MINIMUM_SEVERITY,
            operational_severity * temperature_multiplier * pressure_multiplier,
        )

        gear_configuration = model_config.GEAR_CONFIGURATIONS[gear]
        wear_rate = gear_configuration.base_wear_rate * severity

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
        gear_configuration = model_config.GEAR_CONFIGURATIONS[request.gear]
        estimated_tread_life_cycles = round(
            (model_config.INITIAL_TREAD_DEPTH_MM - model_config.MINIMUM_TREAD_DEPTH_MM)
            / raw_result.wear_rate_mm_per_cycle
        )
        severity_index = round(raw_result.severity * model_config.SEVERITY_INDEX_SCALE)
        severity_level = classify_severity(severity_index)
        severity_configuration = model_config.SEVERITY_CONFIGURATIONS[severity_level]
        pressure_warning = (
            request.under_inflation_pct >= model_config.PRESSURE_WARNING_THRESHOLD_PCT
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
            model_version=model_config.MODEL_VERSION,
            disclaimer=model_config.DISCLAIMER,
        )


calculator = WearCalculator()
