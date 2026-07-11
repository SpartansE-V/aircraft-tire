"""Evidence-integrity and governance tests for immutable model releases."""

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from app.calibration.artifacts import artifact_sha256, canonical_artifact_bytes
from app.calibration.promotion import (
    CalibrationAcceptanceThresholds,
    CalibrationReportArtifact,
    FrozenCalibrationAcceptancePolicy,
    FrozenCalibrationPredictionArtifact,
    ValidationAcceptanceDecisionArtifact,
    ValidationClaimDecision,
)
from app.calibration.schemas import (
    FleetTireInterval,
    FrozenDatasetPartitionArtifact,
    FrozenPredictionArtifact,
    FrozenValidationAcceptancePolicy,
    HoldoutValidationMetrics,
    HoldoutValidationReport,
    ModelReleaseBinding,
    TreadWearRatePrediction,
    ValidationAcceptanceThresholds,
)
from app.domain.assessment_schemas import TireAssessmentRequest
from app.domain.governance_schemas import (
    ApproverIdentity,
    ExactTargetIdentity,
    ModelReleaseManifest,
)
from app.services.assessment_gate import AssessmentGateError, evaluate_assessment_gate
from app.services.model_registry import (
    InvalidModelReleaseError,
    ModelEvidenceIntegrityError,
    ModelRegistry,
    evaluate_governance,
)
from app.services.wear_calculator import WearCalculator

RELEASE_ID = "pilot-sim-2.0.0"
RELEASE_PATH = Path(__file__).resolve().parents[1] / "app" / "model_releases" / RELEASE_ID
EXPECTED_MANIFEST_SHA256 = "7ec6fb19db1f286a0141ca22b37bfe7e510b3032756e7c61f300965110307159"
EXPECTED_PARAMETERS_SHA256 = "403d3bf6c47071fb804dc714371a4ac6853f06650ce17f094bafc09f90bfdacf"
EXPECTED_IMPLEMENTATION_SHA256 = "3b9458d1dd2feba60e009f4daf9085cb2fd42db51b067f5494b64bef0f3087d5"
EXPECTED_SUPPORTING_EVIDENCE_SHA256 = (
    "1c499db6c7fa0463f3a58856d6a8decb02378a9d23fdc8596482233178b0a943"
)
CALIBRATION_DATASET_SHA256 = "1" * 64
CALIBRATION_REPORT_SHA256 = "2" * 64
CALIBRATION_POLICY_SHA256 = "7" * 64
CALIBRATION_PREDICTIONS_SHA256 = "a" * 64
HOLDOUT_DATASET_SHA256 = "3" * 64
VALIDATION_REPORT_SHA256 = "4" * 64
VALIDATION_METRICS_SHA256 = "5" * 64
VALIDATION_POLICY_SHA256 = "8" * 64
VALIDATION_PREDICTIONS_SHA256 = "b" * 64
CONTROLLED_DOCUMENT_SHA256 = "6" * 64


def _manifest_document() -> dict[str, Any]:
    document = yaml.safe_load((RELEASE_PATH / "manifest.yaml").read_bytes())
    return cast(dict[str, Any], document)


def _calibration_evidence() -> dict[str, Any]:
    return {
        "status": "PASS",
        "dataset": {
            "dataset_id": "operator-fleet-freeze-2026-06",
            "path": "evidence/calibration-training-partition.json",
            "sha256": CALIBRATION_DATASET_SHA256,
            "source": "REAL_FLEET",
            "evidence_role": "CALIBRATION",
            "target_identity": _exact_target_identity(),
        },
        "acceptance_policy": {
            "artifact_id": "calibration-policy-rev-a",
            "path": "evidence/calibration-policy-rev-a.json",
            "sha256": CALIBRATION_POLICY_SHA256,
        },
        "predictions": {
            "artifact_id": "calibration-predictions-rev-a",
            "path": "evidence/calibration-predictions-rev-a.json",
            "sha256": CALIBRATION_PREDICTIONS_SHA256,
        },
        "report": {
            "artifact_id": "calibration-report-rev-a",
            "path": "evidence/calibration-report-rev-a.json",
            "sha256": CALIBRATION_REPORT_SHA256,
        },
    }


