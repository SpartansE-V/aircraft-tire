"""Public contracts for the canonical aircraft-tire assessment endpoint."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.schemas import GearValue, StrictSchema, WearSeverityRequest, WearSeverityResponse
from app.domain.simulation_schemas import (
    ApprovedLimitEvaluation,
    CurrentConditionEvaluation,
    PressurePolicyComparison,
    SimulationConfidence,
    SimulationProfileId,
    SimulationRecommendation,
    TireSimulationRequest,
    UnscheduledRemovalRisk,
    WearForecast,
)


class TireAssessmentRequest(TireSimulationRequest):
    """Measured tire condition and bounded future operating assumptions."""

    @model_validator(mode="after")
    def validate_pressure_deficit_domain(self) -> "TireAssessmentRequest":
        condition = self.current_condition
        deficit_pct = max(
            0.0,
            (condition.reference_cold_pressure_psi - condition.measured_cold_pressure_psi)
            / condition.reference_cold_pressure_psi
            * 100,
        )
        if deficit_pct > 10.0:
            raise ValueError(
                "measured cold pressure must remain within 10% of the reference pressure"
            )
        return self


class RepresentativeCycleAssessment(StrictSchema):
    """Deterministic assessment at each future distribution's most-likely value."""

    basis: Literal["MOST_LIKELY_FUTURE_CONDITIONS"]
    operating_conditions: WearSeverityRequest
    result: WearSeverityResponse


class AssessmentModelVersions(StrictSchema):
    severity: str
    simulation: str


class TireAssessmentResponse(StrictSchema):
    """Combined current-cycle and future-scenario tire assessment."""

    assessment_id: UUID
    profile_id: SimulationProfileId
    gear: GearValue
    random_seed: int
    representative_cycle: RepresentativeCycleAssessment
    current_condition: CurrentConditionEvaluation
    forecast: WearForecast
    pressure_policy_comparison: PressurePolicyComparison
    approved_limits: ApprovedLimitEvaluation
    unscheduled_removal_risk: UnscheduledRemovalRisk
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
