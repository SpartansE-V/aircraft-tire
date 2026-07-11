"""Conservative service gates that are independent from fitted model coefficients."""

# Development safety policy only. Operational releases must replace this with limits
# supported by controlled installation and maintenance documents.
FORECAST_WITHHOLD_PRESSURE_DEFICIT_PCT = 10.0


def calculate_pressure_deficit_pct(
    *,
    measured_cold_pressure_psi: float,
    reference_cold_pressure_psi: float,
) -> float:
    """Calculate one consistently rounded pressure deficit for every model path."""

    if reference_cold_pressure_psi <= 0:
        raise ValueError("reference cold pressure must be positive")
    raw_deficit = (
        (reference_cold_pressure_psi - measured_cold_pressure_psi)
        / reference_cold_pressure_psi
        * 100
    )
    return max(0.0, round(raw_deficit, 12))