def _validation_evidence(*, holdout_digest: str = HOLDOUT_DATASET_SHA256) -> dict[str, Any]:
    return {
        "status": "PASS",
        "holdout_dataset": {
            "dataset_id": "operator-holdout-freeze-2026-06",
            "path": "evidence/validation-holdout-partition.json",
            "sha256": holdout_digest,
            "source": "REAL_FLEET",
            "evidence_role": "VALIDATION_HOLDOUT",
            "target_identity": _exact_target_identity(),
        },
        "predictions": {
            "artifact_id": "validation-predictions-rev-a",
            "path": "evidence/validation-predictions-rev-a.json",
            "sha256": VALIDATION_PREDICTIONS_SHA256,
        },
        "report": {
            "artifact_id": "validation-report-rev-a",
            "path": "evidence/validation-report-rev-a.json",
            "sha256": VALIDATION_REPORT_SHA256,
        },
        "metrics_acceptance": {
            "policy": {
                "artifact_id": "validation-policy-rev-a",
                "path": "evidence/validation-policy-rev-a.json",
                "sha256": VALIDATION_POLICY_SHA256,
            },
            "metrics": {
                "artifact_id": "validation-metrics-rev-a",
                "path": "evidence/validation-metrics-rev-a.json",
                "sha256": VALIDATION_METRICS_SHA256,
            },
            "accepted": True,
            "acceptance_basis": "controlled acceptance criteria ACME-TIRE-VAL-001 rev A",
        },
        "validated_claims": [
            "TREAD_WEAR_RATE_POINT",
            "SEVERITY_CLASSIFICATION",
            "TREAD_DEPTH_INTERVAL_COVERAGE",
            "CYCLES_TO_THRESHOLD",
            "THRESHOLD_EVENT_PROBABILITY",
            "PRESSURE_POLICY_COUNTERFACTUAL",
            "RECOMMENDATION_POLICY",
            "TEMPORAL_GENERALIZATION",
            "AIRCRAFT_TAIL_GENERALIZATION",
        ],
    }


def _exact_target_identity() -> dict[str, str]:
    return {
        "aircraft_manufacturer": "Example Airframer",
        "aircraft_model": "EA-100",
        "aircraft_variant": "EA-100-200",
        "tire_manufacturer": "Example Tire Manufacturer",
        "tire_part_number": "ETM-12345",
        "tire_size": "H44.5x16.5-21",
        "gear_position": "MAIN",
        "wheel_position": "LEFT_MAIN_OUTBOARD",
    }


def _promotion_record(
    record_id: str,
    casing_id: str,
    target_identity: ExactTargetIdentity,
) -> FleetTireInterval:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    return FleetTireInterval(
        record_id=record_id,
        source_system="synthetic-contract-fixture",
        source_extract_id="synthetic-fixture-1",
        operator_id="synthetic-operator",
        aircraft_tail_id=f"tail-{record_id}",
        target_identity=target_identity,
        tire_asset_id=f"asset-{record_id}",
        casing_serial_id=casing_id,
        construction="RADIAL",
        retread_count=0,
        interval_start_utc=start,
        interval_end_utc=end,
        cycles_at_start=0,
        cycles_at_end=10,
        tread_depth_start_mm=10.0,
        tread_depth_end_mm=9.75,
        measurement_gauge_id="gauge-fixture",
        gauge_calibration_due_utc=datetime(2026, 2, 1, tzinfo=UTC),
        cold_pressure_mean_psi=205.0,
        reference_cold_pressure_psi=205.0,
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
        heavy_braking_events=0,
        wet_cycles=0,
        contaminated_cycles=0,
        rough_runway_cycles=0,
        known_defect_at_end=False,
        removal_reason="IN_SERVICE",
    )


def _validated_manifest_document() -> dict[str, Any]:
    document = _manifest_document()
    document["lifecycle"] = "VALIDATED_SHADOW"
    document["intended_uses"] = ["SCENARIO_PLANNING", "MAINTENANCE_PLANNING"]
    document["target_identity"] = _exact_target_identity()
    document["calibration"] = _calibration_evidence()
    document["validation"] = _validation_evidence()
    return document


def _authorization_evidence() -> dict[str, Any]:
    return {
        "status": "AUTHORIZED",
        "controlled_documents": [
            {
                "document_id": "ACME-TIRE-AUTH-001",
                "revision": "A",
                "path": "evidence/acme-tire-auth-001-rev-a.pdf",
                "sha256": CONTROLLED_DOCUMENT_SHA256,
            }
        ],
        "approver": {
            "name": "Authorized Engineering Representative",
            "role": "Chief Airworthiness Engineer",
            "organization": "Example Operator",
        },
        "effective_at": datetime(2026, 7, 1, tzinfo=UTC),
        "expires_at": datetime(2027, 7, 1, tzinfo=UTC),
        "permitted_uses": ["MAINTENANCE_PLANNING"],
    }


