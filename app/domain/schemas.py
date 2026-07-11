"""Strict public request and response schemas."""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
# RUL prediction (the AI endpoint) — contract for app.services.tire_rul_service,
# which is the only place the backend crosses into the app.tire_rul model package.
# ---------------------------------------------------------------------------
WheelPositionValue = Literal[
    "nlg_l",
    "nlg_r",
    "mlg_l_inbd",
    "mlg_l_outbd",
    "mlg_r_inbd",
    "mlg_r_outbd",
]
TireRulStatusValue = Literal["healthy", "monitor", "schedule", "replace_now"]
TireRulSeverityValue = Literal["info", "warning", "critical"]

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


class FlightConditions(StrictSchema):
    """Normalized wear factors for newly completed/planned takeoff-and-landing cycles.

    A value of 1.0 is a normal fleet-average cycle; values above 1.0 represent more severe
    exposure. The service combines these with position-specific sensitivities.
    """

    landing_load_factor: float = Field(default=1.0, ge=0.5, le=1.5, allow_inf_nan=False)
    braking_energy_factor: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)
    takeoff_severity_factor: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)
    taxi_heat_factor: float = Field(default=1.0, ge=0.5, le=1.5, allow_inf_nan=False)
    temperature_factor: float = Field(default=1.0, ge=0.5, le=1.5, allow_inf_nan=False)
    inflation_factor: float = Field(default=1.0, ge=1.0, le=1.8, allow_inf_nan=False)
    runway_roughness_factor: float = Field(default=1.0, ge=1.0, le=1.5, allow_inf_nan=False)
    hard_landing_factor: float = Field(default=1.0, ge=1.0, le=2.2, allow_inf_nan=False)
    crosswind_factor: float = Field(default=1.0, ge=1.0, le=1.5, allow_inf_nan=False)


class TireRulPredictionRequest(StrictSchema):
    """A single wheel's readings and utilization for one remaining-useful-life forecast."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "position": "mlg_r_inbd",
                    "current_cycles": 190,
                    "planned_landings": 20,
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
    planned_landings: float = Field(
        default=0.0,
        ge=0.0,
        le=MAX_CURRENT_CYCLES,
        allow_inf_nan=False,
        description=(
            "Additional planned landings to apply as a what-if horizon. The forecast is evaluated "
            "at current_cycles + planned_landings without changing the inspection history."
        ),
    )
    flight_conditions: FlightConditions = Field(
        default_factory=FlightConditions,
        description="Wear factors applied only to planned_landings; defaults to normal exposure.",
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


class TireRulQuantiles(StrictSchema):
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


class TireRulStatus(StrictSchema):
    status: TireRulStatusValue = Field(description="Overall wheel condition category.")
    severity: TireRulSeverityValue = Field(
        description="Severity of the recommended attention level."
    )
    headline: str = Field(description="One-line plain-language condition summary.")
    recommended_action: str = Field(description="Suggested maintenance-planning action.")


class TireRulPredictionResponse(StrictSchema):
    prediction_id: UUID = Field(description="Stateless UUID for correlating this prediction.")
    position: WheelPositionValue
    rul_landings: TireRulQuantiles
    wear_to_limit_dates: WearToLimitDates
    p_cross_before_next_check: float = Field(
        description="Probability the wear limit is crossed before the next scheduled check."
    )
    landings_per_day: float
    wear_exposure_multiplier: float = Field(
        description="Position-specific multiplier applied to the newly planned landings."
    )
    effective_planned_landings: float = Field(
        description="Planned landings converted to fleet-average wear-equivalent landings."
    )
    readings_used: int = Field(description="Number of readings the posterior was fit on.")
    low_confidence: bool = Field(
        description="True when too few readings were supplied and the fleet prior dominates."
    )
    status: TireRulStatus
    wear_limit_mm: float = Field(
        description="Serviceable groove-depth limit used for the crossing."
    )
    model_version: str
    disclaimer: str


# ---------------------------------------------------------------------------
# Maintenance Decision Agent — contract for app.services.agent_service, which
# wraps app.tire_rul.agent (LLM tool-calling over the fleet dataset) for the FE.
# ---------------------------------------------------------------------------
AgentBackendValue = Literal["auto", "openai", "bedrock", "mock"]
AgentRoleValue = Literal["user", "assistant"]

MAX_AGENT_MESSAGES = 40
MAX_AGENT_MESSAGE_CHARS = 4000
MAX_WORKLIST_TOP_N = 50


class AgentChatMessage(StrictSchema):
    """One turn of the engineer/agent conversation."""

    role: AgentRoleValue = Field(description="Who wrote the turn: the engineer or the agent.")
    content: str = Field(
        min_length=1,
        max_length=MAX_AGENT_MESSAGE_CHARS,
        description="Turn text. Assistant turns are the agent's earlier Markdown answers.",
    )


class AgentChatRequest(StrictSchema):
    """Full conversation history, ending with the newest engineer message."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "messages": [
                        {"role": "user", "content": "What should I do about VN-A320 MLG L INBD?"}
                    ],
                    "backend": "auto",
                }
            ]
        },
    )

    messages: list[AgentChatMessage] = Field(
        min_length=1,
        max_length=MAX_AGENT_MESSAGES,
        description=(
            "Conversation so far, oldest first, ending with the newest user message. Send the "
            "full history each call — the API is stateless and follow-ups may reference earlier "
            "turns ('predict it')."
        ),
    )
    backend: AgentBackendValue = Field(
        default="auto",
        description=(
            "Agent backend: 'auto' picks the first configured LLM (OpenAI, then Bedrock) and "
            "falls back to the offline deterministic planner ('mock')."
        ),
    )

    @model_validator(mode="after")
    def _last_message_is_user(self) -> "AgentChatRequest":
        if self.messages[-1].role != "user":
            raise ValueError("messages must end with a 'user' message")
        return self


