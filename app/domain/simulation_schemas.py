"""Scenario inputs and outputs composed by the v1 tire-assessment API."""

from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from app.domain.schemas import GearValue, StrictSchema

SimulationProfileId = Literal["pilot-main-v1", "pilot-nose-v1"]
RunwayCondition = Literal["DRY", "WET", "CONTAMINATED", "ROUGH"]
KnownDefect = Literal[
    "CUT",
    "BULGE",
    "SEPARATION",
    "FLAT_SPOT",
    "CHUNKING",
    "EXPOSED_CORD",
    "HEAT_DAMAGE",
    "CONTAMINATION",
    "FOD",
]
CurrentConditionStatus = Literal[
    "MONITOR",
    "PRESSURE_ATTENTION",
    "PLANNING_THRESHOLD_REACHED",
    "QUALIFIED_INSPECTION_REQUIRED",
]


class RangeDistribution(StrictSchema):
    """Bounded triangular distribution for one future operating input."""

    minimum: float = Field(allow_inf_nan=False)
    most_likely: float = Field(allow_inf_nan=False)
    maximum: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self) -> "RangeDistribution":
        if not self.minimum <= self.most_likely <= self.maximum:
            raise ValueError("minimum must be <= most_likely <= maximum")
        return self


class CurrentTireCondition(StrictSchema):
    cycles_since_install: int = Field(ge=0, le=100_000)
    current_tread_depth_mm: float = Field(ge=0.0, le=100.0, allow_inf_nan=False)
    measured_cold_pressure_psi: float = Field(gt=0, le=500, allow_inf_nan=False)
    reference_cold_pressure_psi: float = Field(gt=0, le=500, allow_inf_nan=False)
    tire_temperature_c: float = Field(ge=-60, le=150, allow_inf_nan=False)
    retread_count: int = Field(default=0, ge=0, le=20)
    known_defects: list[KnownDefect] = Field(default_factory=list, max_length=20)


class FutureOperatingConditions(StrictSchema):
    model_config = ConfigDict(strict=True, extra="forbid")

    landing_weight_kg: RangeDistribution
    touchdown_ground_speed_ms: RangeDistribution
    crosswind_kt: RangeDistribution
    touchdown_sink_rate_ms: RangeDistribution
    touchdown_yaw_angle_deg: RangeDistribution
    taxi_distance_km: RangeDistribution
    average_taxi_speed_kt: RangeDistribution
    outside_air_temperature_c: RangeDistribution
    brake_temperature_c: RangeDistribution
    heavy_braking_probability: float = Field(ge=0, le=1, allow_inf_nan=False)
    runway_condition: RunwayCondition


class TireSimulationRequest(StrictSchema):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "profile_id": "pilot-main-v1",
                    "current_condition": {
                        "cycles_since_install": 94,
                        "current_tread_depth_mm": 6.8,
                        "measured_cold_pressure_psi": 198.0,
                        "reference_cold_pressure_psi": 205.0,
                        "tire_temperature_c": 30.0,
                        "retread_count": 1,
                        "known_defects": [],
                    },
                    "horizon_cycles": 50,
                    "simulation_runs": 1000,
                    "random_seed": 42,
                    "future_conditions": {
                        "landing_weight_kg": {
                            "minimum": 58000.0,
                            "most_likely": 64000.0,
                            "maximum": 70000.0,
                        },
                        "touchdown_ground_speed_ms": {
                            "minimum": 63.0,
                            "most_likely": 69.0,
                            "maximum": 76.0,
                        },
                        "crosswind_kt": {
                            "minimum": 0.0,
                            "most_likely": 8.0,
                            "maximum": 18.0,
                        },
                        "touchdown_sink_rate_ms": {
                            "minimum": 0.5,
                            "most_likely": 1.2,
                            "maximum": 2.0,
                        },
                        "touchdown_yaw_angle_deg": {
                            "minimum": 0.0,
                            "most_likely": 2.0,
                            "maximum": 6.0,
                        },
                        "taxi_distance_km": {
                            "minimum": 2.0,
                            "most_likely": 4.2,
                            "maximum": 6.0,
                        },
                        "average_taxi_speed_kt": {
                            "minimum": 8.0,
                            "most_likely": 14.0,
                            "maximum": 22.0,
                        },
                        "outside_air_temperature_c": {
                            "minimum": 18.0,
                            "most_likely": 29.0,
                            "maximum": 39.0,
                        },
                        "brake_temperature_c": {
                            "minimum": 100.0,
                            "most_likely": 220.0,
                            "maximum": 380.0,
                        },
                        "heavy_braking_probability": 0.05,
                        "runway_condition": "DRY",
                    },
                }
            ]
        },
    )

    profile_id: SimulationProfileId
    current_condition: CurrentTireCondition
    horizon_cycles: int = Field(ge=1, le=500)
    simulation_runs: int = Field(default=1000, ge=100, le=20_000)
    random_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    future_conditions: FutureOperatingConditions