def _write_calibrated_release(tmp_path: Path) -> tuple[Path, Path]:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)

    parameter_path = copied_release / "parameters.json"
    parameter_document = json.loads(parameter_path.read_bytes())
    parameter_document["parameter_status"] = "CALIBRATED"
    parameter_document["target_identity"] = _exact_target_identity()
    parameter_bytes = (json.dumps(parameter_document, indent=2) + "\n").encode("utf-8")
    parameter_path.write_bytes(parameter_bytes)
    parameter_sha256 = hashlib.sha256(parameter_bytes).hexdigest()

    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    implementation_sha256 = cast(str, manifest["implementation"]["sha256"])
    target_identity = ExactTargetIdentity.model_validate(_exact_target_identity())
    training_records = (
        _promotion_record("record-1", "casing-1", target_identity),
        _promotion_record("record-2", "casing-2", target_identity),
    )
    training_partition = FrozenDatasetPartitionArtifact(
        schema_version="1.0",
        partition_id="operator-fleet-freeze-2026-06",
        partition_role="TRAINING",
        source_dataset_sha256="9" * 64,
        split_manifest_sha256="a" * 64,
        target_identities=(target_identity,),
        casing_serial_ids=("casing-1", "casing-2"),
        record_ids=("record-1", "record-2"),
        records=training_records,
    )
    calibration_policy = FrozenCalibrationAcceptancePolicy(
        schema_version="1.0",
        policy_id="calibration-policy-rev-a",
        frozen_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        target_identity=target_identity,
        calibrated_claim="TREAD_WEAR_RATE_POINT",
        parameterization_id="pilot-physics-simulation-2.0.0",
        thresholds=CalibrationAcceptanceThresholds(
            minimum_training_record_count=2,
            minimum_training_casing_count=2,
            maximum_mae_mm_per_cycle=0.01,
            maximum_rmse_mm_per_cycle=0.01,
            maximum_absolute_bias_mm_per_cycle=0.01,
            maximum_p90_absolute_error_mm_per_cycle=0.01,
        ),
    )
    model_binding = ModelReleaseBinding(
        release_id=RELEASE_ID,
        parameters_sha256=parameter_sha256,
        implementation_sha256=implementation_sha256,
        target_identity=target_identity,
    )
    calibration_predictions = FrozenCalibrationPredictionArtifact(
        schema_version="1.0",
        artifact_id="calibration-predictions-rev-a",
        created_at_utc=datetime(2026, 1, 2, tzinfo=UTC),
        training_partition_sha256=artifact_sha256(training_partition),
        model_release=model_binding,
        acceptance_policy_sha256=artifact_sha256(calibration_policy),
        predictions=(
            TreadWearRatePrediction(
                record_id="record-1",
                predicted_tread_wear_rate_mm_per_cycle=0.025,
            ),
            TreadWearRatePrediction(
                record_id="record-2",
                predicted_tread_wear_rate_mm_per_cycle=0.025,
            ),
        ),
    )
    calibration_report = CalibrationReportArtifact(
        schema_version="1.0",
        report_id="calibration-report-rev-a",
        created_at_utc=datetime(2026, 1, 3, tzinfo=UTC),
        target_identity=target_identity,
        source_dataset_sha256=training_partition.source_dataset_sha256,
        split_manifest_sha256=training_partition.split_manifest_sha256,
        training_partition_sha256=artifact_sha256(training_partition),
        model_release=model_binding,
        acceptance_policy_sha256=artifact_sha256(calibration_policy),
        prediction_artifact_sha256=artifact_sha256(calibration_predictions),
        calibration_method_id="test-only-external-fit",
        calibration_code_sha256=implementation_sha256,
        calibrated_claim="TREAD_WEAR_RATE_POINT",
        training_record_count=2,
        training_casing_count=2,
        metrics=HoldoutValidationMetrics(
            mae_mm_per_cycle=0.0,
            rmse_mm_per_cycle=0.0,
            bias_mm_per_cycle=0.0,
            p90_absolute_error_mm_per_cycle=0.0,
        ),
        calibration_passed=True,
        blockers=(),
        limitations=("Synthetic contract fixture; not real calibration evidence.",),
    )
    calibration = _calibration_evidence()
    artifacts = (
        (cast(dict[str, Any], calibration["dataset"]), training_partition),
        (cast(dict[str, Any], calibration["acceptance_policy"]), calibration_policy),
        (cast(dict[str, Any], calibration["predictions"]), calibration_predictions),
        (cast(dict[str, Any], calibration["report"]), calibration_report),
    )
    for reference, artifact in artifacts:
        artifact_path = copied_release / cast(str, reference["path"])
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        content = canonical_artifact_bytes(artifact)
        artifact_path.write_bytes(content)
        reference["sha256"] = hashlib.sha256(content).hexdigest()

    manifest["lifecycle"] = "CALIBRATED_SHADOW"
    manifest["target_identity"] = _exact_target_identity()
    manifest["calibration"] = calibration
    manifest["parameters"]["sha256"] = parameter_sha256
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    dataset_path = copied_release / cast(str, cast(dict[str, Any], calibration["dataset"])["path"])
    return releases_root, dataset_path


