"""Reproducible demonstration-only aircraft-tire scenario simulation."""

import math
import random
from uuid import uuid4

from app.domain.model_parameter_schemas import (
    ModelParameterSet,
    SyntheticRemovalHazardCoefficients,
)
from app.domain.simulation_schemas import (
    ApprovedLimitEvaluation,
    CurrentConditionEvaluation,
    CurrentConditionStatus,
    FloatDistributionSummary,
    IntegerDistributionSummary,
    ModelFactorField,
    ModelFactorUsage,
    PressurePolicyComparison,
    RangeDistribution,
    RemovalMode,
    RunwayCondition,
    SimulationConfidence,
    SimulationProfile,
    SimulationProfileCatalog,
    SimulationRecommendation,
    SyntheticRemovalModeRisk,
    TireSimulationRequest,
    TireSimulationResponse,
    UnscheduledRemovalRisk,
    WearForecast,
)
from app.services import model_config
from app.services.model_registry import ACTIVE_MODEL_RELEASE_ID, ModelRegistry
from app.services.safety_policy import (
    FORECAST_WITHHOLD_PRESSURE_DEFICIT_PCT,
    calculate_pressure_deficit_pct,
)
from app.services.wear_calculator import WearCalculator


def _sample(distribution: RangeDistribution, rng: random.Random) -> float:
    return rng.triangular(
        distribution.minimum,
        distribution.maximum,
        distribution.most_likely,
    )


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _float_summary(values: list[float]) -> FloatDistributionSummary:
    return FloatDistributionSummary(
        p10=round(_percentile(values, 0.10), 3),
        p50=round(_percentile(values, 0.50), 3),
        p90=round(_percentile(values, 0.90), 3),
    )


def _integer_summary(values: list[int]) -> IntegerDistributionSummary:
    numeric_values = [float(value) for value in values]
    return IntegerDistributionSummary(
        p10=round(_percentile(numeric_values, 0.10)),
        p50=round(_percentile(numeric_values, 0.50)),
        p90=round(_percentile(numeric_values, 0.90)),
    )


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return min(maximum, max(minimum, value))


def _horizon_probability(per_cycle_hazard: float, horizon_cycles: int) -> float:
    bounded_hazard = _clamp(per_cycle_hazard)
    return 1.0 - (1.0 - bounded_hazard) ** horizon_cycles


