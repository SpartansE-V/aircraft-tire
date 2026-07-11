"""Load, freeze, and audit SHA-256-bound fleet datasets before model fitting."""

import hashlib
import math
from pathlib import Path

from app.calibration.artifacts import artifact_sha256
from app.calibration.schemas import (
    CalibrationReadinessPolicy,
    CalibrationReadinessReport,
    FleetDatasetSnapshot,
    FleetTireInterval,
    FrozenDatasetPartitionArtifact,
    FrozenDatasetPartitions,
    FrozenDatasetSplitManifest,
    ValidationBlocker,
)
from app.domain.governance_schemas import ExactTargetIdentity

MODEL_FEATURES = (
    "cold_pressure_mean_psi",
    "reference_cold_pressure_psi",
    "tire_temperature_mean_c",
    "landing_weight_mean_kg",
    "touchdown_ground_speed_mean_ms",
    "touchdown_sink_rate_mean_ms",
    "touchdown_yaw_angle_mean_deg",
    "crosswind_mean_kt",
    "taxi_distance_mean_km",
    "average_taxi_speed_kt",
    "outside_air_temperature_mean_c",
    "brake_temperature_mean_c",
    "heavy_braking_events",
    "wet_cycles",
    "contaminated_cycles",
    "rough_runway_cycles",
)


def load_fleet_dataset(
    path: Path,
    *,
    maximum_bytes: int = 100_000_000,
) -> FleetDatasetSnapshot:
    """Parse and hash the same bounded in-memory byte snapshot.

    Returning the digest together with the parsed records prevents a caller from
    auditing records from one file while attaching the digest of another file.
    """

    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive")
    if path.is_symlink() or not path.is_file():
        raise ValueError("dataset path must be a regular, non-symlink file")
    with path.open("rb") as dataset_file:
        content = dataset_file.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise ValueError("dataset exceeds the configured size limit")

    records: list[FleetTireInterval] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = FleetTireInterval.model_validate_json(raw_line)
        except ValueError as exc:
            raise ValueError(f"invalid dataset record at line {line_number}") from exc
        if record.record_id in seen_ids:
            raise ValueError(f"duplicate record_id at line {line_number}")
        seen_ids.add(record.record_id)
        records.append(record)
    if not records:
        raise ValueError("dataset contains no records")

    return FleetDatasetSnapshot(
        dataset_sha256=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
        records=tuple(records),
    )


def _validation_casings(
    casing_serial_ids: set[str],
    fraction: float,
    split_seed: str,
) -> set[str]:
    ordered = sorted(
        casing_serial_ids,
        key=lambda casing_id: hashlib.sha256(f"{split_seed}\0{casing_id}".encode()).hexdigest(),
    )
    if len(ordered) < 2:
        return set()
    count = min(
        len(ordered) - 1,
        max(1, math.floor(len(ordered) * fraction + 0.5)),
    )
    return set(ordered[:count])


def freeze_dataset_split(
    snapshot: FleetDatasetSnapshot,
    *,
    split_id: str,
    split_seed: str,
    validation_fraction: float,
) -> FrozenDatasetSplitManifest:
    """Freeze explicit whole-casing membership for one dataset digest."""

    if not 0 < validation_fraction < 0.5:
        raise ValueError("validation_fraction must be greater than 0 and less than 0.5")
    casing_serial_ids = {record.casing_serial_id for record in snapshot.records}
    validation_casings = _validation_casings(
        casing_serial_ids,
        validation_fraction,
        split_seed,
    )
    training_casings = casing_serial_ids - validation_casings
    if not training_casings or not validation_casings:
        raise ValueError("at least two distinct casings are required for a frozen split")

    return FrozenDatasetSplitManifest(
        schema_version="1.0",
        split_id=split_id,
        dataset_sha256=snapshot.dataset_sha256,
        algorithm="SHA256_CASING_SERIAL_V1",
        split_seed=split_seed,
        validation_fraction=validation_fraction,
        training_casing_serial_ids=tuple(sorted(training_casings)),
        validation_casing_serial_ids=tuple(sorted(validation_casings)),
        training_record_ids=tuple(
            sorted(
                record.record_id
                for record in snapshot.records
                if record.casing_serial_id in training_casings
            )
        ),
        validation_record_ids=tuple(
            sorted(
                record.record_id
                for record in snapshot.records
                if record.casing_serial_id in validation_casings
            )
        ),
    )


def dataset_split_issues(
    snapshot: FleetDatasetSnapshot,
    split_manifest: FrozenDatasetSplitManifest,
) -> tuple[ValidationBlocker, ...]:
    """Return fail-closed binding or membership issues for a frozen split."""

    if split_manifest.dataset_sha256 != snapshot.dataset_sha256:
        return ("SPLIT_DATASET_MISMATCH",)

    expected = freeze_dataset_split(
        snapshot,
        split_id=split_manifest.split_id,
        split_seed=split_manifest.split_seed,
        validation_fraction=split_manifest.validation_fraction,
    )
    membership_fields = (
        "training_casing_serial_ids",
        "validation_casing_serial_ids",
        "training_record_ids",
        "validation_record_ids",
    )
    if any(
        getattr(split_manifest, field) != getattr(expected, field) for field in membership_fields
    ):
        return ("INVALID_SPLIT_MEMBERSHIP",)
    return ()


