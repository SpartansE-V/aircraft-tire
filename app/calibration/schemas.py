"""Strict schemas for tire-level fleet degradation and evidence artifacts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.domain.governance_schemas import ExactTargetIdentity
from app.domain.schemas import StrictSchema

TireConstruction = Literal["RADIAL", "BIAS"]
DatasetPartitionRole = Literal["TRAINING", "HOLDOUT"]
RemovalReason = Literal[
    "IN_SERVICE",
    "WEAR_LIMIT",
    "PRESSURE_LOSS",
    "CUT_OR_FOD",
    "FLAT_SPOT",
    "HEAT_DAMAGE",
    "SEPARATION",
    "SCHEDULED_MAINTENANCE",
    "OTHER",
    "UNKNOWN",
]
ValidationBlocker = Literal[
    "SPLIT_DATASET_MISMATCH",
    "INVALID_SPLIT_MEMBERSHIP",
    "PREDICTION_SPLIT_MISMATCH",
    "PREDICTION_HOLDOUT_PARTITION_MISMATCH",
    "PREDICTION_RELEASE_MISMATCH",
    "PREDICTION_ACCEPTANCE_POLICY_MISMATCH",
    "RELEASE_TARGET_IDENTITY_MISMATCH",
    "EMPTY_HOLDOUT",
    "DUPLICATE_HOLDOUT_RECORD_IDS",
    "DUPLICATE_PREDICTION_RECORD_IDS",
    "MISSING_PREDICTIONS",
    "UNEXPECTED_PREDICTIONS",
    "TARGET_IDENTITY_MISMATCH",
    "INSUFFICIENT_HOLDOUT_RECORDS",
    "INSUFFICIENT_HOLDOUT_CASINGS",
    "MAE_EXCEEDS_LIMIT",
    "RMSE_EXCEEDS_LIMIT",
    "ABSOLUTE_BIAS_EXCEEDS_LIMIT",
    "P90_ABSOLUTE_ERROR_EXCEEDS_LIMIT",
]


def _parse_rfc3339_datetime(value: object) -> object:
    """Parse the canonical JSON timestamp form before strict aware-datetime validation."""

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


EvidenceAwareDatetime = Annotated[
    AwareDatetime,
    BeforeValidator(_parse_rfc3339_datetime),
]


class FleetTireInterval(StrictSchema):
    """One measured tread-change interval for a uniquely identified tire casing."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    record_id: str = Field(min_length=1, max_length=200)
    source_system: str = Field(min_length=1, max_length=200)
    source_extract_id: str = Field(min_length=1, max_length=200)
    operator_id: str = Field(min_length=1, max_length=200)
    aircraft_tail_id: str = Field(min_length=1, max_length=200)
    target_identity: ExactTargetIdentity
    tire_asset_id: str = Field(min_length=1, max_length=200)
    casing_serial_id: str = Field(min_length=1, max_length=200)
    construction: TireConstruction
    retread_count: int = Field(ge=0, le=20)
    interval_start_utc: EvidenceAwareDatetime
    interval_end_utc: EvidenceAwareDatetime
    cycles_at_start: int = Field(ge=0)
    cycles_at_end: int = Field(gt=0)
    tread_depth_start_mm: float = Field(gt=0, le=30, allow_inf_nan=False)
    tread_depth_end_mm: float = Field(ge=0, le=30, allow_inf_nan=False)
    measurement_gauge_id: str = Field(min_length=1, max_length=200)
    gauge_calibration_due_utc: EvidenceAwareDatetime
    cold_pressure_mean_psi: float | None = Field(default=None, gt=0, le=500)
    reference_cold_pressure_psi: float | None = Field(default=None, gt=0, le=500)
    tire_temperature_mean_c: float | None = Field(default=None, ge=-60, le=150)
    landing_weight_mean_kg: float | None = Field(default=None, gt=0, le=1_000_000)
    touchdown_ground_speed_mean_ms: float | None = Field(default=None, ge=0, le=150)
    touchdown_sink_rate_mean_ms: float | None = Field(default=None, ge=0, le=10)
    touchdown_yaw_angle_mean_deg: float | None = Field(default=None, ge=0, le=45)
    crosswind_mean_kt: float | None = Field(default=None, ge=0, le=100)
    taxi_distance_mean_km: float | None = Field(default=None, ge=0, le=100)
    average_taxi_speed_kt: float | None = Field(default=None, ge=0, le=100)
    outside_air_temperature_mean_c: float | None = Field(default=None, ge=-100, le=100)
    brake_temperature_mean_c: float | None = Field(default=None, ge=-100, le=1_500)
    heavy_braking_events: int | None = Field(default=None, ge=0)
    wet_cycles: int | None = Field(default=None, ge=0)
    contaminated_cycles: int | None = Field(default=None, ge=0)
    rough_runway_cycles: int | None = Field(default=None, ge=0)
    known_defect_at_end: bool
    removal_reason: RemovalReason

    @model_validator(mode="after")
    def validate_interval(self) -> "FleetTireInterval":
        if self.interval_end_utc <= self.interval_start_utc:
            raise ValueError("interval_end_utc must be after interval_start_utc")
        if self.cycles_at_end <= self.cycles_at_start:
            raise ValueError("cycles_at_end must be greater than cycles_at_start")
        if self.gauge_calibration_due_utc < self.interval_end_utc:
            raise ValueError("measurement gauge calibration must cover the interval end")
        if self.tread_depth_end_mm > self.tread_depth_start_mm:
            raise ValueError("tread_depth_end_mm cannot exceed tread_depth_start_mm")
        for field_name in (
            "heavy_braking_events",
            "wet_cycles",
            "contaminated_cycles",
            "rough_runway_cycles",
        ):
            exposure_count = getattr(self, field_name)
            if exposure_count is not None and exposure_count > self.interval_cycles:
                raise ValueError(f"{field_name} cannot exceed interval_cycles")
        return self

    @property
    def interval_cycles(self) -> int:
        return self.cycles_at_end - self.cycles_at_start

    @property
    def tread_loss_mm(self) -> float:
        return self.tread_depth_start_mm - self.tread_depth_end_mm


