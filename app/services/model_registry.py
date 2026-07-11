"""Checksum-verified, fail-closed loader for immutable model releases."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from app.calibration.artifacts import canonical_artifact_bytes
from app.calibration.physical_benchmark import (
    PhysicalBenchmarkError,
    PhysicalBenchmarkIntegrityError,
    load_physical_benchmark,
)
from app.calibration.promotion import (
    CalibrationReportArtifact,
    FrozenCalibrationAcceptancePolicy,
    FrozenCalibrationPredictionArtifact,
    ValidationAcceptanceDecisionArtifact,
    calibration_bundle_issues,
    validation_bundle_issues,
)
from app.calibration.schemas import (
    FrozenDatasetPartitionArtifact,
    FrozenDatasetPartitions,
    FrozenPredictionArtifact,
    FrozenValidationAcceptancePolicy,
    HoldoutValidationReport,
    ModelReleaseBinding,
)
from app.domain.governance_schemas import (
    GovernanceDecision,
    IntendedUse,
    ModelReleaseManifest,
)
from app.domain.model_parameter_schemas import ModelParameterSet

_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ACTIVE_MODEL_RELEASE_ID = "pilot-sim-2.0.0"


class ModelRegistryError(RuntimeError):
    """Base error for model-release loading and integrity failures."""


class ModelReleaseNotFoundError(ModelRegistryError):
    """Raised when a requested release package does not exist."""


class InvalidModelReleaseError(ModelRegistryError):
    """Raised when a release package violates the evidence contract."""


class ModelEvidenceIntegrityError(ModelRegistryError):
    """Raised when immutable release content does not match its recorded digest."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _release_artifact_sha256(
    release_directory: Path,
    relative_path: str,
    *,
    label: str,
) -> str:
    """Hash one regular in-package artifact without loading large evidence into memory."""

    candidate = release_directory / relative_path
    resolved_candidate = candidate.resolve()
    if (
        candidate.is_symlink()
        or not resolved_candidate.is_relative_to(release_directory)
        or not resolved_candidate.is_file()
    ):
        raise InvalidModelReleaseError(f"{label} is unavailable or unsafe")
    digest = hashlib.sha256()
    with resolved_candidate.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_canonical_json_artifact[EvidenceModel: BaseModel](
    release_directory: Path,
    relative_path: str,
    expected_sha256: str,
    model_type: type[EvidenceModel],
    *,
    label: str,
    maximum_bytes: int = 10_000_000,
) -> tuple[EvidenceModel, str]:
    """Hash, parse, and canonicalize the same bounded evidence bytes."""

    candidate = release_directory / relative_path
    resolved_candidate = candidate.resolve()
    if (
        candidate.is_symlink()
        or not resolved_candidate.is_relative_to(release_directory)
        or not resolved_candidate.is_file()
    ):
        raise InvalidModelReleaseError(f"{label} is unavailable or unsafe")
    with resolved_candidate.open("rb") as artifact_file:
        content = artifact_file.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise InvalidModelReleaseError(f"{label} exceeds the evidence size limit")
    digest = _sha256(content)
    if not hmac.compare_digest(digest, expected_sha256):
        raise ModelEvidenceIntegrityError(f"{label} checksum does not match manifest")
    try:
        artifact = model_type.model_validate_json(content, strict=True)
    except (ValidationError, ValueError) as exc:
        raise InvalidModelReleaseError(f"{label} does not satisfy its evidence schema") from exc
    if canonical_artifact_bytes(artifact) != content:
        raise InvalidModelReleaseError(f"{label} must use canonical JSON serialization")
    return artifact, digest


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is not permitted: {value}")


