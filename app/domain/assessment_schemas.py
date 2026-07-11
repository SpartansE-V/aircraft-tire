"""Public contracts for the canonical aircraft-tire assessment endpoint."""

from typing import Literal, cast
from uuid import UUID

from pydantic import ConfigDict, Field
from pydantic.config import JsonDict

from app.domain.governance_schemas import (
    AuthorizationStatus,
    CalibrationStatus,
    IntendedUse,
    ModelLifecycle,
    ValidationStatus,
)
from app.domain.schemas import GearValue, StrictSchema, WearSeverityRequest, WearSeverityResponse
from app.domain.simulation_schemas import (
    ApprovedLimitEvaluation,
    CurrentConditionEvaluation,
    ModelFactorUsage,
    PressurePolicyComparison,
    SimulationConfidence,
    SimulationProfileId,
    SimulationRecommendation,
    TireSimulationRequest,
    UnscheduledRemovalRisk,
    WearForecast,
)


def _assessment_request_examples() -> list[JsonDict]:
    """Extend the simulation examples with assessment governance inputs."""

    schema_extra = TireSimulationRequest.model_config.get("json_schema_extra")
    if not isinstance(schema_extra, dict):
        raise RuntimeError("TireSimulationRequest must define object schema metadata")

    examples = schema_extra.get("examples")
    if not isinstance(examples, list):
        raise RuntimeError("TireSimulationRequest must define request examples")

    return [
        {
            "intended_use": "SCENARIO_PLANNING",
            **cast(JsonDict, example),
        }
        for example in examples
    ]


class TireAssessmentRequest(TireSimulationRequest):
    """Measured tire condition and bounded future operating assumptions."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra=cast(JsonDict, {"examples": _assessment_request_examples()}),
    )

    intended_use: IntendedUse = Field(
        description=(
            "Declared decision context. The current release permits SCENARIO_PLANNING only."
        ),
        examples=["SCENARIO_PLANNING"],
    )


class RepresentativeCycleAssessment(StrictSchema):
    """Deterministic assessment at each future distribution's most-likely value."""

    basis: Literal["MOST_LIKELY_FUTURE_CONDITIONS"]
    operating_conditions: WearSeverityRequest
    result: WearSeverityResponse


class AssessmentModelVersions(StrictSchema):
    severity: str
    simulation: str


class AssessmentSupportingEvidence(StrictSchema):
    evidence_id: str
    source_kind: Literal["PHYSICAL_TEST"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AssessmentGovernance(StrictSchema):
    release_id: str
    lifecycle: ModelLifecycle
    requested_use: IntendedUse
    requested_use_permitted: bool
    operational_decision_authorized: bool
    calibration_status: CalibrationStatus
    validation_status: ValidationStatus
    authorization_status: AuthorizationStatus
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parameters_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    implementation_id: str
    implementation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    supporting_evidence: list[AssessmentSupportingEvidence]
    reasons: list[str]


class TireAssessmentResponse(StrictSchema):
    """Combined current-cycle and future-scenario tire assessment."""

    assessment_id: UUID
    profile_id: SimulationProfileId
    gear: GearValue
    random_seed: int
    governance: AssessmentGovernance
    representative_cycle: RepresentativeCycleAssessment
    current_condition: CurrentConditionEvaluation
    forecast: WearForecast
    pressure_policy_comparison: PressurePolicyComparison
    approved_limits: ApprovedLimitEvaluation
    unscheduled_removal_risk: UnscheduledRemovalRisk
    model_factor_usage: list[ModelFactorUsage] = Field(min_length=3, max_length=3)
    scenario_drivers: list[str]
    recommendation: SimulationRecommendation
    confidence: SimulationConfidence
    assumptions: list[str]
    model_versions: AssessmentModelVersions
    disclaimer: str = Field(
        description=(
            "Safety limitation for the combined assessment; the nested cycle result also carries "
            "its model-specific disclaimer."
        )
    )
