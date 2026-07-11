"""Evidence-bound holdout validation metrics and failure-gate tests."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.calibration.artifacts import artifact_sha256
from app.calibration.dataset import freeze_dataset_partitions, freeze_dataset_split
from app.calibration.schemas import (
    FleetDatasetSnapshot,
    FleetTireInterval,
    FrozenDatasetSplitManifest,
    FrozenPredictionArtifact,
    FrozenValidationAcceptancePolicy,
    ModelReleaseBinding,
    TreadWearRatePrediction,
    ValidationAcceptanceThresholds,
)
from app.calibration.validation import evaluate_holdout_validation
from app.domain.governance_schemas import ExactTargetIdentity


def _target(**overrides: object) -> ExactTargetIdentity:
    values: dict[str, object] = {
        "aircraft_manufacturer": "Boeing",
        "aircraft_model": "737",
        "aircraft_variant": "737-800",
        "tire_manufacturer": "Bridgestone",
        "tire_part_number": "APR04450",
        "tire_size": "H44.5x16.5-21",
        "gear_position": "MAIN",
        "wheel_position": "LEFT_MAIN_INBOARD",
    }
    values.update(overrides)
    return ExactTargetIdentity.model_validate(values)


RELEASE = ModelReleaseBinding(
    release_id="b737-apr04450-model-1",
    parameters_sha256="a" * 64,
    implementation_sha256="b" * 64,
    target_identity=_target(),
)


def _record(
    record_id: str,
    casing_serial_id: str,
    *,
    cycles_at_start: int = 0,
    cycles_at_end: int = 10,
    tread_depth_start_mm: float = 10.0,
    tread_depth_end_mm: float = 9.8,
    target_identity: ExactTargetIdentity | None = None,
) -> FleetTireInterval:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=cycles_at_start)
    end = start + timedelta(days=1)
    return FleetTireInterval(
        record_id=record_id,
        source_system="operator-maintenance-export",
        source_extract_id="extract-2026-01",
        operator_id="operator-a",
        aircraft_tail_id="tail-1",
        target_identity=target_identity or _target(),
        tire_asset_id=f"installation-{record_id}",
        casing_serial_id=casing_serial_id,
        construction="RADIAL",
        retread_count=0,
        interval_start_utc=start,
        interval_end_utc=end,
        cycles_at_start=cycles_at_start,
        cycles_at_end=cycles_at_end,
        tread_depth_start_mm=tread_depth_start_mm,
        tread_depth_end_mm=tread_depth_end_mm,
        measurement_gauge_id="gauge-1",
        gauge_calibration_due_utc=end + timedelta(days=30),
        cold_pressure_mean_psi=230.0,
        reference_cold_pressure_psi=230.0,
        tire_temperature_mean_c=25.0,
        landing_weight_mean_kg=65_000.0,
        touchdown_ground_speed_mean_ms=69.0,
        touchdown_sink_rate_mean_ms=1.2,
        touchdown_yaw_angle_mean_deg=2.0,
        crosswind_mean_kt=5.0,
        taxi_distance_mean_km=3.0,
        average_taxi_speed_kt=15.0,
        outside_air_temperature_mean_c=25.0,
        brake_temperature_mean_c=200.0,
        heavy_braking_events=1,
        wet_cycles=0,
        contaminated_cycles=0,
        rough_runway_cycles=0,
        known_defect_at_end=False,
        removal_reason="IN_SERVICE",
    )


def _records(
    *,
    target_identity: ExactTargetIdentity | None = None,
) -> list[FleetTireInterval]:
    return [
        _record(
            f"record-{index}",
            f"casing-{index}",
            target_identity=target_identity,
        )
        for index in range(1, 5)
    ]


def _snapshot(records: list[FleetTireInterval]) -> FleetDatasetSnapshot:
    content = b"".join(f"{record.model_dump_json()}\n".encode() for record in records)
    return FleetDatasetSnapshot(
        dataset_sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        records=tuple(records),
    )


def _split(snapshot: FleetDatasetSnapshot) -> FrozenDatasetSplitManifest:
    return freeze_dataset_split(
        snapshot,
        split_id="b737-apr04450-holdout-1",
        split_seed="validation-seed-v1",
        validation_fraction=0.49,
    )


def _policy(
    *,
    minimum_record_count: int = 2,
    minimum_casing_count: int = 2,
    limit: float = 0.01,
) -> FrozenValidationAcceptancePolicy:
    return FrozenValidationAcceptancePolicy(
        schema_version="1.0",
        policy_id="b737-apr04450-acceptance-v1",
        frozen_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        target_identity=_target(),
        acceptance_thresholds=ValidationAcceptanceThresholds(
            minimum_record_count=minimum_record_count,
            minimum_casing_count=minimum_casing_count,
            maximum_mae_mm_per_cycle=limit,
            maximum_rmse_mm_per_cycle=limit,
            maximum_absolute_bias_mm_per_cycle=limit,
            maximum_p90_absolute_error_mm_per_cycle=limit,
        ),
    )


def _prediction(record_id: str, rate: float) -> TreadWearRatePrediction:
    return TreadWearRatePrediction(
        record_id=record_id,
        predicted_tread_wear_rate_mm_per_cycle=rate,
    )


def _artifact(
    snapshot: FleetDatasetSnapshot,
    split: FrozenDatasetSplitManifest,
    policy: FrozenValidationAcceptancePolicy,
    predictions: list[TreadWearRatePrediction],
    *,
    release: ModelReleaseBinding = RELEASE,
    split_sha256: str | None = None,
    holdout_partition_sha256: str | None = None,
    policy_sha256: str | None = None,
    created_at_utc: datetime | None = None,
) -> FrozenPredictionArtifact:
    return FrozenPredictionArtifact(
        schema_version="1.0",
        artifact_id="holdout-predictions-1",
        created_at_utc=created_at_utc or datetime(2026, 1, 2, tzinfo=UTC),
        split_manifest_sha256=split_sha256 or artifact_sha256(split),
        holdout_partition_sha256=holdout_partition_sha256
        or artifact_sha256(freeze_dataset_partitions(snapshot, split).holdout),
        model_release=release,
        acceptance_policy_sha256=policy_sha256 or artifact_sha256(policy),
        predictions=tuple(predictions),
    )


def _holdout_predictions(
    split: FrozenDatasetSplitManifest,
    rate: float,
) -> list[TreadWearRatePrediction]:
    return [_prediction(record_id, rate) for record_id in split.validation_record_ids]


def test_matching_holdout_passes_and_records_all_evidence_digests() -> None:
    snapshot = _snapshot(_records())
    split = _split(snapshot)
    policy = _policy()
    artifact = _artifact(snapshot, split, policy, _holdout_predictions(split, 0.02))

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.validation_passed is True
    assert report.blockers == []
    assert report.record_count == 2
    assert report.unique_casing_count == 2
    assert report.dataset_sha256 == snapshot.dataset_sha256
    assert report.split_manifest_sha256 == artifact_sha256(split)
    assert report.prediction_artifact_sha256 == artifact_sha256(artifact)
    assert report.model_release == RELEASE
    assert report.acceptance_policy_sha256 == artifact_sha256(policy)
    assert report.metrics is not None
    assert report.metrics.mae_mm_per_cycle < 1e-15
    assert report.metrics.rmse_mm_per_cycle < 1e-15
    assert abs(report.metrics.bias_mm_per_cycle) < 1e-15
    assert report.metrics.p90_absolute_error_mm_per_cycle < 1e-15


def test_all_metric_threshold_failures_are_reported() -> None:
    snapshot = _snapshot(_records())
    split = _split(snapshot)
    policy = _policy(limit=0.05)
    artifact = _artifact(snapshot, split, policy, _holdout_predictions(split, 0.12))

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.validation_passed is False
    assert report.blockers == [
        "MAE_EXCEEDS_LIMIT",
        "RMSE_EXCEEDS_LIMIT",
        "ABSOLUTE_BIAS_EXCEEDS_LIMIT",
        "P90_ABSOLUTE_ERROR_EXCEEDS_LIMIT",
    ]
    assert report.metrics is not None
    assert abs(report.metrics.bias_mm_per_cycle - 0.1) < 1e-15


def test_target_mismatch_withholds_metrics() -> None:
    snapshot = _snapshot(_records(target_identity=_target(tire_part_number="NOT-THE-TARGET")))
    split = _split(snapshot)
    policy = _policy()
    artifact = _artifact(snapshot, split, policy, _holdout_predictions(split, 0.02))

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.validation_passed is False
    assert report.blockers == ["TARGET_IDENTITY_MISMATCH"]
    assert report.metrics is None


def test_missing_prediction_withholds_metrics() -> None:
    snapshot = _snapshot(_records())
    split = _split(snapshot)
    policy = _policy()
    artifact = _artifact(
        snapshot,
        split,
        policy,
        [_prediction(split.validation_record_ids[0], 0.02)],
    )

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.validation_passed is False
    assert report.blockers == ["MISSING_PREDICTIONS"]
    assert report.metrics is None


def test_multiple_intervals_for_one_casing_count_as_one_holdout_casing() -> None:
    initial_snapshot = _snapshot(_records())
    initial_split = _split(initial_snapshot)
    validation_casing = initial_split.validation_casing_serial_ids[0]
    records = _records()
    records.append(
        _record(
            "record-extra",
            validation_casing,
            cycles_at_start=10,
            cycles_at_end=20,
        )
    )
    snapshot = _snapshot(records)
    split = _split(snapshot)
    policy = _policy(minimum_casing_count=3)
    artifact = _artifact(snapshot, split, policy, _holdout_predictions(split, 0.02))

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.record_count == 3
    assert report.unique_casing_count == 2
    assert report.blockers == ["INSUFFICIENT_HOLDOUT_CASINGS"]
    assert report.metrics is not None


def test_split_bound_to_another_dataset_withholds_metrics() -> None:
    first = _snapshot(_records())
    split = _split(first)
    second_records = _records()
    second_records[0] = _record("replacement-record", "replacement-casing")
    second = _snapshot(second_records)
    policy = _policy()
    artifact = _artifact(first, split, policy, _holdout_predictions(split, 0.02))

    report = evaluate_holdout_validation(second, split, artifact, policy, RELEASE)

    assert "SPLIT_DATASET_MISMATCH" in report.blockers
    assert report.metrics is None


def test_prediction_must_match_split_release_and_predeclared_policy() -> None:
    snapshot = _snapshot(_records())
    split = _split(snapshot)
    policy = _policy()
    other_release = ModelReleaseBinding(
        release_id="another-release",
        parameters_sha256="c" * 64,
        implementation_sha256="d" * 64,
        target_identity=_target(),
    )
    artifact = _artifact(
        snapshot,
        split,
        policy,
        _holdout_predictions(split, 0.02),
        release=other_release,
        split_sha256="c" * 64,
        policy_sha256="d" * 64,
        created_at_utc=datetime(2025, 12, 31, tzinfo=UTC),
    )

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.blockers == [
        "PREDICTION_SPLIT_MISMATCH",
        "PREDICTION_RELEASE_MISMATCH",
        "PREDICTION_ACCEPTANCE_POLICY_MISMATCH",
    ]
    assert report.metrics is None


def test_duplicate_and_unexpected_prediction_ids_break_one_to_one_contract() -> None:
    snapshot = _snapshot(_records())
    split = _split(snapshot)
    policy = _policy()
    first_id = split.validation_record_ids[0]
    artifact = _artifact(
        snapshot,
        split,
        policy,
        [
            _prediction(first_id, 0.02),
            _prediction(first_id, 0.02),
            _prediction("record-extra", 0.02),
        ],
    )

    report = evaluate_holdout_validation(snapshot, split, artifact, policy, RELEASE)

    assert report.blockers == [
        "DUPLICATE_PREDICTION_RECORD_IDS",
        "MISSING_PREDICTIONS",
        "UNEXPECTED_PREDICTIONS",
    ]
    assert report.metrics is None


def test_acceptance_policy_is_explicit_aware_finite_and_nonnegative() -> None:
    with pytest.raises(ValidationError, match="maximum_p90_absolute_error_mm_per_cycle"):
        ValidationAcceptanceThresholds(
            minimum_record_count=2,
            minimum_casing_count=2,
            maximum_mae_mm_per_cycle=0.01,
            maximum_rmse_mm_per_cycle=0.01,
            maximum_absolute_bias_mm_per_cycle=0.01,
        )

    with pytest.raises(ValidationError, match="timezone"):
        FrozenValidationAcceptancePolicy(
            schema_version="1.0",
            policy_id="policy-1",
            frozen_at_utc=datetime(2026, 1, 1),
            target_identity=_target(),
            acceptance_thresholds=_policy().acceptance_thresholds,
        )

    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        _prediction("record-1", -0.01)

    with pytest.raises(ValidationError, match="finite number"):
        _policy(limit=float("inf"))
