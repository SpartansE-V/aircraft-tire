"""Immutable evidence contracts for aircraft-tire model releases."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ModelLifecycle = Literal[
    "DEVELOPMENT",
    "CALIBRATED_SHADOW",
    "VALIDATED_SHADOW",
    "AUTHORIZED",
    "SUSPENDED",
    "RETIRED",
]
IntendedUse = Literal[
    "SCENARIO_PLANNING",
    "MAINTENANCE_PLANNING",
    "DISPATCH_SUPPORT",
]
CalibrationStatus = Literal["NOT_PERFORMED", "PASS"]
ValidationStatus = Literal["NOT_PERFORMED", "PASS"]
AuthorizationStatus = Literal["NOT_AUTHORIZED", "AUTHORIZED"]
DatasetSource = Literal["REAL_FLEET", "PHYSICAL_TEST", "REAL_FLEET_AND_PHYSICAL_TEST"]
DatasetEvidenceRole = Literal["CALIBRATION", "VALIDATION_HOLDOUT"]
GearPosition = Literal["MAIN", "NOSE"]
ValidationClaim = Literal[
    "TREAD_WEAR_RATE_POINT",
    "SEVERITY_CLASSIFICATION",
    "TREAD_DEPTH_INTERVAL_COVERAGE",
    "CYCLES_TO_THRESHOLD",
    "THRESHOLD_EVENT_PROBABILITY",
    "PRESSURE_POLICY_COUNTERFACTUAL",
    "RECOMMENDATION_POLICY",
    "TEMPORAL_GENERALIZATION",
    "AIRCRAFT_TAIL_GENERALIZATION",
]
OPERATIONAL_VALIDATION_CLAIMS: frozenset[ValidationClaim] = frozenset(
    {
        "TREAD_WEAR_RATE_POINT",
        "SEVERITY_CLASSIFICATION",
        "TREAD_DEPTH_INTERVAL_COVERAGE",
        "CYCLES_TO_THRESHOLD",
        "THRESHOLD_EVENT_PROBABILITY",
        "PRESSURE_POLICY_COUNTERFACTUAL",
        "RECOMMENDATION_POLICY",
        "TEMPORAL_GENERALIZATION",
        "AIRCRAFT_TAIL_GENERALIZATION",
    }
)

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ReleaseId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
ReleaseArtifactPath = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*/)*"
            r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:csv|json|jsonl|pdf|yaml|yml)$"
        )
    ),
]


def _yaml_list_to_tuple(value: object) -> object:
    """Normalize only YAML sequences while retaining strict validation otherwise."""

    if isinstance(value, list):
        return tuple(value)
    return value


class EvidenceSchema(BaseModel):
    """Strict and frozen base contract for evidence loaded from release files."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ExactTargetIdentity(EvidenceSchema):
    aircraft_manufacturer: NonEmptyText
    aircraft_model: NonEmptyText
    aircraft_variant: NonEmptyText
    tire_manufacturer: NonEmptyText
    tire_part_number: NonEmptyText
    tire_size: NonEmptyText
    gear_position: GearPosition
    wheel_position: NonEmptyText

    @model_validator(mode="after")
    def reject_placeholder_identity(self) -> Self:
        placeholders = {"*", "ANY", "N/A", "NONE", "TBD", "UNKNOWN", "UNSPECIFIED"}
        values = (
            self.aircraft_manufacturer,
            self.aircraft_model,
            self.aircraft_variant,
            self.tire_manufacturer,
            self.tire_part_number,
            self.tire_size,
            self.gear_position,
            self.wheel_position,
        )
        if any(value.upper() in placeholders for value in values):
            raise ValueError("validated releases require an exact aircraft and tire identity")
        return self


class ArtifactReference(EvidenceSchema):
    artifact_id: NonEmptyText
    path: ReleaseArtifactPath
    sha256: Sha256Digest


class DatasetEvidence(EvidenceSchema):
    dataset_id: NonEmptyText
    path: ReleaseArtifactPath
    sha256: Sha256Digest
    source: DatasetSource
    evidence_role: DatasetEvidenceRole
    target_identity: ExactTargetIdentity


