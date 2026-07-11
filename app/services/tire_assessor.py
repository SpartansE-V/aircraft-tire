"""Canonical service that composes cycle severity and future simulation."""

from app.domain.assessment_schemas import (
    AssessmentGovernance,
    AssessmentModelVersions,
    AssessmentSupportingEvidence,
    RepresentativeCycleAssessment,
    TireAssessmentRequest,
    TireAssessmentResponse,
)
from app.domain.schemas import WearSeverityRequest
from app.services.assessment_gate import AssessmentGateError, evaluate_assessment_gate
from app.services.model_registry import (
    ACTIVE_MODEL_RELEASE_ID,
    ModelRegistry,
    ModelRegistryError,
)
from app.services.safety_policy import calculate_pressure_deficit_pct
from app.services.tire_simulator import TireSimulator
from app.services.wear_calculator import WearCalculator


class TireAssessor:
    """Assess one representative cycle and a future scenario from one request."""

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        release_id: str = ACTIVE_MODEL_RELEASE_ID,
    ) -> None:
        self._registry = registry or ModelRegistry()
        self._release_id = release_id

    def assess(self, request: TireAssessmentRequest) -> TireAssessmentResponse:
        try:
            release = self._registry.load_release(self._release_id)
        except ModelRegistryError as exc:
            raise AssessmentGateError(
                code="MODEL_EVIDENCE_UNAVAILABLE",
                message=(
                    "The active model evidence package is unavailable or failed integrity checks."
                ),
                status_code=503,
            ) from exc
        profile = release.parameters.profile(request.profile_id)
        wear_calculator = WearCalculator(release.parameters)
        simulator = TireSimulator(release.parameters, wear_calculator)
        supporting_evidence_digests = dict(release.supporting_evidence_sha256)
        governance_decision = evaluate_assessment_gate(
            request,
            release,
            profile=profile,
        )
        condition = request.current_condition
        future = request.future_conditions
        pressure_deficit_pct = calculate_pressure_deficit_pct(
            measured_cold_pressure_psi=condition.measured_cold_pressure_psi,
            reference_cold_pressure_psi=condition.reference_cold_pressure_psi,
        )
        operating_conditions = WearSeverityRequest(
            gear=profile.gear,
            touchdown_speed_ms=future.touchdown_ground_speed_ms.most_likely,
            landing_weight_kg=future.landing_weight_kg.most_likely,
            crosswind_kt=future.crosswind_kt.most_likely,
            taxi_distance_km=future.taxi_distance_km.most_likely,
            outside_air_temperature_c=future.outside_air_temperature_c.most_likely,
            under_inflation_pct=pressure_deficit_pct,
        )
        cycle_result = wear_calculator.calculate(operating_conditions)
        simulation = simulator.simulate(request)

        return TireAssessmentResponse(
            assessment_id=simulation.simulation_id,
            profile_id=simulation.profile_id,
            gear=simulation.gear,
            random_seed=simulation.random_seed,
            governance=AssessmentGovernance(
                release_id=release.manifest.release_id,
                lifecycle=release.manifest.lifecycle,
                requested_use=request.intended_use,
                requested_use_permitted=governance_decision.permitted,
                operational_decision_authorized=(
                    governance_decision.permitted and request.intended_use != "SCENARIO_PLANNING"
                ),
                calibration_status=release.manifest.calibration.status,
                validation_status=release.manifest.validation.status,
                authorization_status=release.manifest.authorization.status,
                manifest_sha256=release.manifest_sha256,
                parameters_sha256=release.parameters_sha256,
                implementation_id=release.manifest.implementation.implementation_id,
                implementation_sha256=release.implementation_sha256,
                supporting_evidence=[
                    AssessmentSupportingEvidence(
                        evidence_id=evidence.evidence_id,
                        source_kind=evidence.source_kind,
                        sha256=supporting_evidence_digests[evidence.evidence_id],
                    )
                    for evidence in release.manifest.supporting_evidence
                ],
                reasons=list(governance_decision.reasons),
            ),
            representative_cycle=RepresentativeCycleAssessment(
                basis="MOST_LIKELY_FUTURE_CONDITIONS",
                operating_conditions=operating_conditions,
                result=cycle_result,
            ),
            current_condition=simulation.current_condition,
            forecast=simulation.wear_forecast,
            pressure_policy_comparison=simulation.pressure_policy_comparison,
            approved_limits=simulation.approved_limits,
            unscheduled_removal_risk=simulation.unscheduled_removal_risk,
            model_factor_usage=simulation.model_factor_usage,
            scenario_drivers=simulation.scenario_drivers,
            recommendation=simulation.recommendation,
            confidence=simulation.confidence,
            assumptions=simulation.assumptions,
            model_versions=AssessmentModelVersions(
                severity=cycle_result.model_version,
                simulation=simulation.model_version,
            ),
            disclaimer=simulation.disclaimer,
        )


tire_assessor = TireAssessor()
