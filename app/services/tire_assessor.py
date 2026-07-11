"""Canonical service that composes cycle severity and future simulation."""

from app.domain.assessment_schemas import (
    AssessmentModelVersions,
    RepresentativeCycleAssessment,
    TireAssessmentRequest,
    TireAssessmentResponse,
)
from app.domain.schemas import WearSeverityRequest
from app.services.tire_simulator import TireSimulator, tire_simulator
from app.services.wear_calculator import WearCalculator, calculator


class TireAssessor:
    """Assess one representative cycle and a future scenario from one request."""

    def __init__(
        self,
        wear_calculator: WearCalculator | None = None,
        simulator: TireSimulator | None = None,
    ) -> None:
        self._wear_calculator = wear_calculator or calculator
        self._simulator = simulator or tire_simulator

    def assess(self, request: TireAssessmentRequest) -> TireAssessmentResponse:
        profile = next(
            profile
            for profile in self._simulator.list_profiles().profiles
            if profile.profile_id == request.profile_id
        )
        condition = request.current_condition
        future = request.future_conditions
        pressure_deficit_pct = max(
            0.0,
            (condition.reference_cold_pressure_psi - condition.measured_cold_pressure_psi)
            / condition.reference_cold_pressure_psi
            * 100,
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
        cycle_result = self._wear_calculator.calculate(operating_conditions)
        simulation = self._simulator.simulate(request)

        return TireAssessmentResponse(
            assessment_id=simulation.simulation_id,
            profile_id=simulation.profile_id,
            gear=simulation.gear,
            random_seed=simulation.random_seed,
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