def _write_validated_release(tmp_path: Path) -> Path:
    releases_root, _ = _write_calibrated_release(tmp_path)
    copied_release = releases_root / RELEASE_ID
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    target_identity = ExactTargetIdentity.model_validate(_exact_target_identity())
    parameter_sha256 = cast(str, manifest["parameters"]["sha256"])
    implementation_sha256 = cast(str, manifest["implementation"]["sha256"])
    model_binding = ModelReleaseBinding(
        release_id=RELEASE_ID,
        parameters_sha256=parameter_sha256,
        implementation_sha256=implementation_sha256,
        target_identity=target_identity,
    )
    calibration_dataset_reference = manifest["calibration"]["dataset"]
    training_partition = FrozenDatasetPartitionArtifact.model_validate_json(
        (copied_release / calibration_dataset_reference["path"]).read_bytes(),
        strict=True,
    )
    holdout_records = (
        _promotion_record("record-3", "casing-3", target_identity),
        _promotion_record("record-4", "casing-4", target_identity),
    )
    holdout_partition = FrozenDatasetPartitionArtifact(
        schema_version="1.0",
        partition_id="operator-holdout-freeze-2026-06",
        partition_role="HOLDOUT",
        source_dataset_sha256=training_partition.source_dataset_sha256,
        split_manifest_sha256=training_partition.split_manifest_sha256,
        target_identities=(target_identity,),
        casing_serial_ids=("casing-3", "casing-4"),
        record_ids=("record-3", "record-4"),
        records=holdout_records,
    )
    thresholds = ValidationAcceptanceThresholds(
        minimum_record_count=2,
        minimum_casing_count=2,
        maximum_mae_mm_per_cycle=0.01,
        maximum_rmse_mm_per_cycle=0.01,
        maximum_absolute_bias_mm_per_cycle=0.01,
        maximum_p90_absolute_error_mm_per_cycle=0.01,
    )
    validation_policy = FrozenValidationAcceptancePolicy(
        schema_version="1.0",
        policy_id="validation-policy-rev-a",
        frozen_at_utc=datetime(2026, 1, 4, tzinfo=UTC),
        target_identity=target_identity,
        acceptance_thresholds=thresholds,
    )
    validation_predictions = FrozenPredictionArtifact(
        schema_version="1.0",
        artifact_id="validation-predictions-rev-a",
        created_at_utc=datetime(2026, 1, 5, tzinfo=UTC),
        split_manifest_sha256=holdout_partition.split_manifest_sha256,
        holdout_partition_sha256=artifact_sha256(holdout_partition),
        model_release=model_binding,
        acceptance_policy_sha256=artifact_sha256(validation_policy),
        predictions=(
            TreadWearRatePrediction(
                record_id="record-3",
                predicted_tread_wear_rate_mm_per_cycle=0.025,
            ),
            TreadWearRatePrediction(
                record_id="record-4",
                predicted_tread_wear_rate_mm_per_cycle=0.025,
            ),
        ),
    )
    validation_report = HoldoutValidationReport(
        schema_version="1.0",
        report_id="validation-report-rev-a",
        dataset_sha256=holdout_partition.source_dataset_sha256,
        split_manifest_sha256=holdout_partition.split_manifest_sha256,
        holdout_partition_sha256=artifact_sha256(holdout_partition),
        prediction_artifact_sha256=artifact_sha256(validation_predictions),
        model_release=model_binding,
        acceptance_policy_sha256=artifact_sha256(validation_policy),
        acceptance_policy_id=validation_policy.policy_id,
        target_identity=target_identity,
        validated_claim="TREAD_WEAR_RATE_POINT",
        acceptance_thresholds=thresholds,
        record_count=2,
        unique_casing_count=2,
        metrics=HoldoutValidationMetrics(
            mae_mm_per_cycle=0.0,
            rmse_mm_per_cycle=0.0,
            bias_mm_per_cycle=0.0,
            p90_absolute_error_mm_per_cycle=0.0,
        ),
        validation_passed=True,
        blockers=[],
    )
    validation_decision = ValidationAcceptanceDecisionArtifact(
        schema_version="1.0",
        decision_id="validation-metrics-rev-a",
        decided_at_utc=datetime(2026, 1, 6, tzinfo=UTC),
        target_identity=target_identity,
        acceptance_policy_sha256=artifact_sha256(validation_policy),
        claim_decisions=(
            ValidationClaimDecision(
                claim="TREAD_WEAR_RATE_POINT",
                report_sha256=artifact_sha256(validation_report),
                passed=True,
            ),
        ),
        accepted_claims=("TREAD_WEAR_RATE_POINT",),
        accepted=True,
        reviewer=ApproverIdentity(
            name="Synthetic Test Reviewer",
            role="Test Fixture Reviewer",
            organization="Synthetic Test Organization",
        ),
        acceptance_basis="controlled acceptance criteria ACME-TIRE-VAL-001 rev A",
    )
    validation = _validation_evidence()
    validation["validated_claims"] = ["TREAD_WEAR_RATE_POINT"]
    artifacts = (
        (cast(dict[str, Any], validation["holdout_dataset"]), holdout_partition),
        (cast(dict[str, Any], validation["predictions"]), validation_predictions),
        (
            cast(dict[str, Any], validation["metrics_acceptance"])["policy"],
            validation_policy,
        ),
        (cast(dict[str, Any], validation["report"]), validation_report),
        (
            cast(dict[str, Any], validation["metrics_acceptance"])["metrics"],
            validation_decision,
        ),
    )
    for reference, artifact in artifacts:
        artifact_path = copied_release / cast(str, reference["path"])
        content = canonical_artifact_bytes(artifact)
        artifact_path.write_bytes(content)
        reference["sha256"] = hashlib.sha256(content).hexdigest()
    manifest["lifecycle"] = "VALIDATED_SHADOW"
    manifest["validation"] = validation
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return releases_root