class CalibrationReadinessPolicy(StrictSchema):
    """Project governance minima; these do not prove statistical adequacy."""

    minimum_intervals: int = Field(default=1_000, ge=1)
    minimum_casings: int = Field(default=100, ge=2)
    minimum_aircraft: int = Field(default=10, ge=2)
    minimum_wear_limit_removals: int = Field(default=20, ge=1)
    validation_fraction: float = Field(default=0.2, gt=0, lt=0.5)


class CalibrationReadinessReport(StrictSchema):
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    record_count: int
    unique_tire_assets: int
    unique_casings: int
    unique_aircraft: int
    target_identities: tuple[ExactTargetIdentity, ...]
    wear_limit_removals: int
    training_casings: int
    validation_casings: int
    split_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_partition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    holdout_partition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    missing_feature_counts: dict[str, int]
    ready_for_calibration: bool
    blockers: list[str]


class FleetDatasetSnapshot(StrictSchema):
    """Rows parsed from, and SHA-256 hashed over, one in-memory byte snapshot."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(ge=1)
    records: tuple[FleetTireInterval, ...] = Field(min_length=1)

    @field_validator("records", mode="before")
    @classmethod
    def normalize_records(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class FrozenDatasetSplitManifest(StrictSchema):
    """Explicit casing/record membership for one immutable dataset digest."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    split_id: str = Field(min_length=1, max_length=200)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    algorithm: Literal["SHA256_CASING_SERIAL_V1"]
    split_seed: str = Field(min_length=1, max_length=200)
    validation_fraction: float = Field(gt=0, lt=0.5, allow_inf_nan=False)
    training_casing_serial_ids: tuple[str, ...] = Field(min_length=1)
    validation_casing_serial_ids: tuple[str, ...] = Field(min_length=1)
    training_record_ids: tuple[str, ...] = Field(min_length=1)
    validation_record_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "training_casing_serial_ids",
        "validation_casing_serial_ids",
        "training_record_ids",
        "validation_record_ids",
        mode="before",
    )
    @classmethod
    def normalize_membership(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_membership_sets(self) -> "FrozenDatasetSplitManifest":
        collections = (
            self.training_casing_serial_ids,
            self.validation_casing_serial_ids,
            self.training_record_ids,
            self.validation_record_ids,
        )
        if any(len(set(values)) != len(values) for values in collections):
            raise ValueError("split membership identifiers must be unique")
        if set(self.training_casing_serial_ids).intersection(self.validation_casing_serial_ids):
            raise ValueError("a casing cannot belong to both training and validation")
        if set(self.training_record_ids).intersection(self.validation_record_ids):
            raise ValueError("a record cannot belong to both training and validation")
        return self


class FrozenDatasetPartitionArtifact(StrictSchema):
    """One deterministic partition bound to a source snapshot and frozen split."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    partition_id: str = Field(min_length=1, max_length=220)
    partition_role: DatasetPartitionRole
    source_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    split_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_identities: tuple[ExactTargetIdentity, ...] = Field(min_length=1)
    casing_serial_ids: tuple[str, ...] = Field(min_length=1)
    record_ids: tuple[str, ...] = Field(min_length=1)
    records: tuple[FleetTireInterval, ...] = Field(min_length=1)

    @field_validator(
        "target_identities",
        "casing_serial_ids",
        "record_ids",
        "records",
        mode="before",
    )
    @classmethod
    def normalize_membership(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_unique_membership(self) -> "FrozenDatasetPartitionArtifact":
        if len(set(self.target_identities)) != len(self.target_identities):
            raise ValueError("partition target identities must be unique")
        if len(set(self.casing_serial_ids)) != len(self.casing_serial_ids):
            raise ValueError("partition casing identifiers must be unique")
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError("partition record identifiers must be unique")
        if tuple(sorted(record.record_id for record in self.records)) != self.record_ids:
            raise ValueError("partition record identifiers must match embedded records")
        if tuple(sorted({record.casing_serial_id for record in self.records})) != (
            self.casing_serial_ids
        ):
            raise ValueError("partition casing identifiers must match embedded records")
        embedded_targets = tuple(
            sorted(
                {record.target_identity for record in self.records},
                key=lambda identity: identity.model_dump_json(),
            )
        )
        if embedded_targets != self.target_identities:
            raise ValueError("partition target identities must match embedded records")
        return self


class FrozenDatasetPartitions(StrictSchema):
    """The complete training/holdout partition pair for one frozen split."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    training: FrozenDatasetPartitionArtifact
    holdout: FrozenDatasetPartitionArtifact

    @model_validator(mode="after")
    def validate_partition_pair(self) -> "FrozenDatasetPartitions":
        if self.training.partition_role != "TRAINING":
            raise ValueError("training partition must have the TRAINING role")
        if self.holdout.partition_role != "HOLDOUT":
            raise ValueError("holdout partition must have the HOLDOUT role")
        bindings = {
            (
                partition.source_dataset_sha256,
                partition.split_manifest_sha256,
            )
            for partition in (self.training, self.holdout)
        }
        if len(bindings) != 1:
            raise ValueError("training and holdout partitions must share source/split bindings")
        if set(self.training.casing_serial_ids).intersection(self.holdout.casing_serial_ids):
            raise ValueError("training and holdout partitions cannot share a casing")
        if set(self.training.record_ids).intersection(self.holdout.record_ids):
            raise ValueError("training and holdout partitions cannot share a record")
        return self


class ValidationAcceptanceThresholds(StrictSchema):
    """Acceptance limits that must be supplied before holdout evaluation."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    minimum_record_count: int = Field(ge=1)
    minimum_casing_count: int = Field(ge=1)
    maximum_mae_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    maximum_rmse_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    maximum_absolute_bias_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    maximum_p90_absolute_error_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)


class FrozenValidationAcceptancePolicy(StrictSchema):
    """Target and thresholds frozen before holdout predictions are evaluated."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    policy_id: str = Field(min_length=1, max_length=200)
    frozen_at_utc: EvidenceAwareDatetime
    target_identity: ExactTargetIdentity
    acceptance_thresholds: ValidationAcceptanceThresholds


class ModelReleaseBinding(StrictSchema):
    """Exact parameter and implementation artifacts used to generate predictions."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    release_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    parameters_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    implementation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_identity: ExactTargetIdentity


class TreadWearRatePrediction(StrictSchema):
    """One immutable model output keyed to a holdout interval record."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    record_id: str = Field(min_length=1, max_length=200)
    predicted_tread_wear_rate_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)


