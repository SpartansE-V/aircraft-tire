"""Private model coefficients and output mappings.

This module is an internal implementation detail and must not be exposed through
the public API or generated documentation.
"""

from dataclasses import dataclass

from app.domain.schemas import AttentionLevel, GearValue, SeverityLevel

MODEL_VERSION = "pilot-1.0.0"
DISCLAIMER = (
    "This result is a physics-informed hackathon estimate. It does not replace physical "
    "inspection, aircraft maintenance manuals, or qualified engineering approval."
)

REFERENCE_TOUCHDOWN_SPEED_MS = 69.0
REFERENCE_LANDING_WEIGHT_KG = 62_000.0
REFERENCE_TAXI_DISTANCE_KM = 2.8
REFERENCE_TEMPERATURE_C = 15.0
REFERENCE_PRESSURE_DELTA_PCT = 5.0
UNIT_MULTIPLIER = 1.0
SPIN_EXPONENT = 2.0
SEVERITY_INDEX_SCALE = 100

CROSSWIND_FACTOR = 0.012
TAXI_DISTANCE_FACTOR = 0.05
TEMPERATURE_FACTOR = 0.006
PRESSURE_BASE = 2.0

SPIN_WEIGHT = 0.55
BRAKE_WEIGHT = 0.30
LATERAL_WEIGHT = 0.15
MINIMUM_SEVERITY = 0.1

MAIN_GEAR_BASE_WEAR_RATE = 0.04
NOSE_GEAR_BASE_WEAR_RATE = 0.0285
INITIAL_TREAD_DEPTH_MM = 10.9
MINIMUM_TREAD_DEPTH_MM = 1.0

MODERATE_THRESHOLD = 90
HIGH_THRESHOLD = 120
CRITICAL_THRESHOLD = 170
PRESSURE_WARNING_THRESHOLD_PCT = 5.0
WEAR_RATE_OUTPUT_DECIMALS = 3
PRESSURE_MULTIPLIER_OUTPUT_DECIMALS = 3

SIMULATION_MODEL_VERSION = "pilot-sim-2.0.0"
SIMULATION_DISCLAIMER = (
    "This simulation is an uncalibrated demonstration estimate. It does not provide certified "
    "limits, determine serviceability, authorize dispatch, or replace approved maintenance data "
    "and qualified physical inspection."
)
SIMULATION_PROFILE_DISCLAIMER = (
    "Demonstration profile only; it is not an approved aircraft or tire configuration."
)
SIMULATION_UNCERTAINTY_SIGMA = 0.15
SIMULATION_SINK_RATE_REFERENCE_MS = 1.0
SIMULATION_SINK_RATE_FACTOR = 0.10
SIMULATION_YAW_FACTOR = 0.012
SIMULATION_TAXI_SPEED_REFERENCE_KT = 15.0
SIMULATION_TAXI_SPEED_FACTOR = 0.008
SIMULATION_BRAKE_TEMPERATURE_REFERENCE_C = 200.0
SIMULATION_BRAKE_TEMPERATURE_FACTOR = 0.0004
SIMULATION_HEAVY_BRAKING_FACTOR = 1.12
SIMULATION_RUNWAY_FACTORS = {
    "DRY": 1.0,
    "WET": 1.03,
    "CONTAMINATED": 1.08,
    "ROUGH": 1.12,
}

PRESSURE_WARNING_MESSAGE = (
    "Under-inflation is a significant wear driver. Verify cold tire pressure using the "
    "approved maintenance procedure."
)


@dataclass(frozen=True)
class GearConfiguration:
    label: str
    base_wear_rate: float


@dataclass(frozen=True)
class SeverityConfiguration:
    label: str
    attention: AttentionLevel
    message: str


@dataclass(frozen=True)
class SimulationProfileConfiguration:
    profile_id: str
    display_name: str
    gear: GearValue
    initial_tread_depth_mm: float
    planning_threshold_mm: float


GEAR_CONFIGURATIONS = {
    "main": GearConfiguration(label="Main gear", base_wear_rate=MAIN_GEAR_BASE_WEAR_RATE),
    "nose": GearConfiguration(label="Nose gear", base_wear_rate=NOSE_GEAR_BASE_WEAR_RATE),
}

SEVERITY_CONFIGURATIONS: dict[SeverityLevel, SeverityConfiguration] = {
    "LOW": SeverityConfiguration(
        label="Low wear conditions",
        attention="ROUTINE_MONITORING",
        message=(
            "Operating conditions indicate relatively low tire-wear severity. Continue routine "
            "inspections."
        ),
    ),
    "MODERATE": SeverityConfiguration(
        label="Moderate wear conditions",
        attention="NORMAL_MONITORING",
        message=(
            "Operating conditions are within the normal pilot range. Continue inspections "
            "according to the maintenance schedule."
        ),
    ),
    "HIGH": SeverityConfiguration(
        label="High wear conditions",
        attention="INCREASED_ATTENTION",
        message=(
            "Operating conditions may accelerate tire wear. Consider an earlier tread-depth and "
            "pressure inspection."
        ),
    ),
    "CRITICAL": SeverityConfiguration(
        label="Critical wear conditions",
        attention="MAINTENANCE_ATTENTION",
        message=(
            "The scenario indicates severe tire-wear conditions. A qualified maintenance "
            "inspection should be prioritized."
        ),
    ),
}

SIMULATION_PROFILES = {
    "pilot-main-v1": SimulationProfileConfiguration(
        profile_id="pilot-main-v1",
        display_name="Pilot main-gear demonstration profile",
        gear="main",
        initial_tread_depth_mm=INITIAL_TREAD_DEPTH_MM,
        planning_threshold_mm=MINIMUM_TREAD_DEPTH_MM,
    ),
    "pilot-nose-v1": SimulationProfileConfiguration(
        profile_id="pilot-nose-v1",
        display_name="Pilot nose-gear demonstration profile",
        gear="nose",
        initial_tread_depth_mm=INITIAL_TREAD_DEPTH_MM,
        planning_threshold_mm=MINIMUM_TREAD_DEPTH_MM,
    ),
}
