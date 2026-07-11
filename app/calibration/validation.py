"""Evidence-bound holdout evaluation for aircraft-tire tread-wear predictions."""

import math
from collections import Counter
from collections.abc import Sequence

from app.calibration.artifacts import artifact_sha256
from app.calibration.dataset import dataset_split_issues, freeze_dataset_partitions
from app.calibration.schemas import (
    FleetDatasetSnapshot,
    FleetTireInterval,
    FrozenDatasetSplitManifest,
    FrozenPredictionArtifact,
    FrozenValidationAcceptancePolicy,
    HoldoutValidationMetrics,
    HoldoutValidationReport,
    ModelReleaseBinding,
    ValidationBlocker,
)
from app.domain.governance_schemas import ExactTargetIdentity


def _has_exact_target(record: FleetTireInterval, target: ExactTargetIdentity) -> bool:
    return record.target_identity == target


def _stable_mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("cannot calculate a mean for an empty sequence")
    count = len(values)
    return math.fsum(value / count for value in values)


def _stable_rmse(errors: Sequence[float]) -> float:
    scale = max((abs(error) for error in errors), default=0.0)
    if scale == 0.0:
        return 0.0
    normalized_mean_square = _stable_mean([(error / scale) ** 2 for error in errors])
    return scale * math.sqrt(normalized_mean_square)


def _nearest_rank_p90(values: Sequence[float]) -> float:
    """Return the deterministic nearest-rank 90th percentile."""

    if not values:
        raise ValueError("cannot calculate a percentile for an empty sequence")
    ordered = sorted(values)
    rank = math.ceil(0.9 * len(ordered))
    return ordered[rank - 1]