class FrozenPredictionArtifact(StrictSchema):
    """Predictions bound to one split, release, and acceptance policy."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    artifact_id: str = Field(min_length=1, max_length=200)
    created_at_utc: EvidenceAwareDatetime
    split_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    holdout_partition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_release: ModelReleaseBinding
    acceptance_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    predictions: tuple[TreadWearRatePrediction, ...]

    @field_validator("predictions", mode="before")
    @classmethod
    def normalize_predictions(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class HoldoutValidationMetrics(StrictSchema):
    """Aggregate error metrics for an identity-matched, leakage-safe holdout."""

    mae_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    rmse_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    bias_mm_per_cycle: float = Field(allow_inf_nan=False)
    p90_absolute_error_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)


class HoldoutValidationReport(StrictSchema):
    schema_version: Literal["1.0"]
    report_id: str = Field(min_length=1, max_length=240)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    split_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    holdout_partition_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    prediction_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_release: ModelReleaseBinding
    acceptance_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    acceptance_policy_id: str = Field(min_length=1, max_length=200)
    target_identity: ExactTargetIdentity
    validated_claim: Literal["TREAD_WEAR_RATE_POINT"]
    acceptance_thresholds: ValidationAcceptanceThresholds
    record_count: int = Field(ge=0)
    unique_casing_count: int = Field(ge=0)
    metrics: HoldoutValidationMetrics | None
    validation_passed: bool
    blockers: list[ValidationBlocker]