def _implementation_sha256(application_root: Path, source_paths: tuple[str, ...]) -> str:
    """Hash ordered path names and bytes so path/content substitutions are detectable."""

    resolved_root = application_root.resolve()
    digest = hashlib.sha256()
    for source_path in source_paths:
        candidate = application_root / source_path
        resolved_candidate = candidate.resolve()
        if (
            candidate.is_symlink()
            or not resolved_candidate.is_relative_to(resolved_root)
            or not resolved_candidate.is_file()
        ):
            raise InvalidModelReleaseError(
                f"implementation source is unavailable or unsafe: {source_path}"
            )
        encoded_path = source_path.encode("utf-8")
        content = resolved_candidate.read_bytes()
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def evaluate_governance(
    manifest: ModelReleaseManifest,
    requested_use: IntendedUse,
    *,
    as_of: datetime | None = None,
) -> GovernanceDecision:
    """Derive whether a verified release may be used for the requested purpose."""

    reasons: list[str] = []
    current_time = as_of or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("governance evaluation time must be timezone-aware")

    if manifest.lifecycle in {"SUSPENDED", "RETIRED"}:
        reasons.append(f"release lifecycle is {manifest.lifecycle}")
    if requested_use not in manifest.intended_uses:
        reasons.append("requested use is not declared by this release")

    if requested_use == "SCENARIO_PLANNING":
        if manifest.lifecycle not in {"SUSPENDED", "RETIRED"} and not reasons:
            return GovernanceDecision(
                release_id=manifest.release_id,
                lifecycle=manifest.lifecycle,
                requested_use=requested_use,
                permitted=True,
                reasons=("release is restricted to declared scenario-planning use",),
            )
    else:
        if manifest.lifecycle != "AUTHORIZED":
            reasons.append("operational use requires the AUTHORIZED lifecycle")
        if manifest.calibration.status != "PASS":
            reasons.append("calibration has not passed")
        if manifest.validation.status != "PASS":
            reasons.append("validation has not passed")
        authorization = manifest.authorization
        if authorization.status != "AUTHORIZED":
            reasons.append("release is not authorized")
        else:
            if requested_use not in authorization.permitted_uses:
                reasons.append("requested use is not permitted by the authorization")
            if authorization.effective_at is None or current_time < authorization.effective_at:
                reasons.append("authorization is not yet effective")
            if authorization.expires_at is None or current_time >= authorization.expires_at:
                reasons.append("authorization is expired")

    if not reasons:
        return GovernanceDecision(
            release_id=manifest.release_id,
            lifecycle=manifest.lifecycle,
            requested_use=requested_use,
            permitted=True,
            reasons=("all evidence and authorization gates passed",),
        )
    return GovernanceDecision(
        release_id=manifest.release_id,
        lifecycle=manifest.lifecycle,
        requested_use=requested_use,
        permitted=False,
        reasons=tuple(dict.fromkeys(reasons)),
    )


@dataclass(frozen=True)
class LoadedModelRelease:
    manifest: ModelReleaseManifest
    parameters: ModelParameterSet
    manifest_sha256: str
    parameters_sha256: str
    implementation_sha256: str
    supporting_evidence_sha256: tuple[tuple[str, str], ...]
    primary_evidence_sha256: tuple[tuple[str, str], ...]

    def evaluate_governance(
        self,
        requested_use: IntendedUse,
        *,
        as_of: datetime | None = None,
    ) -> GovernanceDecision:
        return evaluate_governance(self.manifest, requested_use, as_of=as_of)


