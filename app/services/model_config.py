"""Non-numerical response policy for the aircraft-tire model.

All fitted coefficients, operating envelopes, and profile geometry live in the
checksum-verified release parameter artifact. This module contains only public
wording, category mappings, and presentation precision used by the algorithm.
"""

from dataclasses import dataclass

from app.domain.schemas import AttentionLevel, SeverityLevel

DISCLAIMER = (
    "This result is a physics-informed hackathon estimate. It does not replace physical "
    "inspection, aircraft maintenance manuals, or qualified engineering approval."
)
SIMULATION_DISCLAIMER = (
    "This simulation is an uncalibrated demonstration estimate. It does not provide certified "
    "limits, determine serviceability, authorize dispatch, or replace approved maintenance data "
    "and qualified physical inspection."
)
SIMULATION_PROFILE_DISCLAIMER = (
    "Demonstration profile only; it is not an approved aircraft or tire configuration."
)
PRESSURE_WARNING_MESSAGE = (
    "Under-inflation is a significant wear driver. Verify cold tire pressure using the "
    "approved maintenance procedure."
)

# Presentation and algorithm conventions, not fitted model coefficients.
WEAR_RATE_OUTPUT_DECIMALS = 3
PRESSURE_MULTIPLIER_OUTPUT_DECIMALS = 3


@dataclass(frozen=True)
class SeverityConfiguration:
    label: str
    attention: AttentionLevel
    message: str


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
