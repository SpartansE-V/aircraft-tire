"""Typed, cross-bound evidence required before model-release promotion."""

import math
from collections import Counter
from collections.abc import Sequence
from typing import Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.calibration.artifacts import artifact_sha256
from app.calibration.schemas import (
    EvidenceAwareDatetime,
    FrozenDatasetPartitionArtifact,
    FrozenPredictionArtifact,
    FrozenValidationAcceptancePolicy,
    HoldoutValidationMetrics,
    HoldoutValidationReport,
    ModelReleaseBinding,
    TreadWearRatePrediction,
)
from app.domain.governance_schemas import (
    ApproverIdentity,
    ExactTargetIdentity,
    ValidationClaim,
)
from app.domain.schemas import StrictSchema


class FrozenPromotionSchema(StrictSchema):
    """Strict immutable base for promotion artifacts."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class CalibrationAcceptanceThresholds(FrozenPromotionSchema):
    minimum_training_record_count: int = Field(ge=1)
    minimum_training_casing_count: int = Field(ge=2)
    maximum_mae_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    maximum_rmse_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    maximum_absolute_bias_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)
    maximum_p90_absolute_error_mm_per_cycle: float = Field(ge=0, allow_inf_nan=False)


class FrozenCalibrationAcceptancePolicy(FrozenPromotionSchema):
    schema_version: Literal["1.0"]
    policy_id: str = Field(min_length=1, max_length=200)
    frozen_at_utc: EvidenceAwareDatetime
    target_identity: ExactTargetIdentity
    calibrated_claim: Literal["TREAD_WEAR_RATE_POINT"]
    parameterization_id: str = Field(min_length=1, max_length=200)
    thresholds: CalibrationAcceptanceThresholds


class FrozenCalibrationPredictionArtifact(FrozenPromotionSchema):
    schema_version: Literal["1.0"]
    artifact_id: str = Field(min_length=1, max_length=200)
    created_at_utc: EvidenceAwareDatetime
    training_partition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_release: ModelReleaseBinding
    acceptance_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    predictions: tuple[TreadWearRatePrediction, ...] = Field(min_length=1)

    @field_validator("predictions", mode="before")
    @classmethod
    def normalize_predictions(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_unique_predictions(self) -> "FrozenCalibrationPredictionArtifact":
        record_ids = [prediction.record_id for prediction in self.predictions]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("calibration prediction record identifiers must be unique")
        return self


class CalibrationReportArtifact(FrozenPromotionSchema):
    """Reproducible calibration result bound to the training partition and model bytes."""

    schema_version: Literal["1.0"]
    report_id: str = Field(min_length=1, max_length=200)
    created_at_utc: EvidenceAwareDatetime
    target_identity: ExactTargetIdentity
    source_dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    split_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_partition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_release: ModelReleaseBinding
    acceptance_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    prediction_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    calibration_method_id: str = Field(min_length=1, max_length=200)
    calibration_code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    calibrated_claim: Literal["TREAD_WEAR_RATE_POINT"]
    training_record_count: int = Field(ge=1)
    training_casing_count: int = Field(ge=1)
    metrics: HoldoutValidationMetrics
    calibration_passed: bool
    blockers: tuple[str, ...]
    limitations: tuple[str, ...] = Field(min_length=1)

    @field_validator("blockers", "limitations", mode="before")
    @classmethod
    def normalize_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "CalibrationReportArtifact":
        if self.calibration_passed and self.blockers:
            raise ValueError("a passing calibration report cannot contain blockers")
        if not self.calibration_passed and not self.blockers:
            raise ValueError("a failed calibration report must identify at least one blocker")
        return self


class ValidationClaimDecision(FrozenPromotionSchema):
    claim: ValidationClaim
    report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    passed: bool


class ValidationAcceptanceDecisionArtifact(FrozenPromotionSchema):
    """Accountable acceptance decision over explicitly scoped validation reports."""

    schema_version: Literal["1.0"]
    decision_id: str = Field(min_length=1, max_length=200)
    decided_at_utc: EvidenceAwareDatetime
    target_identity: ExactTargetIdentity
    acceptance_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    claim_decisions: tuple[ValidationClaimDecision, ...] = Field(min_length=1)
    accepted_claims: tuple[ValidationClaim, ...] = Field(min_length=1)
    accepted: bool
    reviewer: ApproverIdentity
    acceptance_basis: str = Field(min_length=1, max_length=256)

    @field_validator("claim_decisions", "accepted_claims", mode="before")
    @classmethod
    def normalize_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_claim_decisions(self) -> "ValidationAcceptanceDecisionArtifact":
        claims = [decision.claim for decision in self.claim_decisions]
        if len(set(claims)) != len(claims):
            raise ValueError("validation claim decisions must be unique")
        if len(set(self.accepted_claims)) != len(self.accepted_claims):
            raise ValueError("accepted validation claims must be unique")
        passing_claims = {decision.claim for decision in self.claim_decisions if decision.passed}
        if set(self.accepted_claims) != passing_claims:
            raise ValueError("accepted claims must exactly match passing claim decisions")
        if self.accepted != all(decision.passed for decision in self.claim_decisions):
            raise ValueError("overall acceptance must match all claim decisions")
        return self


def calibration_bundle_issues(
    partition: FrozenDatasetPartitionArtifact,
    policy: FrozenCalibrationAcceptancePolicy,
    predictions: FrozenCalibrationPredictionArtifact,
    report: CalibrationReportArtifact,
    expected_model: ModelReleaseBinding,
) -> tuple[str, ...]:
    """Cross-check calibration semantics after every artifact passes its own schema."""

    issues: list[str] = []
    if partition.partition_role != "TRAINING":
        issues.append("CALIBRATION_PARTITION_ROLE_MISMATCH")
    if partition.target_identities != (expected_model.target_identity,):
        issues.append("CALIBRATION_PARTITION_TARGET_MISMATCH")
    if report.training_partition_sha256 != artifact_sha256(partition):
        issues.append("CALIBRATION_PARTITION_DIGEST_MISMATCH")
    if report.source_dataset_sha256 != partition.source_dataset_sha256:
        issues.append("CALIBRATION_SOURCE_DATASET_MISMATCH")
    if report.split_manifest_sha256 != partition.split_manifest_sha256:
        issues.append("CALIBRATION_SPLIT_MISMATCH")
    if report.acceptance_policy_sha256 != artifact_sha256(policy):
        issues.append("CALIBRATION_POLICY_MISMATCH")
    if predictions.training_partition_sha256 != artifact_sha256(partition):
        issues.append("CALIBRATION_PREDICTION_PARTITION_MISMATCH")
    if predictions.acceptance_policy_sha256 != artifact_sha256(policy):
        issues.append("CALIBRATION_PREDICTION_POLICY_MISMATCH")
    if predictions.model_release != expected_model:
        issues.append("CALIBRATION_PREDICTION_MODEL_MISMATCH")
    if predictions.created_at_utc < policy.frozen_at_utc:
        issues.append("CALIBRATION_PREDICTIONS_PREDATE_POLICY")
    if report.prediction_artifact_sha256 != artifact_sha256(predictions):
        issues.append("CALIBRATION_PREDICTION_DIGEST_MISMATCH")
    if report.created_at_utc < policy.frozen_at_utc:
        issues.append("CALIBRATION_PREDATES_POLICY")
    if report.created_at_utc < predictions.created_at_utc:
        issues.append("CALIBRATION_REPORT_PREDATES_PREDICTIONS")
    if (
        report.target_identity != policy.target_identity
        or report.target_identity != expected_model.target_identity
    ):
        issues.append("CALIBRATION_TARGET_MISMATCH")
    if report.model_release != expected_model:
        issues.append("CALIBRATION_MODEL_MISMATCH")
    if report.calibration_code_sha256 != expected_model.implementation_sha256:
        issues.append("CALIBRATION_CODE_MISMATCH")
    if report.calibrated_claim != policy.calibrated_claim:
        issues.append("CALIBRATION_CLAIM_MISMATCH")
    thresholds = policy.thresholds
    if report.training_record_count < thresholds.minimum_training_record_count:
        issues.append("INSUFFICIENT_CALIBRATION_RECORDS")
    if report.training_casing_count < thresholds.minimum_training_casing_count:
        issues.append("INSUFFICIENT_CALIBRATION_CASINGS")
    if report.training_record_count != len(partition.record_ids):
        issues.append("CALIBRATION_RECORD_COUNT_MISMATCH")
    if report.training_casing_count != len(partition.casing_serial_ids):
        issues.append("CALIBRATION_CASING_COUNT_MISMATCH")
    recomputed_metrics, prediction_issues = _recompute_metrics(
        partition,
        predictions.predictions,
    )
    issues.extend(f"CALIBRATION_{issue}" for issue in prediction_issues)
    if recomputed_metrics is not None and report.metrics != recomputed_metrics:
        issues.append("CALIBRATION_METRICS_MISMATCH")
    metrics = report.metrics
    if metrics.mae_mm_per_cycle > thresholds.maximum_mae_mm_per_cycle:
        issues.append("CALIBRATION_MAE_EXCEEDS_LIMIT")
    if metrics.rmse_mm_per_cycle > thresholds.maximum_rmse_mm_per_cycle:
        issues.append("CALIBRATION_RMSE_EXCEEDS_LIMIT")
    if abs(metrics.bias_mm_per_cycle) > thresholds.maximum_absolute_bias_mm_per_cycle:
        issues.append("CALIBRATION_BIAS_EXCEEDS_LIMIT")
    if metrics.p90_absolute_error_mm_per_cycle > thresholds.maximum_p90_absolute_error_mm_per_cycle:
        issues.append("CALIBRATION_P90_EXCEEDS_LIMIT")
    if not report.calibration_passed or report.blockers:
        issues.append("CALIBRATION_REPORT_DID_NOT_PASS")
    return tuple(dict.fromkeys(issues))


def validation_bundle_issues(
    partition: FrozenDatasetPartitionArtifact,
    policy: FrozenValidationAcceptancePolicy,
    predictions: FrozenPredictionArtifact,
    report: HoldoutValidationReport,
    decision: ValidationAcceptanceDecisionArtifact,
    expected_model: ModelReleaseBinding,
    *,
    report_sha256: str,
) -> tuple[str, ...]:
    """Cross-check one currently supported holdout claim and its review decision."""

    issues: list[str] = []
    partition_sha256 = artifact_sha256(partition)
    policy_sha256 = artifact_sha256(policy)
    if partition.partition_role != "HOLDOUT":
        issues.append("VALIDATION_PARTITION_ROLE_MISMATCH")
    if partition.target_identities != (expected_model.target_identity,):
        issues.append("VALIDATION_PARTITION_TARGET_MISMATCH")
    if report.holdout_partition_sha256 != partition_sha256:
        issues.append("VALIDATION_PARTITION_DIGEST_MISMATCH")
    if report.dataset_sha256 != partition.source_dataset_sha256:
        issues.append("VALIDATION_SOURCE_DATASET_MISMATCH")
    if report.split_manifest_sha256 != partition.split_manifest_sha256:
        issues.append("VALIDATION_SPLIT_MISMATCH")
    if report.acceptance_policy_sha256 != policy_sha256:
        issues.append("VALIDATION_POLICY_MISMATCH")
    if predictions.holdout_partition_sha256 != partition_sha256:
        issues.append("VALIDATION_PREDICTION_PARTITION_MISMATCH")
    if predictions.acceptance_policy_sha256 != policy_sha256:
        issues.append("VALIDATION_PREDICTION_POLICY_MISMATCH")
    if predictions.model_release != expected_model:
        issues.append("VALIDATION_PREDICTION_MODEL_MISMATCH")
    if predictions.created_at_utc < policy.frozen_at_utc:
        issues.append("VALIDATION_PREDICTIONS_PREDATE_POLICY")
    if report.prediction_artifact_sha256 != artifact_sha256(predictions):
        issues.append("VALIDATION_PREDICTION_DIGEST_MISMATCH")
    if report.acceptance_policy_id != policy.policy_id:
        issues.append("VALIDATION_POLICY_ID_MISMATCH")
    if report.acceptance_thresholds != policy.acceptance_thresholds:
        issues.append("VALIDATION_THRESHOLDS_MISMATCH")
    if (
        report.target_identity != policy.target_identity
        or report.target_identity != expected_model.target_identity
    ):
        issues.append("VALIDATION_TARGET_MISMATCH")
    if report.model_release != expected_model:
        issues.append("VALIDATION_MODEL_MISMATCH")
    if not report.validation_passed or report.blockers or report.metrics is None:
        issues.append("VALIDATION_REPORT_DID_NOT_PASS")
    if report.record_count != len(partition.record_ids):
        issues.append("VALIDATION_RECORD_COUNT_MISMATCH")
    if report.unique_casing_count != len(partition.casing_serial_ids):
        issues.append("VALIDATION_CASING_COUNT_MISMATCH")
    thresholds = policy.acceptance_thresholds
    if report.record_count < thresholds.minimum_record_count:
        issues.append("INSUFFICIENT_VALIDATION_RECORDS")
    if report.unique_casing_count < thresholds.minimum_casing_count:
        issues.append("INSUFFICIENT_VALIDATION_CASINGS")
    if report.metrics is not None:
        metrics = report.metrics
        if metrics.mae_mm_per_cycle > thresholds.maximum_mae_mm_per_cycle:
            issues.append("VALIDATION_MAE_EXCEEDS_LIMIT")
        if metrics.rmse_mm_per_cycle > thresholds.maximum_rmse_mm_per_cycle:
            issues.append("VALIDATION_RMSE_EXCEEDS_LIMIT")
        if abs(metrics.bias_mm_per_cycle) > thresholds.maximum_absolute_bias_mm_per_cycle:
            issues.append("VALIDATION_BIAS_EXCEEDS_LIMIT")
        if (
            metrics.p90_absolute_error_mm_per_cycle
            > thresholds.maximum_p90_absolute_error_mm_per_cycle
        ):
            issues.append("VALIDATION_P90_EXCEEDS_LIMIT")
    recomputed_metrics, prediction_issues = _recompute_metrics(
        partition,
        predictions.predictions,
    )
    issues.extend(f"VALIDATION_{issue}" for issue in prediction_issues)
    if recomputed_metrics is not None and report.metrics != recomputed_metrics:
        issues.append("VALIDATION_METRICS_MISMATCH")
    if decision.target_identity != expected_model.target_identity:
        issues.append("VALIDATION_DECISION_TARGET_MISMATCH")
    if decision.acceptance_policy_sha256 != policy_sha256:
        issues.append("VALIDATION_DECISION_POLICY_MISMATCH")
    if decision.decided_at_utc < policy.frozen_at_utc:
        issues.append("VALIDATION_DECISION_PREDATES_POLICY")
    if decision.decided_at_utc < predictions.created_at_utc:
        issues.append("VALIDATION_DECISION_PREDATES_PREDICTIONS")
    if not decision.accepted:
        issues.append("VALIDATION_DECISION_NOT_ACCEPTED")
    if len(decision.claim_decisions) != 1:
        issues.append("UNVERIFIED_VALIDATION_CLAIM_REPORTS")
    else:
        claim_decision = decision.claim_decisions[0]
        if claim_decision.claim != report.validated_claim:
            issues.append("VALIDATION_DECISION_CLAIM_MISMATCH")
        if claim_decision.report_sha256 != report_sha256:
            issues.append("VALIDATION_DECISION_REPORT_MISMATCH")
        if not claim_decision.passed:
            issues.append("VALIDATION_CLAIM_NOT_ACCEPTED")
    return tuple(dict.fromkeys(issues))


def _stable_mean(values: Sequence[float]) -> float:
    count = len(values)
    return math.fsum(value / count for value in values)


def _stable_rmse(errors: Sequence[float]) -> float:
    scale = max((abs(error) for error in errors), default=0.0)
    if scale == 0.0:
        return 0.0
    return scale * math.sqrt(_stable_mean([(error / scale) ** 2 for error in errors]))


def _nearest_rank_p90(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def _recompute_metrics(
    partition: FrozenDatasetPartitionArtifact,
    predictions: tuple[TreadWearRatePrediction, ...],
) -> tuple[HoldoutValidationMetrics | None, tuple[str, ...]]:
    prediction_ids = [prediction.record_id for prediction in predictions]
    issues: list[str] = []
    if any(count > 1 for count in Counter(prediction_ids).values()):
        issues.append("DUPLICATE_PREDICTIONS")
    if set(prediction_ids) != set(partition.record_ids):
        issues.append("PREDICTION_MEMBERSHIP_MISMATCH")
    if issues:
        return None, tuple(issues)
    prediction_by_id = {
        prediction.record_id: prediction.predicted_tread_wear_rate_mm_per_cycle
        for prediction in predictions
    }
    errors = [
        prediction_by_id[record.record_id] - record.tread_loss_mm / record.interval_cycles
        for record in sorted(partition.records, key=lambda item: item.record_id)
    ]
    absolute_errors = [abs(error) for error in errors]
    return (
        HoldoutValidationMetrics(
            mae_mm_per_cycle=_stable_mean(absolute_errors),
            rmse_mm_per_cycle=_stable_rmse(errors),
            bias_mm_per_cycle=_stable_mean(errors),
            p90_absolute_error_mm_per_cycle=_nearest_rank_p90(absolute_errors),
        ),
        (),
    )