def _verify_promotion_semantics(
    release_directory: Path,
    manifest: ModelReleaseManifest,
    *,
    parameters_sha256: str,
    implementation_sha256: str,
) -> None:
    """Parse and cross-check promotion evidence rather than trusting manifest labels."""

    if manifest.calibration.status != "PASS":
        return
    target_identity = manifest.target_identity
    calibration_dataset = manifest.calibration.dataset
    calibration_policy_reference = manifest.calibration.acceptance_policy
    calibration_predictions_reference = manifest.calibration.predictions
    calibration_report_reference = manifest.calibration.report
    if (
        target_identity is None
        or calibration_dataset is None
        or calibration_policy_reference is None
        or calibration_predictions_reference is None
        or calibration_report_reference is None
    ):
        raise InvalidModelReleaseError("calibration evidence package is incomplete")

    expected_model = ModelReleaseBinding(
        release_id=manifest.release_id,
        parameters_sha256=parameters_sha256,
        implementation_sha256=implementation_sha256,
        target_identity=target_identity,
    )
    training_partition, _ = _load_canonical_json_artifact(
        release_directory,
        calibration_dataset.path,
        calibration_dataset.sha256,
        FrozenDatasetPartitionArtifact,
        label=f"calibration dataset {calibration_dataset.dataset_id}",
    )
    calibration_policy, _ = _load_canonical_json_artifact(
        release_directory,
        calibration_policy_reference.path,
        calibration_policy_reference.sha256,
        FrozenCalibrationAcceptancePolicy,
        label=f"calibration policy {calibration_policy_reference.artifact_id}",
    )
    calibration_predictions, _ = _load_canonical_json_artifact(
        release_directory,
        calibration_predictions_reference.path,
        calibration_predictions_reference.sha256,
        FrozenCalibrationPredictionArtifact,
        label=f"calibration predictions {calibration_predictions_reference.artifact_id}",
    )
    calibration_report, _ = _load_canonical_json_artifact(
        release_directory,
        calibration_report_reference.path,
        calibration_report_reference.sha256,
        CalibrationReportArtifact,
        label=f"calibration report {calibration_report_reference.artifact_id}",
    )
    if training_partition.partition_id != calibration_dataset.dataset_id:
        raise InvalidModelReleaseError("calibration partition identity does not match manifest")
    if calibration_policy.policy_id != calibration_policy_reference.artifact_id:
        raise InvalidModelReleaseError("calibration policy identity does not match manifest")
    if calibration_predictions.artifact_id != calibration_predictions_reference.artifact_id:
        raise InvalidModelReleaseError("calibration prediction identity does not match manifest")
    if calibration_report.report_id != calibration_report_reference.artifact_id:
        raise InvalidModelReleaseError("calibration report identity does not match manifest")
    calibration_issues = calibration_bundle_issues(
        training_partition,
        calibration_policy,
        calibration_predictions,
        calibration_report,
        expected_model,
    )
    if calibration_issues:
        issue_summary = ", ".join(calibration_issues)
        raise InvalidModelReleaseError(
            f"calibration evidence did not pass semantic verification: {issue_summary}"
        )

    if manifest.validation.status != "PASS":
        return
    holdout_dataset = manifest.validation.holdout_dataset
    validation_predictions_reference = manifest.validation.predictions
    validation_report_reference = manifest.validation.report
    metrics_acceptance = manifest.validation.metrics_acceptance
    if (
        holdout_dataset is None
        or validation_predictions_reference is None
        or validation_report_reference is None
        or metrics_acceptance is None
    ):
        raise InvalidModelReleaseError("validation evidence package is incomplete")

    holdout_partition, _ = _load_canonical_json_artifact(
        release_directory,
        holdout_dataset.path,
        holdout_dataset.sha256,
        FrozenDatasetPartitionArtifact,
        label=f"validation holdout {holdout_dataset.dataset_id}",
    )
    validation_policy, _ = _load_canonical_json_artifact(
        release_directory,
        metrics_acceptance.policy.path,
        metrics_acceptance.policy.sha256,
        FrozenValidationAcceptancePolicy,
        label=f"validation policy {metrics_acceptance.policy.artifact_id}",
    )
    validation_predictions, _ = _load_canonical_json_artifact(
        release_directory,
        validation_predictions_reference.path,
        validation_predictions_reference.sha256,
        FrozenPredictionArtifact,
        label=f"validation predictions {validation_predictions_reference.artifact_id}",
    )
    validation_report, validation_report_sha256 = _load_canonical_json_artifact(
        release_directory,
        validation_report_reference.path,
        validation_report_reference.sha256,
        HoldoutValidationReport,
        label=f"validation report {validation_report_reference.artifact_id}",
    )
    validation_decision, _ = _load_canonical_json_artifact(
        release_directory,
        metrics_acceptance.metrics.path,
        metrics_acceptance.metrics.sha256,
        ValidationAcceptanceDecisionArtifact,
        label=f"validation metrics {metrics_acceptance.metrics.artifact_id}",
    )
    if holdout_partition.partition_id != holdout_dataset.dataset_id:
        raise InvalidModelReleaseError("holdout partition identity does not match manifest")
    if validation_policy.policy_id != metrics_acceptance.policy.artifact_id:
        raise InvalidModelReleaseError("validation policy identity does not match manifest")
    if validation_predictions.artifact_id != validation_predictions_reference.artifact_id:
        raise InvalidModelReleaseError("validation prediction identity does not match manifest")
    if validation_report.report_id != validation_report_reference.artifact_id:
        raise InvalidModelReleaseError("validation report identity does not match manifest")
    if validation_decision.decision_id != metrics_acceptance.metrics.artifact_id:
        raise InvalidModelReleaseError("validation decision identity does not match manifest")
    if metrics_acceptance.accepted != validation_decision.accepted:
        raise InvalidModelReleaseError("validation acceptance does not match decision artifact")
    if metrics_acceptance.acceptance_basis != validation_decision.acceptance_basis:
        raise InvalidModelReleaseError(
            "validation acceptance basis does not match decision artifact"
        )
    if set(manifest.validation.validated_claims) != set(validation_decision.accepted_claims):
        raise InvalidModelReleaseError("validated claims do not match decision artifact")
    try:
        FrozenDatasetPartitions(training=training_partition, holdout=holdout_partition)
    except ValidationError as exc:
        raise InvalidModelReleaseError(
            "calibration and validation partitions are not a verified disjoint pair"
        ) from exc
    validation_issues = validation_bundle_issues(
        holdout_partition,
        validation_policy,
        validation_predictions,
        validation_report,
        validation_decision,
        expected_model,
        report_sha256=validation_report_sha256,
    )
    if validation_issues:
        issue_summary = ", ".join(validation_issues)
        raise InvalidModelReleaseError(
            f"validation evidence did not pass semantic verification: {issue_summary}"
        )