class CalibrationEvidence(EvidenceSchema):
    status: CalibrationStatus
    dataset: DatasetEvidence | None = None
    acceptance_policy: ArtifactReference | None = None
    predictions: ArtifactReference | None = None
    report: ArtifactReference | None = None

    @model_validator(mode="after")
    def validate_status_evidence(self) -> Self:
        evidence = (self.dataset, self.acceptance_policy, self.predictions, self.report)
        if self.status == "PASS" and any(item is None for item in evidence):
            raise ValueError("calibration PASS requires a dataset, policy, predictions, and report")
        if (
            self.status == "PASS"
            and self.dataset is not None
            and self.dataset.evidence_role != "CALIBRATION"
        ):
            raise ValueError("calibration dataset must declare the CALIBRATION evidence role")
        if self.status == "NOT_PERFORMED" and any(item is not None for item in evidence):
            raise ValueError("calibration evidence cannot be attached to NOT_PERFORMED")
        return self


class ValidationMetricsAcceptance(EvidenceSchema):
    policy: ArtifactReference
    metrics: ArtifactReference
    accepted: bool
    acceptance_basis: NonEmptyText


class ValidationEvidence(EvidenceSchema):
    status: ValidationStatus
    holdout_dataset: DatasetEvidence | None = None
    predictions: ArtifactReference | None = None
    report: ArtifactReference | None = None
    metrics_acceptance: ValidationMetricsAcceptance | None = None
    validated_claims: tuple[ValidationClaim, ...] = ()

    @field_validator("validated_claims", mode="before")
    @classmethod
    def normalize_yaml_sequences(cls, value: object) -> object:
        return _yaml_list_to_tuple(value)

    @model_validator(mode="after")
    def validate_status_evidence(self) -> Self:
        evidence = (
            self.holdout_dataset,
            self.predictions,
            self.report,
            self.metrics_acceptance,
        )
        if self.status == "PASS":
            if any(item is None for item in evidence):
                raise ValueError(
                    "validation PASS requires holdout data, predictions, report, and acceptance"
                )
            if self.metrics_acceptance is not None and not self.metrics_acceptance.accepted:
                raise ValueError("validation PASS requires accepted validation metrics")
            if not self.validated_claims:
                raise ValueError("validation PASS requires at least one explicitly validated claim")
            if len(set(self.validated_claims)) != len(self.validated_claims):
                raise ValueError("validated claims must be unique")
            if (
                self.holdout_dataset is not None
                and self.holdout_dataset.evidence_role != "VALIDATION_HOLDOUT"
            ):
                raise ValueError(
                    "validation holdout must declare the VALIDATION_HOLDOUT evidence role"
                )
        elif any(item is not None for item in evidence) or self.validated_claims:
            raise ValueError("validation evidence cannot be attached to NOT_PERFORMED")
        return self


class ControlledDocumentReference(EvidenceSchema):
    document_id: NonEmptyText
    revision: NonEmptyText
    path: ReleaseArtifactPath
    sha256: Sha256Digest


class ApproverIdentity(EvidenceSchema):
    name: NonEmptyText
    role: NonEmptyText
    organization: NonEmptyText