class SimulationProfile(StrictSchema):
    profile_id: SimulationProfileId
    display_name: str
    gear: GearValue
    model_status: Literal["DEMONSTRATION_ONLY"]
    initial_tread_depth_mm: float
    planning_threshold_mm: float
    certified_limits_available: bool
    disclaimer: str


class SimulationProfileCatalog(StrictSchema):
    profiles: list[SimulationProfile]


class ApprovedLimitEvaluation(StrictSchema):
    status: Literal["NOT_AVAILABLE"]
    demonstration_planning_threshold_mm: float = Field(ge=0, allow_inf_nan=False)
    basis: Literal["SYNTHETIC_PILOT_ASSUMPTION"]
    message: str


class CurrentConditionEvaluation(StrictSchema):
    status: CurrentConditionStatus
    pressure_deficit_pct: float
    known_defects: list[KnownDefect]


class FloatDistributionSummary(StrictSchema):
    p10: float
    p50: float
    p90: float


class IntegerDistributionSummary(StrictSchema):
    p10: int
    p50: int
    p90: int


class WearForecast(StrictSchema):
    horizon_cycles: int
    final_tread_depth_mm: FloatDistributionSummary
    cycles_to_planning_threshold: IntegerDistributionSummary
    probability_threshold_within_horizon: float


class PressurePolicyComparison(StrictSchema):
    current_pressure_policy_median_cycles: int
    maintained_reference_pressure_median_cycles: int
    estimated_median_cycle_difference: int


ModelFactorField = Literal["cycles_since_install", "retread_count", "tire_temperature_c"]


class ModelFactorUsage(StrictSchema):
    field: ModelFactorField
    wear_forecast: Literal["RECORDED_NOT_USED"]
    removal_demo: Literal["USED_AS_SYNTHETIC_PROXY"]


RemovalMode = Literal[
    "FOD_DAMAGE",
    "CUT_OR_EXPOSED_CORD",
    "BULGE",
    "TREAD_SEPARATION",
    "HEAT_DAMAGE",
    "FLAT_SPOT",
    "CONTAMINATION",
    "SUDDEN_PRESSURE_LOSS",
]


class SyntheticRemovalModeRisk(StrictSchema):
    mode: RemovalMode
    synthetic_probability_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    drivers: list[str] = Field(min_length=1, max_length=3)


class UnscheduledRemovalRisk(StrictSchema):
    status: Literal["SYNTHETIC_DEMONSTRATION"]
    horizon_cycles: int = Field(ge=1, le=500)
    synthetic_probability_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    modes: list[SyntheticRemovalModeRisk] = Field(min_length=8, max_length=8)
    confidence: Literal["LOW"]
    probability_interpretation: Literal["NOT_EMPIRICAL_FAILURE_PROBABILITY"]
    message: str


class SimulationConfidence(StrictSchema):
    level: Literal["LOW"]
    reason: str


class SimulationRecommendation(StrictSchema):
    attention: Literal[
        "ROUTINE_MONITORING",
        "EARLY_INSPECTION",
        "QUALIFIED_INSPECTION_REQUIRED",
    ]
    message: str


class TireSimulationResponse(StrictSchema):
    simulation_id: UUID
    profile_id: SimulationProfileId
    gear: GearValue
    random_seed: int
    approved_limits: ApprovedLimitEvaluation
    current_condition: CurrentConditionEvaluation
    wear_forecast: WearForecast
    pressure_policy_comparison: PressurePolicyComparison
    unscheduled_removal_risk: UnscheduledRemovalRisk
    model_factor_usage: list[ModelFactorUsage] = Field(min_length=3, max_length=3)
    scenario_drivers: list[str]
    recommendation: SimulationRecommendation
    confidence: SimulationConfidence
    assumptions: list[str]
    model_version: str
    disclaimer: str