def test_current_release_has_stable_artifact_digests() -> None:
    release = ModelRegistry().load_release(RELEASE_ID)

    assert release.manifest_sha256 == EXPECTED_MANIFEST_SHA256
    assert release.parameters_sha256 == EXPECTED_PARAMETERS_SHA256
    assert release.manifest.parameters.sha256 == EXPECTED_PARAMETERS_SHA256
    assert release.implementation_sha256 == EXPECTED_IMPLEMENTATION_SHA256
    assert release.manifest.implementation.sha256 == EXPECTED_IMPLEMENTATION_SHA256
    assert release.supporting_evidence_sha256 == (
        ("nasa-tp-3626-ittv-table4", EXPECTED_SUPPORTING_EVIDENCE_SHA256),
    )
    assert release.primary_evidence_sha256 == ()
    assert release.parameters.release_id == RELEASE_ID
    assert release.parameters.parameter_status == "UNCALIBRATED_PILOT_ASSUMPTIONS"


def test_current_release_is_fail_closed_without_fake_evidence() -> None:
    release = ModelRegistry().load_release(RELEASE_ID)

    assert release.manifest.lifecycle == "DEVELOPMENT"
    assert release.manifest.intended_uses == ("SCENARIO_PLANNING",)
    assert release.manifest.target_identity is None
    assert release.manifest.calibration.status == "NOT_PERFORMED"
    assert release.manifest.calibration.dataset is None
    assert release.manifest.calibration.report is None
    assert release.manifest.validation.status == "NOT_PERFORMED"
    assert release.manifest.authorization.status == "NOT_AUTHORIZED"
    assert release.evaluate_governance("SCENARIO_PLANNING").permitted is True
    assert release.evaluate_governance("MAINTENANCE_PLANNING").permitted is False
    assert release.evaluate_governance("DISPATCH_SUPPORT").permitted is False


