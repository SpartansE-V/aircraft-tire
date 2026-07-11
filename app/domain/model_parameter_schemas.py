"""Strict numerical contracts for checksum-verified model parameter artifacts."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.governance_schemas import ExactTargetIdentity
from app.domain.schemas import GearValue

ParameterStatus = Literal["UNCALIBRATED_PILOT_ASSUMPTIONS", "CALIBRATED"]
ParameterProfileId = Literal["pilot-main-v1", "pilot-nose-v1"]
ParameterRunwayCondition = Literal["DRY", "WET", "CONTAMINATED", "ROUGH"]

FinitePositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
FiniteNonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class ParameterSchema(BaseModel):
    """Strict, deeply composed base model for immutable release parameters."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class NumericRange(ParameterSchema):
    minimum: float = Field(allow_inf_nan=False)
    maximum: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.maximum <= self.minimum:
            raise ValueError("parameter range maximum must be greater than minimum")
        return self


class ModelInputDomain(ParameterSchema):
    touchdown_speed_ms: NumericRange
    landing_weight_kg: NumericRange
    crosswind_kt: NumericRange
    touchdown_sink_rate_ms: NumericRange
    touchdown_yaw_angle_deg: NumericRange
    taxi_distance_km: NumericRange
    average_taxi_speed_kt: NumericRange
    outside_air_temperature_c: NumericRange
    brake_temperature_c: NumericRange
    under_inflation_pct: NumericRange


class BaseSeverityParameters(ParameterSchema):
    model_version: str = Field(min_length=1, max_length=128)
    reference_touchdown_speed_ms: FinitePositiveFloat
    reference_landing_weight_kg: FinitePositiveFloat
    reference_taxi_distance_km: FinitePositiveFloat
    reference_temperature_c: float = Field(allow_inf_nan=False)
    reference_pressure_delta_pct: FinitePositiveFloat
    spin_exponent: FinitePositiveFloat
    crosswind_factor: FiniteNonNegativeFloat
    taxi_distance_factor: FiniteNonNegativeFloat
    temperature_factor: FiniteNonNegativeFloat
    pressure_base: float = Field(ge=1, allow_inf_nan=False)
    spin_weight: FiniteNonNegativeFloat
    brake_weight: FiniteNonNegativeFloat
    lateral_weight: FiniteNonNegativeFloat
    minimum_severity: FinitePositiveFloat
    severity_index_scale: int = Field(gt=0)
    moderate_threshold: int = Field(gt=0)
    high_threshold: int = Field(gt=0)
    critical_threshold: int = Field(gt=0)
    pressure_warning_threshold_pct: FiniteNonNegativeFloat

    @model_validator(mode="after")
    def validate_thresholds_and_weights(self) -> Self:
        if not self.moderate_threshold < self.high_threshold < self.critical_threshold:
            raise ValueError("severity thresholds must be strictly increasing")
        if self.spin_weight + self.brake_weight + self.lateral_weight <= 0:
            raise ValueError("at least one severity weight must be positive")
        return self


class GearParameters(ParameterSchema):
    label: str = Field(min_length=1, max_length=128)
    base_wear_rate_mm_per_cycle: FinitePositiveFloat


class GearParameterSet(ParameterSchema):
    main: GearParameters
    nose: GearParameters

    def for_gear(self, gear: GearValue) -> GearParameters:
        return self.main if gear == "main" else self.nose


class RunwayFactors(ParameterSchema):
    dry: FinitePositiveFloat = Field(alias="DRY")
    wet: FinitePositiveFloat = Field(alias="WET")
    contaminated: FinitePositiveFloat = Field(alias="CONTAMINATED")
    rough: FinitePositiveFloat = Field(alias="ROUGH")

    def for_condition(self, condition: ParameterRunwayCondition) -> float:
        return {
            "DRY": self.dry,
            "WET": self.wet,
            "CONTAMINATED": self.contaminated,
            "ROUGH": self.rough,
        }[condition]


class SimulationParameters(ParameterSchema):
    uncertainty_sigma: FiniteNonNegativeFloat
    sink_rate_reference_ms: FiniteNonNegativeFloat
    sink_rate_factor: FiniteNonNegativeFloat
    yaw_factor: FiniteNonNegativeFloat
    taxi_speed_reference_kt: FiniteNonNegativeFloat
    taxi_speed_factor: FiniteNonNegativeFloat
    brake_temperature_reference_c: FiniteNonNegativeFloat
    brake_temperature_factor: FiniteNonNegativeFloat
    heavy_braking_factor: float = Field(ge=1, allow_inf_nan=False)
    runway_factors: RunwayFactors