class ModelRegistry:
    """Load versioned release packages without trusting mutable runtime configuration."""

    def __init__(
        self,
        releases_root: Path | None = None,
        application_root: Path | None = None,
    ) -> None:
        self._releases_root = (
            releases_root or Path(__file__).resolve().parents[1] / "model_releases"
        )
        self._application_root = application_root or Path(__file__).resolve().parents[1]

    def load_release(self, release_id: str) -> LoadedModelRelease:
        """Load a release, validate its evidence, and verify its parameter checksum."""

        if not _RELEASE_ID_PATTERN.fullmatch(release_id):
            raise InvalidModelReleaseError("invalid model release identifier")

        releases_root = self._releases_root.resolve()
        release_directory = self._releases_root / release_id
        resolved_release_directory = release_directory.resolve()
        if release_directory.is_symlink() or resolved_release_directory.parent != releases_root:
            raise InvalidModelReleaseError("model release must be a direct registry directory")
        if not resolved_release_directory.is_dir():
            raise ModelReleaseNotFoundError(f"model release not found: {release_id}")

        manifest_path = resolved_release_directory / "manifest.yaml"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ModelReleaseNotFoundError(f"model release manifest not found: {release_id}")
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest_document = yaml.safe_load(manifest_bytes)
            manifest = ModelReleaseManifest.model_validate(manifest_document, strict=True)
        except (UnicodeDecodeError, yaml.YAMLError, ValidationError, TypeError) as exc:
            raise InvalidModelReleaseError(f"invalid model release manifest: {release_id}") from exc
        if manifest.release_id != release_id:
            raise InvalidModelReleaseError(
                "manifest release_id does not match its registry directory"
            )

        implementation_sha256 = _implementation_sha256(
            self._application_root,
            manifest.implementation.source_paths,
        )
        if not hmac.compare_digest(
            implementation_sha256,
            manifest.implementation.sha256,
        ):
            raise ModelEvidenceIntegrityError(
                "implementation checksum does not match the release manifest"
            )

        supporting_evidence_sha256: list[tuple[str, str]] = []
        for evidence in manifest.supporting_evidence:
            evidence_path = resolved_release_directory / evidence.path
            if not evidence_path.resolve().is_relative_to(resolved_release_directory):
                raise InvalidModelReleaseError(
                    f"supporting evidence artifact is unavailable or unsafe: {evidence.evidence_id}"
                )
            try:
                evidence_snapshot = load_physical_benchmark(
                    evidence_path,
                    expected_sha256=evidence.sha256,
                )
            except PhysicalBenchmarkIntegrityError as exc:
                raise ModelEvidenceIntegrityError(
                    f"supporting evidence checksum does not match manifest: {evidence.evidence_id}"
                ) from exc
            except PhysicalBenchmarkError as exc:
                raise InvalidModelReleaseError(
                    f"supporting evidence artifact is invalid: {evidence.evidence_id}"
                ) from exc
            if evidence_snapshot.benchmark.benchmark_id != evidence.evidence_id:
                raise InvalidModelReleaseError(
                    f"supporting evidence identity does not match manifest: {evidence.evidence_id}"
                )
            supporting_evidence_sha256.append((evidence.evidence_id, evidence_snapshot.sha256))

        parameter_path = resolved_release_directory / manifest.parameters.path
        resolved_parameter_path = parameter_path.resolve()
        if (
            parameter_path.is_symlink()
            or resolved_parameter_path.parent != resolved_release_directory
            or not resolved_parameter_path.is_file()
        ):
            raise InvalidModelReleaseError("parameter artifact must be a regular release file")
        parameter_bytes = resolved_parameter_path.read_bytes()
        parameter_sha256 = _sha256(parameter_bytes)
        if not hmac.compare_digest(parameter_sha256, manifest.parameters.sha256):
            raise ModelEvidenceIntegrityError("parameter artifact checksum does not match manifest")

        try:
            parameter_document = json.loads(
                parameter_bytes,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise InvalidModelReleaseError("parameter artifact is not valid strict JSON") from exc
        try:
            parameters = ModelParameterSet.model_validate(parameter_document, strict=True)
        except ValidationError as exc:
            raise InvalidModelReleaseError("invalid model parameter artifact") from exc
        if parameters.release_id != manifest.release_id:
            raise InvalidModelReleaseError(
                "parameter release_id does not match the release manifest"
            )
        manifest_is_calibrated = manifest.calibration.status == "PASS"
        parameters_are_calibrated = parameters.parameter_status == "CALIBRATED"
        if manifest_is_calibrated != parameters_are_calibrated:
            raise InvalidModelReleaseError(
                "parameter calibration status does not match the evidence manifest"
            )
        if parameters.target_identity != manifest.target_identity:
            raise InvalidModelReleaseError(
                "parameter target identity does not match the evidence manifest"
            )

        primary_evidence_references: list[tuple[str, str, str]] = []
        if manifest.calibration.dataset is not None:
            calibration_dataset = manifest.calibration.dataset
            primary_evidence_references.append(
                (
                    f"calibration dataset {calibration_dataset.dataset_id}",
                    calibration_dataset.path,
                    calibration_dataset.sha256,
                )
            )
        if manifest.calibration.report is not None:
            calibration_report = manifest.calibration.report
            primary_evidence_references.append(
                (
                    f"calibration report {calibration_report.artifact_id}",
                    calibration_report.path,
                    calibration_report.sha256,
                )
            )
        if manifest.calibration.acceptance_policy is not None:
            calibration_policy = manifest.calibration.acceptance_policy
            primary_evidence_references.append(
                (
                    f"calibration policy {calibration_policy.artifact_id}",
                    calibration_policy.path,
                    calibration_policy.sha256,
                )
            )
        if manifest.calibration.predictions is not None:
            calibration_predictions = manifest.calibration.predictions
            primary_evidence_references.append(
                (
                    f"calibration predictions {calibration_predictions.artifact_id}",
                    calibration_predictions.path,
                    calibration_predictions.sha256,
                )
            )
        if manifest.validation.holdout_dataset is not None:
            holdout_dataset = manifest.validation.holdout_dataset
            primary_evidence_references.append(
                (
                    f"validation holdout {holdout_dataset.dataset_id}",
                    holdout_dataset.path,
                    holdout_dataset.sha256,
                )
            )
        if manifest.validation.predictions is not None:
            validation_predictions = manifest.validation.predictions
            primary_evidence_references.append(
                (
                    f"validation predictions {validation_predictions.artifact_id}",
                    validation_predictions.path,
                    validation_predictions.sha256,
                )
            )
        if manifest.validation.report is not None:
            validation_report = manifest.validation.report
            primary_evidence_references.append(
                (
                    f"validation report {validation_report.artifact_id}",
                    validation_report.path,
                    validation_report.sha256,
                )
            )
        if manifest.validation.metrics_acceptance is not None:
            validation_policy = manifest.validation.metrics_acceptance.policy
            primary_evidence_references.append(
                (
                    f"validation policy {validation_policy.artifact_id}",
                    validation_policy.path,
                    validation_policy.sha256,
                )
            )
            validation_metrics = manifest.validation.metrics_acceptance.metrics
            primary_evidence_references.append(
                (
                    f"validation metrics {validation_metrics.artifact_id}",
                    validation_metrics.path,
                    validation_metrics.sha256,
                )
            )
        primary_evidence_references.extend(
            (
                f"controlled document {document.document_id} revision {document.revision}",
                document.path,
                document.sha256,
            )
            for document in manifest.authorization.controlled_documents
        )

        primary_evidence_sha256: list[tuple[str, str]] = []
        for label, path, expected_sha256 in primary_evidence_references:
            digest = _release_artifact_sha256(
                resolved_release_directory,
                path,
                label=label,
            )
            if not hmac.compare_digest(digest, expected_sha256):
                raise ModelEvidenceIntegrityError(f"{label} checksum does not match manifest")
            primary_evidence_sha256.append((label, digest))

        _verify_promotion_semantics(
            resolved_release_directory,
            manifest,
            parameters_sha256=parameter_sha256,
            implementation_sha256=implementation_sha256,
        )

        return LoadedModelRelease(
            manifest=manifest,
            parameters=parameters,
            manifest_sha256=_sha256(manifest_bytes),
            parameters_sha256=parameter_sha256,
            implementation_sha256=implementation_sha256,
            supporting_evidence_sha256=tuple(supporting_evidence_sha256),
            primary_evidence_sha256=tuple(primary_evidence_sha256),
        )

    def evaluate_use(
        self,
        release_id: str,
        requested_use: IntendedUse,
        *,
        as_of: datetime | None = None,
    ) -> GovernanceDecision:
        """Load a verified release and evaluate one requested use."""

        return self.load_release(release_id).evaluate_governance(requested_use, as_of=as_of)
