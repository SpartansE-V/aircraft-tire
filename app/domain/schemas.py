"""Strict public request and response schemas."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

GearValue = Literal["main", "nose"]
SeverityLevel = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
AttentionLevel = Literal[
    "ROUTINE_MONITORING",
    "NORMAL_MONITORING",
    "INCREASED_ATTENTION",
    "MAINTENANCE_ATTENTION",
]

TOUCHDOWN_SPEED_RANGE = (58.0, 82.0)
LANDING_WEIGHT_RANGE = (50_000.0, 73_500.0)
CROSSWIND_RANGE = (0.0, 25.0)
TAXI_DISTANCE_RANGE = (0.5, 8.0)
TEMPERATURE_RANGE = (5.0, 45.0)
UNDER_INFLATION_RANGE = (0.0, 10.0)

INPUT_RANGES: dict[str, tuple[float, float]] = {
    "touchdown_speed_ms": TOUCHDOWN_SPEED_RANGE,
    "landing_weight_kg": LANDING_WEIGHT_RANGE,
    "crosswind_kt": CROSSWIND_RANGE,
    "taxi_distance_km": TAXI_DISTANCE_RANGE,
    "outside_air_temperature_c": TEMPERATURE_RANGE,
    "under_inflation_pct": UNDER_INFLATION_RANGE,
}


class StrictSchema(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class WearSeverityRequest(StrictSchema):
    """Aircraft operating conditions for one wear-severity estimate."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "gear": "main",
                    "touchdown_speed_ms": 69,
                    "landing_weight_kg": 62000,
                    "crosswind_kt": 6,
                    "taxi_distance_km": 2.8,
                    "outside_air_temperature_c": 30,
                    "under_inflation_pct": 0,
                }
            ]
        },
    )

    gear: GearValue = Field(
        description=(
            "Tire position: main gear carries more aircraft load; nose gear carries less load."
        )
    )
    touchdown_speed_ms: float = Field(
        ge=TOUCHDOWN_SPEED_RANGE[0],
        le=TOUCHDOWN_SPEED_RANGE[1],
        allow_inf_nan=False,
        description="Aircraft touchdown speed in metres per second (58 to 82 m/s).",
    )
    landing_weight_kg: float = Field(
        ge=LANDING_WEIGHT_RANGE[0],
        le=LANDING_WEIGHT_RANGE[1],
        allow_inf_nan=False,
        description="Aircraft landing weight in kilograms (50,000 to 73,500 kg).",
    )
    crosswind_kt: float = Field(
        ge=CROSSWIND_RANGE[0],
        le=CROSSWIND_RANGE[1],
        allow_inf_nan=False,
        description="Crosswind component in knots (0 to 25 kt).",
    )
    taxi_distance_km: float = Field(
        ge=TAXI_DISTANCE_RANGE[0],
        le=TAXI_DISTANCE_RANGE[1],
        allow_inf_nan=False,
        description=(
            "Taxi distance associated with the operating cycle in kilometres (0.5 to 8 km)."
        ),
    )
    outside_air_temperature_c: float = Field(
        ge=TEMPERATURE_RANGE[0],
        le=TEMPERATURE_RANGE[1],
        allow_inf_nan=False,
        description="Outside-air temperature in degrees Celsius (5 to 45 °C).",
    )
    under_inflation_pct: float = Field(
        ge=UNDER_INFLATION_RANGE[0],
        le=UNDER_INFLATION_RANGE[1],
        allow_inf_nan=False,
        description=(
            "Amount below the approved cold inflation pressure, as a percentage (0 to 10%)."
        ),
    )


class SeverityResult(StrictSchema):
    index: int = Field(description="Relative wear-severity index for the supplied conditions.")
    level: SeverityLevel = Field(
        description=(
            "Planning category: LOW (<90), MODERATE (90–119), HIGH (120–169), or CRITICAL (170+)."
        )
    )
    label: str = Field(description="Human-readable severity category.")


class PressureEffect(StrictSchema):
    multiplier: float = Field(description="Relative pressure-related wear effect.")
    warning: bool = Field(description="Whether under-inflation needs explicit attention.")
    message: str | None = Field(
        default=None,
        description="Pressure-verification guidance when the warning threshold is reached.",
    )


class Recommendation(StrictSchema):
    attention: AttentionLevel = Field(description="Suggested maintenance-planning attention level.")
    message: str = Field(description="Inspection-planning guidance; never an approval for service.")


class WearSeverityResponse(StrictSchema):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "calculation_id": "3c690c67-1932-48ae-a96b-d5865f4568cc",
                    "gear": "main",
                    "gear_label": "Main gear",
                    "severity": {
                        "index": 110,
                        "level": "MODERATE",
                        "label": "Moderate wear conditions",
                    },
                    "estimated_wear_rate_mm_per_cycle": 0.044,
                    "estimated_total_tread_life_cycles": 225,
                    "pressure_effect": {"multiplier": 1.0, "warning": False},
                    "recommendation": {
                        "attention": "NORMAL_MONITORING",
                        "message": (
                            "Operating conditions are within the normal pilot range. Continue "
                            "inspections according to the maintenance schedule."
                        ),
                    },
                    "model_version": "pilot-1.0.0",
                    "disclaimer": (
                        "This result is a physics-informed hackathon estimate. It does not replace "
                        "physical inspection, aircraft maintenance manuals, or qualified "
                        "engineering approval."
                    ),
                }
            ]
        },
    )

    calculation_id: UUID = Field(description="Stateless UUID for correlating this calculation.")
    gear: GearValue
    gear_label: str
    severity: SeverityResult
    estimated_wear_rate_mm_per_cycle: float = Field(
        description="Estimated tread wear per operating cycle, in millimetres."
    )
    estimated_total_tread_life_cycles: int = Field(
        description="Estimated total cycles across the modeled tread-depth range."
    )
    pressure_effect: PressureEffect
    recommendation: Recommendation
    model_version: str
    disclaimer: str


