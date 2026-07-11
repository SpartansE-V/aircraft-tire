"""Reproducible demonstration-only aircraft-tire scenario simulation."""

import math
import random
from typing import cast
from uuid import uuid4

from app.domain.simulation_schemas import (
    ApprovedLimitEvaluation,
    CurrentConditionEvaluation,
    CurrentConditionStatus,
    FloatDistributionSummary,
    IntegerDistributionSummary,
    PressurePolicyComparison,
    RangeDistribution,
    SimulationConfidence,
    SimulationProfile,
    SimulationProfileCatalog,
    SimulationProfileId,
    SimulationRecommendation,
    TireSimulationRequest,
    TireSimulationResponse,
    UnscheduledRemovalRisk,
    WearForecast,
)
from app.services import model_config
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


class TireSimulator:
    """Run an explicitly uncalibrated scenario forecast with bounded inputs."""

    def __init__(self, wear_calculator: WearCalculator | None = None) -> None:
        self._wear_calculator = wear_calculator or WearCalculator()

    def list_profiles(self) -> SimulationProfileCatalog:
        profiles = [
            SimulationProfile(
                profile_id=cast(SimulationProfileId, profile.profile_id),
                display_name=profile.display_name,
                gear=profile.gear,
                model_status="DEMONSTRATION_ONLY",
                initial_tread_depth_mm=profile.initial_tread_depth_mm,
                planning_threshold_mm=profile.planning_threshold_mm,
                certified_limits_available=False,
                disclaimer=model_config.SIMULATION_PROFILE_DISCLAIMER,
            )
            for profile in model_config.SIMULATION_PROFILES.values()
        ]
        return SimulationProfileCatalog(profiles=profiles)

    def simulate(self, request: TireSimulationRequest) -> TireSimulationResponse:
        profile = model_config.SIMULATION_PROFILES[request.profile_id]
        condition = request.current_condition
        future = request.future_conditions
        rng = random.Random(request.random_seed)
        pressure_deficit_pct = max(
            0.0,
            (condition.reference_cold_pressure_psi - condition.measured_cold_pressure_psi)
            / condition.reference_cold_pressure_psi
            * 100,
        )
        remaining_tread_mm = max(
            0.0,
            condition.current_tread_depth_mm - profile.planning_threshold_mm,
        )

        final_tread_values: list[float] = []
        cycles_to_threshold: list[int] = []
        maintained_pressure_cycles: list[int] = []

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
            uncertainty = rng.lognormvariate(0.0, model_config.SIMULATION_UNCERTAINTY_SIGMA)

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

        return TireSimulationResponse(
            simulation_id=uuid4(),
            profile_id=request.profile_id,
            gear=profile.gear,
            random_seed=request.random_seed,
            approved_limits=ApprovedLimitEvaluation(
                status="NOT_AVAILABLE",
                message=(
                    "This demonstration profile has no controlled AMM, CMM, ICA, or certified "
                    "tire-limit data."
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
            unscheduled_removal_risk=UnscheduledRemovalRisk(
                status="NOT_MODELED",
                message=(
                    "FOD, cuts, separation, heat damage, and other premature-removal modes require "
                    "fleet outcome data and qualified inspection; no probability is produced."
                ),
            ),
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
                "The caller-provided reference pressure is unverified approved data.",
                "The profile is a generic demonstration profile, not an aircraft installation.",
                (
                    "Cycles since installation, retread count, and measurement temperature are "
                    "recorded but are not calibrated model factors."
                ),
                "Premature-removal and defect probabilities are not modeled.",
            ],
            model_version=model_config.SIMULATION_MODEL_VERSION,
            disclaimer=model_config.SIMULATION_DISCLAIMER,
        )

    @staticmethod
    def _additional_multiplier(
        *,
        sink_rate_ms: float,
        yaw_angle_deg: float,
        taxi_speed_kt: float,
        brake_temperature_c: float,
        heavy_braking: bool,
        runway_condition: str,
    ) -> float:
        sink_multiplier = (
            1.0
            + max(
                0.0,
                sink_rate_ms - model_config.SIMULATION_SINK_RATE_REFERENCE_MS,
            )
            * model_config.SIMULATION_SINK_RATE_FACTOR
        )
        yaw_multiplier = 1.0 + yaw_angle_deg * model_config.SIMULATION_YAW_FACTOR
        taxi_speed_multiplier = (
            1.0
            + max(
                0.0,
                taxi_speed_kt - model_config.SIMULATION_TAXI_SPEED_REFERENCE_KT,
            )
            * model_config.SIMULATION_TAXI_SPEED_FACTOR
        )
        brake_temperature_multiplier = (
            1.0
            + max(
                0.0,
                brake_temperature_c - model_config.SIMULATION_BRAKE_TEMPERATURE_REFERENCE_C,
            )
            * model_config.SIMULATION_BRAKE_TEMPERATURE_FACTOR
        )
        heavy_braking_multiplier = (
            model_config.SIMULATION_HEAVY_BRAKING_FACTOR if heavy_braking else 1.0
        )
        return (
            sink_multiplier
            * yaw_multiplier
            * taxi_speed_multiplier
            * brake_temperature_multiplier
            * heavy_braking_multiplier
            * model_config.SIMULATION_RUNWAY_FACTORS[runway_condition]
        )

    @staticmethod
    def _condition_guidance(
        *,
        tread_depth_mm: float,
        planning_threshold_mm: float,
        pressure_deficit_pct: float,
        has_known_defects: bool,
    ) -> tuple[CurrentConditionStatus, SimulationRecommendation]:
        if (
            has_known_defects
            or tread_depth_mm <= planning_threshold_mm
            or pressure_deficit_pct >= 10
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
        if pressure_deficit_pct >= 5:
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

    @staticmethod
    def _scenario_drivers(
        request: TireSimulationRequest,
        pressure_deficit_pct: float,
    ) -> list[str]:
        drivers = ["CURRENT_TREAD_DEPTH"]
        if request.current_condition.known_defects:
            drivers.append("KNOWN_DEFECTS")
        if pressure_deficit_pct > 0:
            drivers.append("PRESSURE_DEFICIT")

        future = request.future_conditions
        deviations = {
            "TOUCHDOWN_SPEED": abs(
                future.touchdown_ground_speed_ms.most_likely
                - model_config.REFERENCE_TOUCHDOWN_SPEED_MS
            )
            / model_config.REFERENCE_TOUCHDOWN_SPEED_MS,
            "LANDING_WEIGHT": abs(
                future.landing_weight_kg.most_likely - model_config.REFERENCE_LANDING_WEIGHT_KG
            )
            / model_config.REFERENCE_LANDING_WEIGHT_KG,
            "TAXI_DISTANCE": abs(
                future.taxi_distance_km.most_likely - model_config.REFERENCE_TAXI_DISTANCE_KM
            )
            / model_config.REFERENCE_TAXI_DISTANCE_KM,
            "CROSSWIND": future.crosswind_kt.most_likely / 25.0,
            "TOUCHDOWN_YAW": future.touchdown_yaw_angle_deg.most_likely / 15.0,
            "TAXI_SPEED": future.average_taxi_speed_kt.most_likely / 30.0,
            "BRAKE_TEMPERATURE": future.brake_temperature_c.most_likely / 600.0,
        }
        ranked = sorted(deviations, key=deviations.__getitem__, reverse=True)
        drivers.extend(ranked[:3])
        return drivers


tire_simulator = TireSimulator()
