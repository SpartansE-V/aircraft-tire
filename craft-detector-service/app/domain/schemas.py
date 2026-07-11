"""Strict public request and response schemas."""

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


class ModelPrediction(StrictSchema):
    x: float = Field(description="Bounding-box centre x-coordinate in pixels.")
    y: float = Field(description="Bounding-box centre y-coordinate in pixels.")
    width: float = Field(description="Bounding-box width in pixels.")
    height: float = Field(description="Bounding-box height in pixels.")
    confidence: float = Field(ge=0.0, le=1.0, description="Model confidence score.")
    class_name: str = Field(
        alias="class",
        description="Detected class label.",
    )
    class_id: int = Field(description="Numeric class identifier from the model.")
    detection_id: str = Field(description="Unique identifier for the detection.")


class TyreQualityPrediction(ModelPrediction):
    class_name: str = Field(
        alias="class",
        description="Detected tyre-quality class label.",
    )


class TyreQualityResponse(StrictSchema):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "predictions": [
                        {
                            "x": 321,
                            "y": 273,
                            "width": 622,
                            "height": 472,
                            "confidence": 0.824,
                            "class": "bad_tyre",
                            "class_id": 0,
                            "detection_id": "ea4dce18-94eb-4c4a-a358-4bb8b860d0fb",
                        }
                    ]
                }
            ]
        },
    )

    predictions: list[TyreQualityPrediction] = Field(
        description="YOLO detections returned by the Roboflow model.",
    )


class TreadDepthPrediction(ModelPrediction):
    class_name: str = Field(
        alias="class",
        description="Detected tread-depth class label (e.g. '7-8 mm').",
    )


class TreadDepthResponse(StrictSchema):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "predictions": [
                        {
                            "x": 2019,
                            "y": 1285.5,
                            "width": 4026,
                            "height": 397,
                            "confidence": 0.832,
                            "class": "7-8 mm",
                            "class_id": 6,
                            "detection_id": "0d34376c-a32b-4811-9bd9-9b0c68937207",
                        },
                        {
                            "x": 2016,
                            "y": 1781.5,
                            "width": 4000,
                            "height": 531,
                            "confidence": 0.749,
                            "class": "7-8 mm",
                            "class_id": 6,
                            "detection_id": "3332d823-6752-41c3-aeb5-334ef0296d2c",
                        },
                        {
                            "x": 2017,
                            "y": 729,
                            "width": 4026,
                            "height": 518,
                            "confidence": 0.55,
                            "class": "7-8 mm",
                            "class_id": 6,
                            "detection_id": "b100d76d-0d93-4de9-a7eb-e08a660da31a",
                        },
                    ]
                }
            ]
        },
    )

    predictions: list[TreadDepthPrediction] = Field(
        description="YOLO detections returned by the tread-depth Roboflow model.",
    )