class RootResponse(StrictSchema):
    service: str
    version: str
    status: str
    documentation: str


class HealthResponse(StrictSchema):
    status: str


# ---------------------------------------------------------------------------
# RUL prediction (the AI endpoint) — contract for app.services.rul_service,
# which is the only place the backend crosses into the app.rul model package.
# ---------------------------------------------------------------------------
WheelPositionValue = Literal[
    "nlg_l",
    "nlg_r",
    "mlg_l_inbd",
    "mlg_l_outbd",
    "mlg_r_inbd",
    "mlg_r_outbd",
]
RulStatusValue = Literal["healthy", "monitor", "schedule", "replace_now"]
RulSeverityValue = Literal["info", "warning", "critical"]

MAX_READINGS = 200
MAX_GROOVE_MM = 30.0
MAX_CURRENT_CYCLES = 20_000.0
MAX_LANDINGS_PER_DAY = 20.0


class InspectionReading(StrictSchema):
    """One tread-depth measurement for the tire being forecast."""

    cycles_since_install: float = Field(
        ge=0.0,
        le=MAX_CURRENT_CYCLES,
        allow_inf_nan=False,
        description="Cumulative landings the tire had flown when this groove depth was measured.",
    )
    measured_groove_mm: float = Field(
        gt=0.0,
        le=MAX_GROOVE_MM,
        allow_inf_nan=False,
        description="Measured remaining groove depth in millimetres.",
    )


class RulPredictionRequest(StrictSchema):
    """A single wheel's readings and utilization for one remaining-useful-life forecast."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "position": "mlg_r_inbd",
                    "current_cycles": 190,
                    "landings_per_day": 4.0,
                    "readings": [
                        {"cycles_since_install": 0, "measured_groove_mm": 12.0},
                        {"cycles_since_install": 90, "measured_groove_mm": 9.0},
                        {"cycles_since_install": 190, "measured_groove_mm": 6.1},
                    ],
                }
            ]
        },
    )

    position: WheelPositionValue = Field(
        description="Wheel position; selects the fitted per-position degradation prior."
    )
    current_cycles: float = Field(
        ge=0.0,
        le=MAX_CURRENT_CYCLES,
        allow_inf_nan=False,
        description="Landings the tire has flown so far (the point RUL is measured from).",
    )
    landings_per_day: float = Field(
        gt=0.0,
        le=MAX_LANDINGS_PER_DAY,
        allow_inf_nan=False,
        description="Assumed utilization, used to convert remaining landings into calendar dates.",
    )
    readings: list[InspectionReading] = Field(
        default_factory=list,
        max_length=MAX_READINGS,
        description=(
            "Tread-depth history for this tire. May be empty — the forecast then falls back to the "
            "fleet/position prior and is flagged low_confidence."
        ),
    )
    as_of_date: date | None = Field(
        default=None,
        # JSON has no date type, so accept ISO "YYYY-MM-DD" strings despite model-level strictness.
        strict=False,
        description=(
            "Reference date (ISO 8601, e.g. 2026-07-11) for the returned wear-to-limit dates. "
            "Defaults to today (UTC)."
        ),
    )


class RulQuantiles(StrictSchema):
    p10: float = Field(description="Earliest-credible remaining landings (10th percentile).")
    median: float = Field(description="Expected remaining landings (50th percentile).")
    p90: float = Field(description="Latest-credible remaining landings (90th percentile).")
    mean: float = Field(description="Mean remaining landings across Monte-Carlo draws.")


class WearToLimitDates(StrictSchema):
    earliest_credible_p10: date = Field(
        description="Date the P10 (earliest-credible) RUL is reached."
    )
    median: date = Field(description="Date the median RUL is reached.")
    p90: date = Field(description="Date the P90 (latest-credible) RUL is reached.")


class RulStatus(StrictSchema):
    status: RulStatusValue = Field(description="Overall wheel condition category.")
    severity: RulSeverityValue = Field(description="Severity of the recommended attention level.")
    headline: str = Field(description="One-line plain-language condition summary.")
    recommended_action: str = Field(description="Suggested maintenance-planning action.")


class RulPredictionResponse(StrictSchema):
    prediction_id: UUID = Field(description="Stateless UUID for correlating this prediction.")
    position: WheelPositionValue
    rul_landings: RulQuantiles
    wear_to_limit_dates: WearToLimitDates
    p_cross_before_next_check: float = Field(
        description="Probability the wear limit is crossed before the next scheduled check."
    )
    landings_per_day: float
    readings_used: int = Field(description="Number of readings the posterior was fit on.")
    low_confidence: bool = Field(
        description="True when too few readings were supplied and the fleet prior dominates."
    )
    status: RulStatus
    wear_limit_mm: float = Field(
        description="Serviceable groove-depth limit used for the crossing."
    )
    model_version: str
    disclaimer: str