def test_registry_rejects_tampered_parameter_artifact(tmp_path: Path) -> None:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    parameter_path = copied_release / "parameters.json"
    parameter_path.write_text(parameter_path.read_text() + "\n")

    with pytest.raises(ModelEvidenceIntegrityError, match="checksum"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_rejects_tampered_supporting_evidence(tmp_path: Path) -> None:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    evidence_path = copied_release / "evidence" / "nasa-tp-3626-ittv-table4.json"
    evidence_path.write_text(evidence_path.read_text() + "\n")

    with pytest.raises(ModelEvidenceIntegrityError, match="supporting evidence checksum"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_rejects_checksum_valid_but_invalid_supporting_evidence(
    tmp_path: Path,
) -> None:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    evidence_path = copied_release / "evidence" / "nasa-tp-3626-ittv-table4.json"
    document = json.loads(evidence_path.read_bytes())
    document["calibration_claim"] = "TARGET_CALIBRATION"
    evidence_bytes = (json.dumps(document, indent=2) + "\n").encode()
    evidence_path.write_bytes(evidence_bytes)
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    manifest["supporting_evidence"][0]["sha256"] = hashlib.sha256(evidence_bytes).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(InvalidModelReleaseError, match="supporting evidence artifact is invalid"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_rejects_supporting_evidence_identity_mismatch(tmp_path: Path) -> None:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    evidence_path = copied_release / "evidence" / "nasa-tp-3626-ittv-table4.json"
    document = json.loads(evidence_path.read_bytes())
    document["benchmark_id"] = "different-benchmark"
    evidence_bytes = (json.dumps(document, indent=2) + "\n").encode()
    evidence_path.write_bytes(evidence_bytes)
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    manifest["supporting_evidence"][0]["sha256"] = hashlib.sha256(evidence_bytes).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(InvalidModelReleaseError, match="supporting evidence identity"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_rejects_tampered_implementation(tmp_path: Path) -> None:
    application_root = tmp_path / "app"
    releases_root = application_root / "model_releases"
    shutil.copytree(RELEASE_PATH, releases_root / RELEASE_ID)
    manifest = ModelReleaseManifest.model_validate(_manifest_document(), strict=True)
    source_root = RELEASE_PATH.parents[1]
    for relative_path in manifest.implementation.source_paths:
        destination = application_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative_path, destination)
    tampered_source = application_root / manifest.implementation.source_paths[-1]
    tampered_source.write_text(tampered_source.read_text() + "\n")

    with pytest.raises(ModelEvidenceIntegrityError, match="implementation checksum"):
        ModelRegistry(releases_root, application_root).load_release(RELEASE_ID)


def test_registry_rejects_structurally_invalid_parameter_artifact(tmp_path: Path) -> None:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    parameter_path = copied_release / "parameters.json"
    document = json.loads(parameter_path.read_bytes())
    document["unreviewed_coefficient"] = 123
    parameter_bytes = (json.dumps(document, indent=2) + "\n").encode()
    parameter_path.write_bytes(parameter_bytes)
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    manifest["parameters"]["sha256"] = hashlib.sha256(parameter_bytes).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(InvalidModelReleaseError, match="parameter artifact"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_rejects_calibration_claim_with_uncalibrated_parameters(tmp_path: Path) -> None:
    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    manifest["lifecycle"] = "CALIBRATED_SHADOW"
    manifest["target_identity"] = _exact_target_identity()
    manifest["calibration"] = _calibration_evidence()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(InvalidModelReleaseError, match="calibration status"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_verifies_packaged_calibration_artifacts(tmp_path: Path) -> None:
    releases_root, _ = _write_calibrated_release(tmp_path)

    release = ModelRegistry(releases_root).load_release(RELEASE_ID)

    assert [label for label, _ in release.primary_evidence_sha256] == [
        "calibration dataset operator-fleet-freeze-2026-06",
        "calibration report calibration-report-rev-a",
        "calibration policy calibration-policy-rev-a",
        "calibration predictions calibration-predictions-rev-a",
    ]


def test_registry_rejects_tampered_primary_evidence(tmp_path: Path) -> None:
    releases_root, dataset_path = _write_calibrated_release(tmp_path)
    dataset_path.write_bytes(dataset_path.read_bytes() + b"tampered")

    with pytest.raises(ModelEvidenceIntegrityError, match="calibration dataset.*checksum"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_rejects_checksum_valid_but_semantically_false_calibration(
    tmp_path: Path,
) -> None:
    releases_root, _ = _write_calibrated_release(tmp_path)
    copied_release = releases_root / RELEASE_ID
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    report_reference = manifest["calibration"]["report"]
    report_path = copied_release / report_reference["path"]
    report = CalibrationReportArtifact.model_validate_json(report_path.read_bytes(), strict=True)
    false_report = report.model_copy(update={"training_record_count": 3})
    report_bytes = canonical_artifact_bytes(false_report)
    report_path.write_bytes(report_bytes)
    report_reference["sha256"] = hashlib.sha256(report_bytes).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(
        InvalidModelReleaseError,
        match="CALIBRATION_RECORD_COUNT_MISMATCH",
    ):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_registry_loads_cross_bound_single_claim_validation_bundle(tmp_path: Path) -> None:
    releases_root = _write_validated_release(tmp_path)

    release = ModelRegistry(releases_root).load_release(RELEASE_ID)

    assert release.manifest.lifecycle == "VALIDATED_SHADOW"
    assert release.manifest.validation.validated_claims == ("TREAD_WEAR_RATE_POINT",)
    assert len(release.primary_evidence_sha256) == 9


def test_registry_recomputes_validation_metrics_from_frozen_rows_and_predictions(
    tmp_path: Path,
) -> None:
    releases_root = _write_validated_release(tmp_path)
    copied_release = releases_root / RELEASE_ID
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    report_reference = manifest["validation"]["report"]
    report_path = copied_release / report_reference["path"]
    report = HoldoutValidationReport.model_validate_json(report_path.read_bytes(), strict=True)
    assert report.metrics is not None
    false_metrics = report.metrics.model_copy(update={"mae_mm_per_cycle": 0.001})
    false_report = report.model_copy(update={"metrics": false_metrics})
    report_bytes = canonical_artifact_bytes(false_report)
    report_path.write_bytes(report_bytes)
    report_reference["sha256"] = hashlib.sha256(report_bytes).hexdigest()

    decision_reference = manifest["validation"]["metrics_acceptance"]["metrics"]
    decision_path = copied_release / decision_reference["path"]
    decision = ValidationAcceptanceDecisionArtifact.model_validate_json(
        decision_path.read_bytes(),
        strict=True,
    )
    false_claim = decision.claim_decisions[0].model_copy(
        update={"report_sha256": hashlib.sha256(report_bytes).hexdigest()}
    )
    false_decision = decision.model_copy(update={"claim_decisions": (false_claim,)})
    decision_bytes = canonical_artifact_bytes(false_decision)
    decision_path.write_bytes(decision_bytes)
    decision_reference["sha256"] = hashlib.sha256(decision_bytes).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(InvalidModelReleaseError, match="VALIDATION_METRICS_MISMATCH"):
        ModelRegistry(releases_root).load_release(RELEASE_ID)


def test_verified_parameter_change_changes_calculator_output(tmp_path: Path) -> None:
    baseline_release = ModelRegistry().load_release(RELEASE_ID)
    baseline = WearCalculator(baseline_release.parameters).calculate_raw_values(
        gear="main",
        touchdown_speed_ms=69.0,
        landing_weight_kg=62_000.0,
        crosswind_kt=0.0,
        taxi_distance_km=2.8,
        outside_air_temperature_c=15.0,
        under_inflation_pct=0.0,
    )

    releases_root = tmp_path / "model_releases"
    copied_release = releases_root / RELEASE_ID
    shutil.copytree(RELEASE_PATH, copied_release)
    parameter_path = copied_release / "parameters.json"
    document = json.loads(parameter_path.read_bytes())
    document["gear_configurations"]["main"]["base_wear_rate_mm_per_cycle"] = 0.08
    parameter_bytes = (json.dumps(document, indent=2) + "\n").encode()
    parameter_path.write_bytes(parameter_bytes)
    manifest_path = copied_release / "manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_bytes())
    manifest["parameters"]["sha256"] = hashlib.sha256(parameter_bytes).hexdigest()
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))

    changed_release = ModelRegistry(releases_root).load_release(RELEASE_ID)
    changed = WearCalculator(changed_release.parameters).calculate_raw_values(
        gear="main",
        touchdown_speed_ms=69.0,
        landing_weight_kg=62_000.0,
        crosswind_kt=0.0,
        taxi_distance_km=2.8,
        outside_air_temperature_c=15.0,
        under_inflation_pct=0.0,
    )

    assert changed.wear_rate_mm_per_cycle == pytest.approx(baseline.wear_rate_mm_per_cycle * 2)


def test_manifest_rejects_calibrated_lifecycle_without_real_evidence() -> None:
    document = _manifest_document()
    document["lifecycle"] = "CALIBRATED_SHADOW"
    document["calibration"] = {"status": "PASS", "dataset": None, "report": None}

    with pytest.raises(ValidationError, match="calibration PASS requires"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_manifest_rejects_validation_without_exact_target_identity() -> None:
    document = _validated_manifest_document()
    document["target_identity"] = None

    with pytest.raises(ValidationError, match="exact target identity"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_manifest_rejects_validation_that_reuses_calibration_data() -> None:
    document = _validated_manifest_document()
    document["validation"] = _validation_evidence(holdout_digest=CALIBRATION_DATASET_SHA256)

    with pytest.raises(ValidationError, match="holdout must be distinct"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_manifest_rejects_non_target_supporting_evidence_as_model_data() -> None:
    document = _validated_manifest_document()
    document["calibration"]["dataset"]["sha256"] = EXPECTED_SUPPORTING_EVIDENCE_SHA256

    with pytest.raises(ValidationError, match="supporting evidence cannot be reused"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_manifest_rejects_dataset_target_that_differs_from_release() -> None:
    document = _validated_manifest_document()
    document["validation"]["holdout_dataset"]["target_identity"]["wheel_position"] = (
        "RIGHT_MAIN_OUTBOARD"
    )

    with pytest.raises(ValidationError, match="holdout target must match"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_manifest_rejects_authorized_lifecycle_without_controlled_approval() -> None:
    document = _validated_manifest_document()
    document["lifecycle"] = "AUTHORIZED"
    document["authorization"] = {
        "status": "AUTHORIZED",
        "controlled_documents": [],
        "approver": None,
        "effective_at": None,
        "expires_at": None,
        "permitted_uses": [],
    }

    with pytest.raises(ValidationError, match="controlled-document references"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_manifest_rejects_operational_authorization_with_partial_validation() -> None:
    document = _validated_manifest_document()
    document["lifecycle"] = "AUTHORIZED"
    document["validation"]["validated_claims"] = ["TREAD_WEAR_RATE_POINT"]
    document["authorization"] = _authorization_evidence()

    with pytest.raises(ValidationError, match="every modeled output claim"):
        ModelReleaseManifest.model_validate(document, strict=True)


def test_authorized_release_is_limited_by_use_and_expiry() -> None:
    document = _validated_manifest_document()
    document["lifecycle"] = "AUTHORIZED"
    document["authorization"] = _authorization_evidence()
    manifest = ModelReleaseManifest.model_validate(document, strict=True)

    active = evaluate_governance(
        manifest,
        "MAINTENANCE_PLANNING",
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
    )
    dispatch = evaluate_governance(
        manifest,
        "DISPATCH_SUPPORT",
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
    )
    expired = evaluate_governance(
        manifest,
        "MAINTENANCE_PLANNING",
        as_of=datetime(2027, 7, 1, tzinfo=UTC),
    )

    assert active.permitted is True
    assert dispatch.permitted is False
    assert "requested use is not declared by this release" in dispatch.reasons
    assert expired.permitted is False
    assert "authorization is expired" in expired.reasons


def test_runtime_rejects_target_specific_release_on_generic_endpoint(
    simulation_payload: dict[str, object],
) -> None:
    document = _validated_manifest_document()
    manifest = ModelReleaseManifest.model_validate(document, strict=True)
    current_release = ModelRegistry().load_release(RELEASE_ID)
    target_release = replace(current_release, manifest=manifest)
    request = TireAssessmentRequest.model_validate(simulation_payload)

    with pytest.raises(AssessmentGateError) as raised:
        evaluate_assessment_gate(
            request,
            target_release,
            profile=current_release.parameters.profile(request.profile_id),
        )

    assert raised.value.code == "MODEL_TARGET_IDENTITY_UNAVAILABLE"


def test_public_request_rejects_asset_identity(
    simulation_payload: dict[str, object],
) -> None:
    simulation_payload["asset_identity"] = _exact_target_identity()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TireAssessmentRequest.model_validate(simulation_payload)


def test_strict_manifest_rejects_extra_or_coerced_fields() -> None:
    extra_document = _manifest_document()
    extra_document["unreviewed_evidence"] = "present"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelReleaseManifest.model_validate(extra_document, strict=True)

    coerced_document = _manifest_document()
    coerced_document["schema_version"] = 1.0
    with pytest.raises(ValidationError, match="Input should be '1.0'"):
        ModelReleaseManifest.model_validate(coerced_document, strict=True)


def test_loaded_parameters_are_immutable() -> None:
    release = ModelRegistry().load_release(RELEASE_ID)

    with pytest.raises(ValidationError, match="Instance is frozen"):
        release.parameters.release_id = "mutated"