def freeze_dataset_partitions(
    snapshot: FleetDatasetSnapshot,
    split_manifest: FrozenDatasetSplitManifest,
) -> FrozenDatasetPartitions:
    """Create canonical training/holdout artifacts for one verified split."""

    split_issues = dataset_split_issues(snapshot, split_manifest)
    if split_issues:
        raise ValueError(f"invalid frozen dataset split: {', '.join(split_issues)}")

    split_manifest_sha256 = artifact_sha256(split_manifest)
    record_by_id = {record.record_id: record for record in snapshot.records}

    def partition_targets(record_ids: tuple[str, ...]) -> tuple[ExactTargetIdentity, ...]:
        return tuple(
            sorted(
                {record_by_id[record_id].target_identity for record_id in record_ids},
                key=lambda identity: identity.model_dump_json(),
            )
        )

    return FrozenDatasetPartitions(
        training=FrozenDatasetPartitionArtifact(
            schema_version="1.0",
            partition_id=f"{split_manifest.split_id}-training",
            partition_role="TRAINING",
            source_dataset_sha256=snapshot.dataset_sha256,
            split_manifest_sha256=split_manifest_sha256,
            target_identities=partition_targets(split_manifest.training_record_ids),
            casing_serial_ids=split_manifest.training_casing_serial_ids,
            record_ids=split_manifest.training_record_ids,
            records=tuple(
                record_by_id[record_id] for record_id in split_manifest.training_record_ids
            ),
        ),
        holdout=FrozenDatasetPartitionArtifact(
            schema_version="1.0",
            partition_id=f"{split_manifest.split_id}-holdout",
            partition_role="HOLDOUT",
            source_dataset_sha256=snapshot.dataset_sha256,
            split_manifest_sha256=split_manifest_sha256,
            target_identities=partition_targets(split_manifest.validation_record_ids),
            casing_serial_ids=split_manifest.validation_casing_serial_ids,
            record_ids=split_manifest.validation_record_ids,
            records=tuple(
                record_by_id[record_id] for record_id in split_manifest.validation_record_ids
            ),
        ),
    )


def _longitudinal_dataset_blockers(records: tuple[FleetTireInterval, ...]) -> list[str]:
    records_by_casing: dict[str, list[FleetTireInterval]] = {}
    for record in records:
        records_by_casing.setdefault(record.casing_serial_id, []).append(record)

    blockers: list[str] = []
    if any(
        len({record.target_identity for record in casing_records}) > 1
        for casing_records in records_by_casing.values()
    ):
        blockers.append("INCONSISTENT_CASING_TARGET_IDENTITY")

    for casing_records in records_by_casing.values():
        ordered = sorted(
            casing_records,
            key=lambda record: (
                record.interval_start_utc,
                record.cycles_at_start,
                record.record_id,
            ),
        )
        if any(
            current.interval_start_utc < previous.interval_end_utc
            or current.cycles_at_start < previous.cycles_at_end
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ):
            blockers.append("OVERLAPPING_CASING_INTERVALS")
            break
    return blockers


def audit_fleet_dataset(
    snapshot: FleetDatasetSnapshot,
    split_manifest: FrozenDatasetSplitManifest,
    policy: CalibrationReadinessPolicy | None = None,
) -> CalibrationReadinessReport:
    """Audit one bound snapshot using an already-frozen whole-casing split."""

    split_issues = dataset_split_issues(snapshot, split_manifest)
    if split_issues:
        raise ValueError(f"invalid frozen dataset split: {', '.join(split_issues)}")

    active_policy = policy or CalibrationReadinessPolicy()
    if split_manifest.validation_fraction != active_policy.validation_fraction:
        raise ValueError("invalid frozen dataset split: SPLIT_POLICY_MISMATCH")
    records = snapshot.records
    partitions = freeze_dataset_partitions(snapshot, split_manifest)
    tire_assets = {record.tire_asset_id for record in records}
    casings = {record.casing_serial_id for record in records}
    aircraft = {record.aircraft_tail_id for record in records}
    target_identities = tuple(
        sorted(
            {record.target_identity for record in records},
            key=lambda identity: identity.model_dump_json(),
        )
    )
    missing = {
        feature: sum(getattr(record, feature) is None for record in records)
        for feature in MODEL_FEATURES
    }
    wear_limit_removals = sum(record.removal_reason == "WEAR_LIMIT" for record in records)
    blockers = _longitudinal_dataset_blockers(records)
    if len(target_identities) != 1:
        blockers.append("MIXED_TARGET_IDENTITIES")
    if len(records) < active_policy.minimum_intervals:
        blockers.append("INSUFFICIENT_INTERVALS")
    if len(casings) < active_policy.minimum_casings:
        blockers.append("INSUFFICIENT_CASINGS")
    if len(aircraft) < active_policy.minimum_aircraft:
        blockers.append("INSUFFICIENT_AIRCRAFT")
    if wear_limit_removals < active_policy.minimum_wear_limit_removals:
        blockers.append("INSUFFICIENT_WEAR_LIMIT_OUTCOMES")
    if any(missing.values()):
        blockers.append("MISSING_MODEL_FEATURES")

    return CalibrationReadinessReport(
        dataset_sha256=snapshot.dataset_sha256,
        record_count=len(records),
        unique_tire_assets=len(tire_assets),
        unique_casings=len(casings),
        unique_aircraft=len(aircraft),
        target_identities=target_identities,
        wear_limit_removals=wear_limit_removals,
        training_casings=len(split_manifest.training_casing_serial_ids),
        validation_casings=len(split_manifest.validation_casing_serial_ids),
        split_manifest_sha256=artifact_sha256(split_manifest),
        training_partition_sha256=artifact_sha256(partitions.training),
        holdout_partition_sha256=artifact_sha256(partitions.holdout),
        missing_feature_counts=missing,
        ready_for_calibration=not blockers,
        blockers=blockers,
    )