class AuthorizationEvidence(EvidenceSchema):
    status: AuthorizationStatus
    controlled_documents: tuple[ControlledDocumentReference, ...] = ()
    approver: ApproverIdentity | None = None
    effective_at: datetime | None = None
    expires_at: datetime | None = None
    permitted_uses: tuple[IntendedUse, ...] = ()

    @field_validator("controlled_documents", "permitted_uses", mode="before")
    @classmethod
    def normalize_yaml_sequences(cls, value: object) -> object:
        return _yaml_list_to_tuple(value)

    @model_validator(mode="after")
    def validate_authorization_evidence(self) -> Self:
        evidence_present = bool(
            self.controlled_documents
            or self.approver
            or self.effective_at
            or self.expires_at
            or self.permitted_uses
        )
        if self.status == "NOT_AUTHORIZED":
            if evidence_present:
                raise ValueError("authorization evidence cannot be attached to NOT_AUTHORIZED")
            return self

        if not self.controlled_documents:
            raise ValueError("authorization requires controlled-document references")
        if self.approver is None:
            raise ValueError("authorization requires an approver")
        if self.effective_at is None or self.expires_at is None:
            raise ValueError("authorization requires effective and expiry timestamps")
        if self.effective_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("authorization timestamps must be timezone-aware")
        if self.expires_at <= self.effective_at:
            raise ValueError("authorization expiry must be after its effective time")
        if not self.permitted_uses:
            raise ValueError("authorization requires at least one permitted use")
        if len(set(self.permitted_uses)) != len(self.permitted_uses):
            raise ValueError("authorization permitted uses must be unique")
        document_keys = {
            (document.document_id, document.revision) for document in self.controlled_documents
        }
        if len(document_keys) != len(self.controlled_documents):
            raise ValueError("controlled-document references must be unique")
        return self


class ParameterArtifact(EvidenceSchema):
    path: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$"),
    ]
    sha256: Sha256Digest


class ImplementationArtifact(EvidenceSchema):
    implementation_id: NonEmptyText
    source_paths: tuple[
        Annotated[
            str,
            StringConstraints(pattern=r"^(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.py$"),
        ],
        ...,
    ] = Field(min_length=1)
    sha256: Sha256Digest

    @field_validator("source_paths", mode="before")
    @classmethod
    def normalize_yaml_sequences(cls, value: object) -> object:
        return _yaml_list_to_tuple(value)

    @model_validator(mode="after")
    def validate_source_paths(self) -> Self:
        if len(set(self.source_paths)) != len(self.source_paths):
            raise ValueError("implementation source paths must be unique")
        return self


class SupportingEvidenceArtifact(EvidenceSchema):
    evidence_id: NonEmptyText
    path: ReleaseArtifactPath
    sha256: Sha256Digest
    source_kind: Literal["PHYSICAL_TEST"]
    applicability: Literal["NON_TARGET_BENCHMARK"]
    use: Literal["QUALITATIVE_OR_SUBMODEL_RESEARCH_ONLY"]


