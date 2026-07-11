"""Bound real-fleet dataset snapshot and frozen-split contract tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.calibration.artifacts import artifact_sha256
from app.calibration.dataset import (
    audit_fleet_dataset,
    freeze_dataset_partitions,
    freeze_dataset_split,
    load_fleet_dataset,
)
from app.calibration.schemas import (
    CalibrationReadinessPolicy,
    FleetTireInterval,
    FrozenDatasetSplitManifest,
)


def _target_identity(**overrides: object) -> dict[str, object]:
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
    return values


def _record(
    record_id: str,
    tire_id: str,
    tail_id: str,
    *,
    casing_id: str | None = None,
    target_identity: dict[str, object] | None = None,
    start_day: int = 0,
    cycles_at_start: int = 10,
    cycles_at_end: int = 50,
) -> dict[str, object]:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=start_day)
    end = start + timedelta(days=30)
    return {
        "record_id": record_id,
        "source_system": "operator-maintenance-export",
        "source_extract_id": "extract-2026-01",
        "operator_id": "operator-a",
        "aircraft_tail_id": tail_id,
        "target_identity": target_identity or _target_identity(),
        "tire_asset_id": tire_id,
        "casing_serial_id": casing_id or f"casing-{tire_id}",
        "construction": "RADIAL",
        "retread_count": 0,
        "interval_start_utc": start.isoformat(),
        "interval_end_utc": end.isoformat(),
        "cycles_at_start": cycles_at_start,
        "cycles_at_end": cycles_at_end,
        "tread_depth_start_mm": 12.5,
        "tread_depth_end_mm": 11.8,
        "measurement_gauge_id": "gauge-1",
        "gauge_calibration_due_utc": (end + timedelta(days=30)).isoformat(),
        "cold_pressure_mean_psi": 230.0,
        "reference_cold_pressure_psi": 230.0,
        "tire_temperature_mean_c": 25.0,
        "landing_weight_mean_kg": 65_000.0,
        "touchdown_ground_speed_mean_ms": 69.0,
        "touchdown_sink_rate_mean_ms": 1.2,
        "touchdown_yaw_angle_mean_deg": 2.0,
        "crosswind_mean_kt": 5.0,
        "taxi_distance_mean_km": 3.0,
        "average_taxi_speed_kt": 15.0,
        "outside_air_temperature_mean_c": 25.0,
        "brake_temperature_mean_c": 200.0,
        "heavy_braking_events": 1,
        "wet_cycles": 2,
        "contaminated_cycles": 0,
        "rough_runway_cycles": 0,
        "known_defect_at_end": False,
        "removal_reason": "WEAR_LIMIT",
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> bytes:
    content = "".join(f"{json.dumps(row)}\n" for row in rows).encode("utf-8")
    path.write_bytes(content)
    return content


def _policy(**overrides: object) -> CalibrationReadinessPolicy:
    values: dict[str, object] = {
        "minimum_intervals": 2,
        "minimum_casings": 2,
        "minimum_aircraft": 2,
        "minimum_wear_limit_removals": 2,
        "validation_fraction": 0.25,
    }
    values.update(overrides)
    return CalibrationReadinessPolicy.model_validate(values)


def test_dataset_loader_rejects_duplicate_records(tmp_path: Path) -> None:
    dataset = tmp_path / "fleet.jsonl"
    row = _record("record-1", "tire-1", "tail-1")
    _write_jsonl(dataset, [row, row])

    with pytest.raises(ValueError, match="duplicate record_id"):
        load_fleet_dataset(dataset)


def test_snapshot_hash_and_rows_come_from_the_same_bytes(tmp_path: Path) -> None:
    dataset = tmp_path / "fleet.jsonl"
    original = _write_jsonl(
        dataset,
        [
            _record("record-1", "tire-1", "tail-1"),
            _record("record-2", "tire-2", "tail-2"),
        ],
    )
    snapshot = load_fleet_dataset(dataset)

    _write_jsonl(
        dataset,
        [
            _record("replacement-1", "tire-3", "tail-3"),
            _record("replacement-2", "tire-4", "tail-4"),
        ],
    )
    split = freeze_dataset_split(
        snapshot,
        split_id="split-1",
        split_seed="seed-1",
        validation_fraction=0.25,
    )
    report = audit_fleet_dataset(snapshot, split, _policy())

    assert snapshot.dataset_sha256 == hashlib.sha256(original).hexdigest()
    assert [record.record_id for record in snapshot.records] == ["record-1", "record-2"]
    assert report.dataset_sha256 == snapshot.dataset_sha256


def test_frozen_split_keeps_all_installations_of_one_casing_together(tmp_path: Path) -> None:
    dataset = tmp_path / "fleet.jsonl"
    rows = [
        _record("record-1", "installation-1", "tail-1", casing_id="casing-shared"),
        _record(
            "record-2",
            "installation-2",
            "tail-1",
            casing_id="casing-shared",
            start_day=30,
            cycles_at_start=50,
            cycles_at_end=90,
        ),
        _record("record-3", "installation-3", "tail-2", casing_id="casing-3"),
        _record("record-4", "installation-4", "tail-2", casing_id="casing-4"),
        _record("record-5", "installation-5", "tail-1", casing_id="casing-5"),
    ]
    _write_jsonl(dataset, rows)
    snapshot = load_fleet_dataset(dataset)
    split = freeze_dataset_split(
        snapshot,
        split_id="b737-apr04450-freeze-1",
        split_seed="project-seed-v1",
        validation_fraction=0.25,
    )
    repeated = freeze_dataset_split(
        snapshot,
        split_id="b737-apr04450-freeze-1",
        split_seed="project-seed-v1",
        validation_fraction=0.25,
    )
    report = audit_fleet_dataset(
        snapshot,
        split,
        _policy(minimum_intervals=5, minimum_casings=4, minimum_wear_limit_removals=5),
    )
    partitions = freeze_dataset_partitions(snapshot, split)
    repeated_partitions = freeze_dataset_partitions(snapshot, repeated)

    assert split == repeated
    assert partitions == repeated_partitions
    assert artifact_sha256(split) == report.split_manifest_sha256
    assert partitions.training.source_dataset_sha256 == snapshot.dataset_sha256
    assert partitions.holdout.source_dataset_sha256 == snapshot.dataset_sha256
    assert partitions.training.split_manifest_sha256 == artifact_sha256(split)
    assert partitions.holdout.split_manifest_sha256 == artifact_sha256(split)
    assert artifact_sha256(partitions.training) == report.training_partition_sha256
    assert artifact_sha256(partitions.holdout) == report.holdout_partition_sha256
    assert report.training_partition_sha256 != report.holdout_partition_sha256
    assert set(split.training_casing_serial_ids).isdisjoint(split.validation_casing_serial_ids)
    record_group = {record_id: "training" for record_id in split.training_record_ids} | {
        record_id: "validation" for record_id in split.validation_record_ids
    }
    assert record_group["record-1"] == record_group["record-2"]
    assert report.ready_for_calibration is True
    assert report.unique_tire_assets == 5
    assert report.unique_casings == 4
    assert report.training_casings == 3
    assert report.validation_casings == 1


def test_audit_rejects_split_bound_to_another_dataset(tmp_path: Path) -> None:
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"
    _write_jsonl(
        first_path,
        [
            _record("first-1", "tire-1", "tail-1"),
            _record("first-2", "tire-2", "tail-2"),
        ],
    )
    _write_jsonl(
        second_path,
        [
            _record("second-1", "tire-3", "tail-1"),
            _record("second-2", "tire-4", "tail-2"),
        ],
    )
    first = load_fleet_dataset(first_path)
    second = load_fleet_dataset(second_path)
    first_split = freeze_dataset_split(
        first,
        split_id="split-1",
        split_seed="seed-1",
        validation_fraction=0.25,
    )

    with pytest.raises(ValueError, match="SPLIT_DATASET_MISMATCH"):
        audit_fleet_dataset(second, first_split, _policy())

    with pytest.raises(ValueError, match="SPLIT_POLICY_MISMATCH"):
        audit_fleet_dataset(first, first_split, _policy(validation_fraction=0.3))


def test_audit_rejects_tampered_frozen_membership(tmp_path: Path) -> None:
    dataset = tmp_path / "fleet.jsonl"
    _write_jsonl(
        dataset,
        [
            _record("record-1", "tire-1", "tail-1"),
            _record("record-2", "tire-2", "tail-2"),
            _record("record-3", "tire-3", "tail-1"),
        ],
    )
    snapshot = load_fleet_dataset(dataset)
    split = freeze_dataset_split(
        snapshot,
        split_id="split-1",
        split_seed="seed-1",
        validation_fraction=0.25,
    )
    document = split.model_dump()
    training_records = list(split.training_record_ids)
    validation_records = list(split.validation_record_ids)
    training_records[0], validation_records[0] = validation_records[0], training_records[0]
    document["training_record_ids"] = training_records
    document["validation_record_ids"] = validation_records
    tampered = FrozenDatasetSplitManifest.model_validate(document, strict=True)

    with pytest.raises(ValueError, match="INVALID_SPLIT_MEMBERSHIP"):
        audit_fleet_dataset(snapshot, tampered, _policy(minimum_intervals=3))


def test_missing_exposure_features_block_readiness(tmp_path: Path) -> None:
    dataset = tmp_path / "fleet.jsonl"
    rows = [
        _record("record-1", "tire-1", "tail-1"),
        _record("record-2", "tire-2", "tail-2"),
    ]
    rows[0]["brake_temperature_mean_c"] = None
    _write_jsonl(dataset, rows)
    snapshot = load_fleet_dataset(dataset)
    split = freeze_dataset_split(
        snapshot,
        split_id="split-1",
        split_seed="seed-1",
        validation_fraction=0.25,
    )

    report = audit_fleet_dataset(snapshot, split, _policy())

    assert report.ready_for_calibration is False
    assert "MISSING_MODEL_FEATURES" in report.blockers
    assert report.missing_feature_counts["brake_temperature_mean_c"] == 1


def test_interval_requires_aware_timestamps_and_nonincreasing_tread() -> None:
    naive_timestamp = _record("record-1", "tire-1", "tail-1")
    naive_timestamp["interval_start_utc"] = datetime(2026, 1, 1).isoformat()

    with pytest.raises(ValidationError, match="timezone"):
        FleetTireInterval.model_validate_json(json.dumps(naive_timestamp))

    increasing_tread = _record("record-1", "tire-1", "tail-1")
    increasing_tread["tread_depth_end_mm"] = 12.6

    with pytest.raises(ValidationError, match="cannot exceed tread_depth_start_mm"):
        FleetTireInterval.model_validate_json(json.dumps(increasing_tread))


@pytest.mark.parametrize(
    "field_name",
    [
        "heavy_braking_events",
        "wet_cycles",
        "contaminated_cycles",
        "rough_runway_cycles",
    ],
)
def test_exposure_counts_cannot_exceed_interval_cycles(field_name: str) -> None:
    row = _record("record-1", "tire-1", "tail-1")
    row[field_name] = 41

    with pytest.raises(ValidationError, match=f"{field_name} cannot exceed interval_cycles"):
        FleetTireInterval.model_validate_json(json.dumps(row))


def test_mixed_exact_targets_block_calibration_readiness(tmp_path: Path) -> None:
    dataset = tmp_path / "fleet.jsonl"
    rows = [
        _record("record-1", "tire-1", "tail-1"),
        _record(
            "record-2",
            "tire-2",
            "tail-2",
            target_identity=_target_identity(tire_size="DIFFERENT-SIZE"),
        ),
    ]
    _write_jsonl(dataset, rows)
    snapshot = load_fleet_dataset(dataset)
    split = freeze_dataset_split(
        snapshot,
        split_id="split-1",
        split_seed="seed-1",
        validation_fraction=0.25,
    )

    report = audit_fleet_dataset(snapshot, split, _policy())

    assert report.ready_for_calibration is False
    assert report.blockers == ["MIXED_TARGET_IDENTITIES"]
    assert len(report.target_identities) == 2


def test_same_casing_target_changes_and_overlapping_intervals_are_blocked(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "fleet.jsonl"
    rows = [
        _record("record-1", "tire-1", "tail-1", casing_id="casing-shared"),
        _record(
            "record-2",
            "tire-2",
            "tail-1",
            casing_id="casing-shared",
            target_identity=_target_identity(wheel_position="RIGHT_MAIN_INBOARD"),
        ),
        _record("record-3", "tire-3", "tail-2", casing_id="casing-3"),
    ]
    _write_jsonl(dataset, rows)
    snapshot = load_fleet_dataset(dataset)
    split = freeze_dataset_split(
        snapshot,
        split_id="split-1",
        split_seed="seed-1",
        validation_fraction=0.25,
    )

    report = audit_fleet_dataset(
        snapshot,
        split,
        _policy(minimum_intervals=3, minimum_casings=2, minimum_wear_limit_removals=3),
    )

    assert report.ready_for_calibration is False
    assert "INCONSISTENT_CASING_TARGET_IDENTITY" in report.blockers
    assert "OVERLAPPING_CASING_INTERVALS" in report.blockers
    assert "MIXED_TARGET_IDENTITIES" in report.blockers