class SyntheticRemovalRunwayExposure(ParameterSchema):
    dry: FiniteNonNegativeFloat = Field(alias="DRY")
    wet: FiniteNonNegativeFloat = Field(alias="WET")
    contaminated: FiniteNonNegativeFloat = Field(alias="CONTAMINATED")
    rough: FiniteNonNegativeFloat = Field(alias="ROUGH")

    def for_condition(self, condition: ParameterRunwayCondition) -> float:
        return {
            "DRY": self.dry,
            "WET": self.wet,
            "CONTAMINATED": self.contaminated,
            "ROUGH": self.rough,
        }[condition]


class SyntheticRemovalHazardCoefficients(ParameterSchema):
    baseline: FiniteNonNegativeFloat
    pressure_deficit: FiniteNonNegativeFloat = 0.0
    installed_age: FiniteNonNegativeFloat = 0.0
    retread_count: FiniteNonNegativeFloat = 0.0
    tire_temperature: FiniteNonNegativeFloat = 0.0
    heavy_braking: FiniteNonNegativeFloat = 0.0
    brake_heat: FiniteNonNegativeFloat = 0.0
    taxi_exposure: FiniteNonNegativeFloat = 0.0
    runway_exposure: FiniteNonNegativeFloat = 0.0


class SyntheticRemovalModeParameters(ParameterSchema):
    fod_damage: SyntheticRemovalHazardCoefficients
    cut_or_exposed_cord: SyntheticRemovalHazardCoefficients
    bulge: SyntheticRemovalHazardCoefficients
    tread_separation: SyntheticRemovalHazardCoefficients
    heat_damage: SyntheticRemovalHazardCoefficients
    flat_spot: SyntheticRemovalHazardCoefficients
    contamination: SyntheticRemovalHazardCoefficients
    sudden_pressure_loss: SyntheticRemovalHazardCoefficients


class SyntheticRemovalParameters(ParameterSchema):
    status: Literal["SYNTHETIC_PILOT_ASSUMPTIONS"]
    retread_count_reference: FinitePositiveFloat
    tire_temperature_reference_c: float = Field(allow_inf_nan=False)
    tire_temperature_span_c: FinitePositiveFloat
    brake_temperature_reference_c: FiniteNonNegativeFloat
    brake_temperature_span_c: FinitePositiveFloat
    runway_exposure: SyntheticRemovalRunwayExposure
    modes: SyntheticRemovalModeParameters


class SimulationProfileParameters(ParameterSchema):
    profile_id: ParameterProfileId
    display_name: str = Field(min_length=1, max_length=256)
    gear: GearValue
    initial_tread_depth_mm: FinitePositiveFloat
    planning_threshold_mm: FiniteNonNegativeFloat

    @model_validator(mode="after")
    def validate_tread_range(self) -> Self:
        if self.planning_threshold_mm >= self.initial_tread_depth_mm:
            raise ValueError("planning threshold must be below initial tread depth")
        return self


class ModelParameterSet(ParameterSchema):
    """Every numerical input used by one immutable model release."""

    schema_version: Literal["1.0"]
    release_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    parameter_status: ParameterStatus
    target_identity: ExactTargetIdentity | None = None
    input_domain: ModelInputDomain
    base_severity: BaseSeverityParameters
    gear_configurations: GearParameterSet
    simulation: SimulationParameters
    synthetic_removal: SyntheticRemovalParameters
    profiles: tuple[SimulationProfileParameters, ...] = Field(min_length=1)

    @field_validator("profiles", mode="before")
    @classmethod
    def normalize_json_profiles(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_profiles(self) -> Self:
        if self.parameter_status == "CALIBRATED" and self.target_identity is None:
            raise ValueError("calibrated parameters require an exact target identity")
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("simulation profile identifiers must be unique")
        gears = [profile.gear for profile in self.profiles]
        if len(set(gears)) != len(gears):
            raise ValueError("each release may define only one profile per gear")
        return self

    def profile(self, profile_id: ParameterProfileId) -> SimulationProfileParameters:
        for profile in self.profiles:
            if profile.profile_id == profile_id:
                return profile
        raise KeyError(profile_id)