class TireSimulator:
    """Run an explicitly uncalibrated scenario forecast with bounded inputs."""

    def __init__(
        self,
        parameters: ModelParameterSet | None = None,
        wear_calculator: WearCalculator | None = None,
    ) -> None:
        self._parameters = (
            parameters or ModelRegistry().load_release(ACTIVE_MODEL_RELEASE_ID).parameters
        )
        self._wear_calculator = wear_calculator or WearCalculator(self._parameters)

    def list_profiles(self) -> SimulationProfileCatalog:
        profiles = [
            SimulationProfile(
                profile_id=profile.profile_id,
                display_name=profile.display_name,
                gear=profile.gear,
                model_status="DEMONSTRATION_ONLY",
                initial_tread_depth_mm=profile.initial_tread_depth_mm,
                planning_threshold_mm=profile.planning_threshold_mm,
                certified_limits_available=False,
                disclaimer=model_config.SIMULATION_PROFILE_DISCLAIMER,
            )
            for profile in self._parameters.profiles
        ]
        return SimulationProfileCatalog(profiles=profiles)

    def simulate(self, request: TireSimulationRequest) -> TireSimulationResponse:
        profile = self._parameters.profile(request.profile_id)
        simulation_parameters = self._parameters.simulation
        condition = request.current_condition
        future = request.future_conditions
        rng = random.Random(request.random_seed)
        pressure_deficit_pct = calculate_pressure_deficit_pct(
            measured_cold_pressure_psi=condition.measured_cold_pressure_psi,
            reference_cold_pressure_psi=condition.reference_cold_pressure_psi,
        )
        remaining_tread_mm = max(
            0.0,
            condition.current_tread_depth_mm - profile.planning_threshold_mm,
        )

        final_tread_values: list[float] = []
        cycles_to_threshold: list[int] = []
        maintained_pressure_cycles: list[int] = []
        removal_samples: list[tuple[float, float]] = []

        for _ in range(request.simulation_runs):
            landing_weight_kg = _sample(future.landing_weight_kg, rng)
            touchdown_speed_ms = _sample(future.touchdown_ground_speed_ms, rng)
            crosswind_kt = _sample(future.crosswind_kt, rng)
            taxi_distance_km = _sample(future.taxi_distance_km, rng)
            temperature_c = _sample(future.outside_air_temperature_c, rng)
            sink_rate_ms = _sample(future.touchdown_sink_rate_ms, rng)
            yaw_angle_deg = _sample(future.touchdown_yaw_angle_deg, rng)
            taxi_speed_kt = _sample(future.average_taxi_speed_kt, rng)
            brake_temperature_c = _sample(future.brake_temperature_c, rng)
            heavy_braking = rng.random() < future.heavy_braking_probability
            uncertainty = rng.lognormvariate(0.0, simulation_parameters.uncertainty_sigma)

            actual_raw = self._wear_calculator.calculate_raw_values(
                gear=profile.gear,
                touchdown_speed_ms=touchdown_speed_ms,
                landing_weight_kg=landing_weight_kg,
                crosswind_kt=crosswind_kt,
                taxi_distance_km=taxi_distance_km,
                outside_air_temperature_c=temperature_c,
                under_inflation_pct=pressure_deficit_pct,
            )
            maintained_raw = self._wear_calculator.calculate_raw_values(
                gear=profile.gear,
                touchdown_speed_ms=touchdown_speed_ms,
                landing_weight_kg=landing_weight_kg,
                crosswind_kt=crosswind_kt,
                taxi_distance_km=taxi_distance_km,
                outside_air_temperature_c=temperature_c,
                under_inflation_pct=0.0,
            )
            additional_multiplier = self._additional_multiplier(
                sink_rate_ms=sink_rate_ms,
                yaw_angle_deg=yaw_angle_deg,
                taxi_speed_kt=taxi_speed_kt,
                brake_temperature_c=brake_temperature_c,
                heavy_braking=heavy_braking,
                runway_condition=future.runway_condition,
            )
            actual_wear_rate = (
                actual_raw.wear_rate_mm_per_cycle * additional_multiplier * uncertainty
            )
            maintained_wear_rate = (
                maintained_raw.wear_rate_mm_per_cycle * additional_multiplier * uncertainty
            )
            actual_cycles = (
                0 if remaining_tread_mm == 0 else math.ceil(remaining_tread_mm / actual_wear_rate)
            )
            maintained_cycles = (
                0
                if remaining_tread_mm == 0
                else math.ceil(remaining_tread_mm / maintained_wear_rate)
            )
            final_tread_values.append(
                max(
                    0.0,
                    condition.current_tread_depth_mm - actual_wear_rate * request.horizon_cycles,
                )
            )
            cycles_to_threshold.append(actual_cycles)
            maintained_pressure_cycles.append(maintained_cycles)
            removal_samples.append((taxi_distance_km, brake_temperature_c))

        cycle_summary = _integer_summary(cycles_to_threshold)
        maintained_summary = _integer_summary(maintained_pressure_cycles)
        threshold_probability = sum(
            cycles <= request.horizon_cycles for cycles in cycles_to_threshold
        ) / len(cycles_to_threshold)
        current_status, recommendation = self._condition_guidance(
            tread_depth_mm=condition.current_tread_depth_mm,
            planning_threshold_mm=profile.planning_threshold_mm,
            pressure_deficit_pct=pressure_deficit_pct,
            has_known_defects=bool(condition.known_defects),
        )
        removal_risk = self._synthetic_removal_risk(
            request,
            pressure_deficit_pct=pressure_deficit_pct,
            median_cycles_to_threshold=cycle_summary.p50,
            sampled_conditions=removal_samples,
        )

        return TireSimulationResponse(
            simulation_id=uuid4(),
            profile_id=request.profile_id,
            gear=profile.gear,
            random_seed=request.random_seed,
            approved_limits=ApprovedLimitEvaluation(
                status="NOT_AVAILABLE",
                demonstration_planning_threshold_mm=profile.planning_threshold_mm,
                basis="SYNTHETIC_PILOT_ASSUMPTION",
                message=(
                    "This is a demonstration planning threshold, not an approved removal or "
                    "serviceability limit."
                ),
            ),
            current_condition=CurrentConditionEvaluation(
                status=current_status,
                pressure_deficit_pct=round(pressure_deficit_pct, 3),
                known_defects=condition.known_defects,
            ),
            wear_forecast=WearForecast(
                horizon_cycles=request.horizon_cycles,
                final_tread_depth_mm=_float_summary(final_tread_values),
                cycles_to_planning_threshold=cycle_summary,
                probability_threshold_within_horizon=round(threshold_probability, 4),
            ),
            pressure_policy_comparison=PressurePolicyComparison(
                current_pressure_policy_median_cycles=cycle_summary.p50,
                maintained_reference_pressure_median_cycles=maintained_summary.p50,
                estimated_median_cycle_difference=maintained_summary.p50 - cycle_summary.p50,
            ),
            unscheduled_removal_risk=removal_risk,
            model_factor_usage=self._model_factor_usage(),
            scenario_drivers=self._scenario_drivers(request, pressure_deficit_pct),
            recommendation=recommendation,
            confidence=SimulationConfidence(
                level="LOW",
                reason=(
                    "The coefficients and demonstration profiles have not been calibrated or "
                    "validated against aircraft-tire fleet outcomes."
                ),
            ),
            assumptions=[
                "Each simulation run applies one sampled representative cycle across the horizon.",
                (
                    "The caller-provided reference pressure is an unverified scenario assumption, "
                    "not approved installation data."
                ),
                "The profile is a generic demonstration profile, not an aircraft installation.",
                (
                    "Cycles since installation, retread count, and measurement temperature are "
                    "not used by the wear forecast; they are uncalibrated proxies only in the "
                    "synthetic removal demonstration."
                ),
                (
                    "Removal-mode percentages are synthetic demonstrations, not empirical failure "
                    "probabilities or maintenance predictions."
                ),
                (
                    "The aggregate synthetic removal percentage assumes independent component "
                    "modes for demonstration purposes."
                ),
            ],
            model_version=self._parameters.release_id,
            disclaimer=model_config.SIMULATION_DISCLAIMER,
        )

    @staticmethod
    def _model_factor_usage() -> list[ModelFactorUsage]:
        fields: tuple[ModelFactorField, ...] = (
            "cycles_since_install",
            "retread_count",
            "tire_temperature_c",
        )
        return [
            ModelFactorUsage(
                field=field,
                wear_forecast="RECORDED_NOT_USED",
                removal_demo="USED_AS_SYNTHETIC_PROXY",
            )
            for field in fields
        ]

    def _synthetic_removal_risk(
        self,
        request: TireSimulationRequest,
        *,
        pressure_deficit_pct: float,
        median_cycles_to_threshold: int,
        sampled_conditions: list[tuple[float, float]],
    ) -> UnscheduledRemovalRisk:
        parameters = self._parameters.synthetic_removal
        condition = request.current_condition
        future = request.future_conditions
        domain = self._parameters.input_domain
        age_denominator = condition.cycles_since_install + max(median_cycles_to_threshold, 1)
        fixed_features = {
            "PRESSURE_DEFICIT": _clamp(pressure_deficit_pct / 10.0),
            "INSTALLED_AGE": _clamp(condition.cycles_since_install / age_denominator),
            "RETREAD_COUNT": _clamp(condition.retread_count / parameters.retread_count_reference),
            "TIRE_TEMPERATURE": _clamp(
                (condition.tire_temperature_c - parameters.tire_temperature_reference_c)
                / parameters.tire_temperature_span_c
            ),
            "HEAVY_BRAKING": future.heavy_braking_probability,
            "RUNWAY_EXPOSURE": parameters.runway_exposure.for_condition(future.runway_condition),
        }
        modes: tuple[tuple[RemovalMode, SyntheticRemovalHazardCoefficients], ...] = (
            ("FOD_DAMAGE", parameters.modes.fod_damage),
            ("CUT_OR_EXPOSED_CORD", parameters.modes.cut_or_exposed_cord),
            ("BULGE", parameters.modes.bulge),
            ("TREAD_SEPARATION", parameters.modes.tread_separation),
            ("HEAT_DAMAGE", parameters.modes.heat_damage),
            ("FLAT_SPOT", parameters.modes.flat_spot),
            ("CONTAMINATION", parameters.modes.contamination),
            ("SUDDEN_PRESSURE_LOSS", parameters.modes.sudden_pressure_loss),
        )
        probability_values: dict[RemovalMode, list[float]] = {
            mode: [] for mode, _coefficients in modes
        }
        contribution_totals: dict[RemovalMode, dict[str, float]] = {
            mode: {} for mode, _coefficients in modes
        }
        aggregate_values: list[float] = []

        taxi_span = domain.taxi_distance_km.maximum - domain.taxi_distance_km.minimum
        for taxi_distance_km, brake_temperature_c in sampled_conditions:
            features = {
                **fixed_features,
                "BRAKE_HEAT": _clamp(
                    (brake_temperature_c - parameters.brake_temperature_reference_c)
                    / parameters.brake_temperature_span_c
                ),
                "TAXI_EXPOSURE": _clamp(
                    (taxi_distance_km - domain.taxi_distance_km.minimum) / taxi_span
                ),
            }
            run_probabilities: list[float] = []
            for mode, coefficients in modes:
                contributions = self._removal_contributions(coefficients, features)
                per_cycle_hazard = coefficients.baseline + sum(contributions.values())
                probability = _horizon_probability(per_cycle_hazard, request.horizon_cycles)
                probability_values[mode].append(probability)
                run_probabilities.append(probability)
                for driver, contribution in contributions.items():
                    contribution_totals[mode][driver] = (
                        contribution_totals[mode].get(driver, 0.0) + contribution
                    )
            aggregate_values.append(
                1.0 - math.prod(1.0 - probability for probability in run_probabilities)
            )

        mode_results = [
            SyntheticRemovalModeRisk(
                mode=mode,
                synthetic_probability_pct=round(
                    sum(probability_values[mode]) / len(probability_values[mode]) * 100,
                    3,
                ),
                drivers=[
                    driver
                    for driver, _contribution in sorted(
                        contribution_totals[mode].items(),
                        key=lambda item: (-item[1], item[0]),
                    )[:3]
                ],
            )
            for mode, _coefficients in modes
        ]
        return UnscheduledRemovalRisk(
            status="SYNTHETIC_DEMONSTRATION",
            horizon_cycles=request.horizon_cycles,
            synthetic_probability_pct=round(
                sum(aggregate_values) / len(aggregate_values) * 100,
                3,
            ),
            modes=mode_results,
            confidence="LOW",
            probability_interpretation="NOT_EMPIRICAL_FAILURE_PROBABILITY",
            message=(
                "These percentages use uncalibrated pilot coefficients for demonstration only; "
                "they are not observed failure rates or maintenance predictions."
            ),
        )

    @staticmethod
    def _removal_contributions(
        coefficients: SyntheticRemovalHazardCoefficients,
        features: dict[str, float],
    ) -> dict[str, float]:
        weights = {
            "PRESSURE_DEFICIT": coefficients.pressure_deficit,
            "INSTALLED_AGE": coefficients.installed_age,
            "RETREAD_COUNT": coefficients.retread_count,
            "TIRE_TEMPERATURE": coefficients.tire_temperature,
            "HEAVY_BRAKING": coefficients.heavy_braking,
            "BRAKE_HEAT": coefficients.brake_heat,
            "TAXI_EXPOSURE": coefficients.taxi_exposure,
            "RUNWAY_EXPOSURE": coefficients.runway_exposure,
        }
        return {
            driver: weight * features[driver] for driver, weight in weights.items() if weight > 0
        }

    def _additional_multiplier(
        self,
        *,
        sink_rate_ms: float,
        yaw_angle_deg: float,
        taxi_speed_kt: float,
        brake_temperature_c: float,
        heavy_braking: bool,
        runway_condition: RunwayCondition,
    ) -> float:
        parameters = self._parameters.simulation
        sink_multiplier = (
            1.0
            + max(
                0.0,
                sink_rate_ms - parameters.sink_rate_reference_ms,
            )
            * parameters.sink_rate_factor
        )
        yaw_multiplier = 1.0 + yaw_angle_deg * parameters.yaw_factor
        taxi_speed_multiplier = (
            1.0
            + max(
                0.0,
                taxi_speed_kt - parameters.taxi_speed_reference_kt,
            )
            * parameters.taxi_speed_factor
        )
        brake_temperature_multiplier = (
            1.0
            + max(
                0.0,
                brake_temperature_c - parameters.brake_temperature_reference_c,
            )
            * parameters.brake_temperature_factor
        )
        heavy_braking_multiplier = parameters.heavy_braking_factor if heavy_braking else 1.0
        return (
            sink_multiplier
            * yaw_multiplier
            * taxi_speed_multiplier
            * brake_temperature_multiplier
            * heavy_braking_multiplier
            * parameters.runway_factors.for_condition(runway_condition)
        )

    def _condition_guidance(
        self,
        *,
        tread_depth_mm: float,
        planning_threshold_mm: float,
        pressure_deficit_pct: float,
        has_known_defects: bool,
    ) -> tuple[CurrentConditionStatus, SimulationRecommendation]:
        if (
            has_known_defects
            or tread_depth_mm <= planning_threshold_mm
            or pressure_deficit_pct >= FORECAST_WITHHOLD_PRESSURE_DEFICIT_PCT
        ):
            return (
                "QUALIFIED_INSPECTION_REQUIRED"
                if tread_depth_mm > planning_threshold_mm
                else "PLANNING_THRESHOLD_REACHED",
                SimulationRecommendation(
                    attention="QUALIFIED_INSPECTION_REQUIRED",
                    message=(
                        "Do not use the simulation to determine serviceability. Prioritize a "
                        "qualified inspection using approved maintenance data."
                    ),
                ),
            )
        if pressure_deficit_pct >= self._parameters.base_severity.pressure_warning_threshold_pct:
            return (
                "PRESSURE_ATTENTION",
                SimulationRecommendation(
                    attention="EARLY_INSPECTION",
                    message=(
                        "Verify cold tire pressure with an approved procedure and consider an "
                        "earlier condition inspection."
                    ),
                ),
            )
        return (
            "MONITOR",
            SimulationRecommendation(
                attention="ROUTINE_MONITORING",
                message=(
                    "Continue approved inspections; use this result only for scenario planning."
                ),
            ),
        )

    def _scenario_drivers(
        self,
        request: TireSimulationRequest,
        pressure_deficit_pct: float,
    ) -> list[str]:
        drivers = ["CURRENT_TREAD_DEPTH"]
        if request.current_condition.known_defects:
            drivers.append("KNOWN_DEFECTS")
        if pressure_deficit_pct > 0:
            drivers.append("PRESSURE_DEFICIT")

        future = request.future_conditions
        severity_parameters = self._parameters.base_severity
        domain = self._parameters.input_domain
        deviations = {
            "TOUCHDOWN_SPEED": abs(
                future.touchdown_ground_speed_ms.most_likely
                - severity_parameters.reference_touchdown_speed_ms
            )
            / severity_parameters.reference_touchdown_speed_ms,
            "LANDING_WEIGHT": abs(
                future.landing_weight_kg.most_likely
                - severity_parameters.reference_landing_weight_kg
            )
            / severity_parameters.reference_landing_weight_kg,
            "TAXI_DISTANCE": abs(
                future.taxi_distance_km.most_likely - severity_parameters.reference_taxi_distance_km
            )
            / severity_parameters.reference_taxi_distance_km,
            "CROSSWIND": future.crosswind_kt.most_likely / domain.crosswind_kt.maximum,
            "TOUCHDOWN_YAW": (
                future.touchdown_yaw_angle_deg.most_likely / domain.touchdown_yaw_angle_deg.maximum
            ),
            "TAXI_SPEED": (
                future.average_taxi_speed_kt.most_likely / domain.average_taxi_speed_kt.maximum
            ),
            "BRAKE_TEMPERATURE": (
                future.brake_temperature_c.most_likely / domain.brake_temperature_c.maximum
            ),
        }
        ranked = sorted(deviations, key=deviations.__getitem__, reverse=True)
        drivers.extend(ranked[:3])
        return drivers