class AgentToolCall(StrictSchema):
    """One pipeline tool the agent invoked while investigating, with its raw result."""

    tool: str = Field(description="Tool name (e.g. get_wheel_status, run_rul_prediction).")
    args: dict[str, Any] = Field(description="Arguments the agent passed to the tool.")
    result: dict[str, Any] = Field(description="JSON result the tool returned to the agent.")


class AgentChatResponse(StrictSchema):
    chat_id: UUID = Field(description="Stateless UUID for correlating this exchange.")
    answer: str = Field(description="The agent's grounded answer, in Markdown.")
    trace: list[AgentToolCall] = Field(
        description="Ordered tool-call trace behind the answer (render as 'how it investigated')."
    )
    backend: str = Field(description="Backend that produced the answer, e.g. 'openai:gpt-4o-mini'.")
    as_of_date: date = Field(description="Fleet snapshot date the tools answered from.")
    disclaimer: str


class PriorityWheel(StrictSchema):
    """One row of the ranked maintenance worklist."""

    rank: int
    tail_number: str
    position: WheelPositionValue
    station: str = Field(description="Home station of the aircraft (spares are held per station).")
    priority: float = Field(description="Composite priority: P(cross before check) x consequence.")
    p_cross_before_next_check: float
    rul_median_landings: float
    rul_p10_landings: float
    earliest_credible_date: date
    low_confidence: bool
    reason: str = Field(description="Why this wheel ranks here (plain language).")
    action: str = Field(description="Recommended planning action.")


class FleetWorklistResponse(StrictSchema):
    as_of_date: date
    wheels: list[PriorityWheel]
    disclaimer: str


class WheelStatusResponse(StrictSchema):
    """Current condition + forecast for one mounted wheel of the fleet dataset."""

    tail_number: str
    position: WheelPositionValue
    status: TireRulStatusValue
    severity: TireRulSeverityValue
    headline: str
    explanation: str
    recommended_action: str
    rul_median_landings: float
    rul_p10_landings: float
    earliest_credible_date: date
    p_cross_before_next_check: float
    priority: float = Field(
        description="Position-aware maintenance priority: crossing probability x consequence."
    )
    pressure_pct: float | None
    pressure_action: str
    station: str
    spares_on_hand: int
    utilization_landings_per_day: float
    current_cycles: float = Field(
        description="Total landed cycles for the mounted tire at the current fleet snapshot."
    )
    readings: list[InspectionReading] = Field(
        description="Inspection history for the mounted tire, ready to reuse in a RUL prediction."
    )
    low_confidence: bool
    as_of_date: date
    disclaimer: str


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