def evaluate_holdout_validation(
    snapshot: FleetDatasetSnapshot,
    split_manifest: FrozenDatasetSplitManifest,
    prediction_artifact: FrozenPredictionArtifact,
    acceptance_policy: FrozenValidationAcceptancePolicy,
    model_release: ModelReleaseBinding,
) -> HoldoutValidationReport:
    """Evaluate only the holdout membership frozen for the bound dataset.

    The report records canonical digests for the split, predictions, release
    manifest, and acceptance policy. Metrics are withheld when any binding,
    identity, membership, or one-to-one prediction check fails.
    """

    split_sha256 = artifact_sha256(split_manifest)
    acceptance_policy_sha256 = artifact_sha256(acceptance_policy)
    prediction_artifact_sha256 = artifact_sha256(prediction_artifact)
    split_issues = dataset_split_issues(snapshot, split_manifest)
    blockers: list[ValidationBlocker] = list(split_issues)
    holdout_partition_sha256: str | None = None
    if not split_issues:
        partitions = freeze_dataset_partitions(snapshot, split_manifest)
        holdout_partition_sha256 = artifact_sha256(partitions.holdout)

    if prediction_artifact.split_manifest_sha256 != split_sha256:
        blockers.append("PREDICTION_SPLIT_MISMATCH")
    if (
        holdout_partition_sha256 is not None
        and prediction_artifact.holdout_partition_sha256 != holdout_partition_sha256
    ):
        blockers.append("PREDICTION_HOLDOUT_PARTITION_MISMATCH")
    if prediction_artifact.model_release != model_release:
        blockers.append("PREDICTION_RELEASE_MISMATCH")
    if (
        prediction_artifact.acceptance_policy_sha256 != acceptance_policy_sha256
        or prediction_artifact.created_at_utc < acceptance_policy.frozen_at_utc
    ):
        blockers.append("PREDICTION_ACCEPTANCE_POLICY_MISMATCH")
    if model_release.target_identity != acceptance_policy.target_identity:
        blockers.append("RELEASE_TARGET_IDENTITY_MISMATCH")

    record_by_id = {record.record_id: record for record in snapshot.records}
    records = [
        record_by_id[record_id]
        for record_id in split_manifest.validation_record_ids
        if record_id in record_by_id
    ]
    predictions = prediction_artifact.predictions
    target_identity = acceptance_policy.target_identity
    acceptance_thresholds = acceptance_policy.acceptance_thresholds
    record_ids = [record.record_id for record in records]
    prediction_ids = [prediction.record_id for prediction in predictions]
    record_id_set = set(record_ids)
    prediction_id_set = set(prediction_ids)
    holdout_casing_ids = {record.casing_serial_id for record in records}

    if not records:
        blockers.append("EMPTY_HOLDOUT")
    if any(count > 1 for count in Counter(record_ids).values()):
        blockers.append("DUPLICATE_HOLDOUT_RECORD_IDS")
    if any(count > 1 for count in Counter(prediction_ids).values()):
        blockers.append("DUPLICATE_PREDICTION_RECORD_IDS")
    if record_id_set - prediction_id_set:
        blockers.append("MISSING_PREDICTIONS")
    if prediction_id_set - record_id_set:
        blockers.append("UNEXPECTED_PREDICTIONS")
    if any(not _has_exact_target(record, target_identity) for record in records):
        blockers.append("TARGET_IDENTITY_MISMATCH")
    if len(records) < acceptance_thresholds.minimum_record_count:
        blockers.append("INSUFFICIENT_HOLDOUT_RECORDS")
    if len(holdout_casing_ids) < acceptance_thresholds.minimum_casing_count:
        blockers.append("INSUFFICIENT_HOLDOUT_CASINGS")

    structural_blockers = {
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
    }
    metrics: HoldoutValidationMetrics | None = None
    if not structural_blockers.intersection(blockers):
        prediction_by_record_id = {
            prediction.record_id: prediction.predicted_tread_wear_rate_mm_per_cycle
            for prediction in predictions
        }
        ordered_records = sorted(records, key=lambda record: record.record_id)
        errors = [
            prediction_by_record_id[record.record_id]
            - (record.tread_loss_mm / record.interval_cycles)
            for record in ordered_records
        ]
        absolute_errors = [abs(error) for error in errors]
        metrics = HoldoutValidationMetrics(
            mae_mm_per_cycle=_stable_mean(absolute_errors),
            rmse_mm_per_cycle=_stable_rmse(errors),
            bias_mm_per_cycle=_stable_mean(errors),
            p90_absolute_error_mm_per_cycle=_nearest_rank_p90(absolute_errors),
        )
        if metrics.mae_mm_per_cycle > acceptance_thresholds.maximum_mae_mm_per_cycle:
            blockers.append("MAE_EXCEEDS_LIMIT")
        if metrics.rmse_mm_per_cycle > acceptance_thresholds.maximum_rmse_mm_per_cycle:
            blockers.append("RMSE_EXCEEDS_LIMIT")
        if (
            abs(metrics.bias_mm_per_cycle)
            > acceptance_thresholds.maximum_absolute_bias_mm_per_cycle
        ):
            blockers.append("ABSOLUTE_BIAS_EXCEEDS_LIMIT")
        if (
            metrics.p90_absolute_error_mm_per_cycle
            > acceptance_thresholds.maximum_p90_absolute_error_mm_per_cycle
        ):
            blockers.append("P90_ABSOLUTE_ERROR_EXCEEDS_LIMIT")

    return HoldoutValidationReport(
        schema_version="1.0",
        report_id=f"{prediction_artifact.artifact_id}-evaluation",
        dataset_sha256=snapshot.dataset_sha256,
        split_manifest_sha256=split_sha256,
        holdout_partition_sha256=holdout_partition_sha256,
        prediction_artifact_sha256=prediction_artifact_sha256,
        model_release=model_release,
        acceptance_policy_sha256=acceptance_policy_sha256,
        acceptance_policy_id=acceptance_policy.policy_id,
        target_identity=target_identity,
        validated_claim="TREAD_WEAR_RATE_POINT",
        acceptance_thresholds=acceptance_thresholds,
        record_count=len(records),
        unique_casing_count=len(holdout_casing_ids),
        metrics=metrics,
        validation_passed=not blockers,
        blockers=blockers,
    )
