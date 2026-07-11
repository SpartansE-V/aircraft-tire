"""Internal physics-informed wear-severity calculation."""

from uuid import uuid4

from app.domain.schemas import (
    PressureEffect,
    Recommendation,
    SeverityLevel,
    SeverityResult,
    WearSeverityRequest,
    WearSeverityResponse,
)
from app.services import model_config


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

    def calculate(self, request: WearSeverityRequest) -> WearSeverityResponse:
        spin_energy = (
            request.touchdown_speed_ms / model_config.REFERENCE_TOUCHDOWN_SPEED_MS
        ) ** model_config.SPIN_EXPONENT
        brake_energy = (
            request.landing_weight_kg / model_config.REFERENCE_LANDING_WEIGHT_KG
        ) * spin_energy
        lateral_work = (
            model_config.UNIT_MULTIPLIER
            + model_config.CROSSWIND_FACTOR * request.crosswind_kt
            + model_config.TAXI_DISTANCE_FACTOR
            * (
                request.taxi_distance_km / model_config.REFERENCE_TAXI_DISTANCE_KM
                - model_config.UNIT_MULTIPLIER
            )
        )
        temperature_multiplier = model_config.UNIT_MULTIPLIER + model_config.TEMPERATURE_FACTOR * (
            request.outside_air_temperature_c - model_config.REFERENCE_TEMPERATURE_C
        )
        pressure_multiplier = model_config.PRESSURE_BASE ** (
            request.under_inflation_pct / model_config.REFERENCE_PRESSURE_DELTA_PCT
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

        gear_configuration = model_config.GEAR_CONFIGURATIONS[request.gear]
        wear_rate = gear_configuration.base_wear_rate * severity
        estimated_tread_life_cycles = round(
            (model_config.INITIAL_TREAD_DEPTH_MM - model_config.MINIMUM_TREAD_DEPTH_MM) / wear_rate
        )
        severity_index = round(severity * model_config.SEVERITY_INDEX_SCALE)
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
                wear_rate, model_config.WEAR_RATE_OUTPUT_DECIMALS
            ),
            estimated_total_tread_life_cycles=estimated_tread_life_cycles,
            pressure_effect=PressureEffect(
                multiplier=round(
                    pressure_multiplier,
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