class ModelReleaseManifest(EvidenceSchema):
    schema_version: Literal["1.0"]
    release_id: ReleaseId
    lifecycle: ModelLifecycle
    intended_uses: tuple[IntendedUse, ...] = Field(min_length=1)
    parameters: ParameterArtifact
    implementation: ImplementationArtifact
    supporting_evidence: tuple[SupportingEvidenceArtifact, ...] = ()
    target_identity: ExactTargetIdentity | None = None
    calibration: CalibrationEvidence
    validation: ValidationEvidence
    authorization: AuthorizationEvidence

    @field_validator("intended_uses", "supporting_evidence", mode="before")
    @classmethod
    def normalize_yaml_sequences(cls, value: object) -> object:
        return _yaml_list_to_tuple(value)

    @model_validator(mode="after")
    def validate_governance_gates(self) -> Self:
        if len(set(self.intended_uses)) != len(self.intended_uses):
            raise ValueError("intended uses must be unique")
        evidence_ids = [evidence.evidence_id for evidence in self.supporting_evidence]
        evidence_paths = [evidence.path for evidence in self.supporting_evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("supporting evidence identifiers must be unique")
        if len(set(evidence_paths)) != len(evidence_paths):
            raise ValueError("supporting evidence paths must be unique")

        primary_paths: list[str] = []
        if self.calibration.dataset is not None:
            primary_paths.append(self.calibration.dataset.path)
        if self.calibration.acceptance_policy is not None:
            primary_paths.append(self.calibration.acceptance_policy.path)
        if self.calibration.predictions is not None:
            primary_paths.append(self.calibration.predictions.path)
        if self.calibration.report is not None:
            primary_paths.append(self.calibration.report.path)
        if self.validation.holdout_dataset is not None:
            primary_paths.append(self.validation.holdout_dataset.path)
        if self.validation.predictions is not None:
            primary_paths.append(self.validation.predictions.path)
        if self.validation.report is not None:
            primary_paths.append(self.validation.report.path)
        if self.validation.metrics_acceptance is not None:
            primary_paths.append(self.validation.metrics_acceptance.policy.path)
            primary_paths.append(self.validation.metrics_acceptance.metrics.path)
        primary_paths.extend(document.path for document in self.authorization.controlled_documents)
        all_evidence_paths = evidence_paths + primary_paths
        if len(set(all_evidence_paths)) != len(all_evidence_paths):
            raise ValueError("release evidence artifact paths must be unique")

        primary_dataset_digests = {
            dataset.sha256
            for dataset in (self.calibration.dataset, self.validation.holdout_dataset)
            if dataset is not None
        }
        supporting_digests = {evidence.sha256 for evidence in self.supporting_evidence}
        if primary_dataset_digests.intersection(supporting_digests):
            raise ValueError("non-target supporting evidence cannot be reused as model data")

        if self.calibration.status == "PASS":
            if self.target_identity is None:
                raise ValueError("calibration PASS requires an exact target identity")
            calibration_dataset = self.calibration.dataset
            if (
                calibration_dataset is not None
                and calibration_dataset.target_identity != self.target_identity
            ):
                raise ValueError("calibration dataset target must match the release target")

        if self.validation.status == "PASS":
            if self.calibration.status != "PASS":
                raise ValueError("validation PASS requires calibration PASS")
            if self.target_identity is None:
                raise ValueError("validation PASS requires an exact target identity")
            calibration_dataset = self.calibration.dataset
            holdout_dataset = self.validation.holdout_dataset
            if (
                holdout_dataset is not None
                and holdout_dataset.target_identity != self.target_identity
            ):
                raise ValueError("validation holdout target must match the release target")
            if (
                calibration_dataset is not None
                and holdout_dataset is not None
                and calibration_dataset.sha256 == holdout_dataset.sha256
            ):
                raise ValueError("validation holdout must be distinct from calibration data")

        if self.authorization.status == "AUTHORIZED":
            if self.validation.status != "PASS":
                raise ValueError("authorization requires validation PASS")
            undeclared_uses = set(self.authorization.permitted_uses) - set(self.intended_uses)
            if undeclared_uses:
                raise ValueError("authorization cannot permit an undeclared intended use")
            missing_claims = OPERATIONAL_VALIDATION_CLAIMS - set(self.validation.validated_claims)
            if missing_claims:
                raise ValueError(
                    "operational authorization requires validation of every modeled output claim"
                )

        if self.lifecycle == "DEVELOPMENT":
            if (
                self.calibration.status != "NOT_PERFORMED"
                or self.validation.status != "NOT_PERFORMED"
                or self.authorization.status != "NOT_AUTHORIZED"
            ):
                raise ValueError(
                    "DEVELOPMENT cannot claim calibration, validation, or authorization"
                )
        elif self.lifecycle == "CALIBRATED_SHADOW":
            if (
                self.calibration.status != "PASS"
                or self.validation.status != "NOT_PERFORMED"
                or self.authorization.status != "NOT_AUTHORIZED"
            ):
                raise ValueError("CALIBRATED_SHADOW requires calibration PASS only")
        elif self.lifecycle == "VALIDATED_SHADOW":
            if (
                self.calibration.status != "PASS"
                or self.validation.status != "PASS"
                or self.authorization.status != "NOT_AUTHORIZED"
            ):
                raise ValueError("VALIDATED_SHADOW requires calibration and validation PASS")
        elif self.lifecycle == "AUTHORIZED":
            if self.authorization.status != "AUTHORIZED":
                raise ValueError("AUTHORIZED lifecycle requires authorization evidence")
        return self


class GovernanceDecision(EvidenceSchema):
    release_id: ReleaseId
    lifecycle: ModelLifecycle
    requested_use: IntendedUse
    permitted: bool
    reasons: tuple[NonEmptyText, ...]
