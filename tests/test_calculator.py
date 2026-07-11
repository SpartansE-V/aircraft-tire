"""Internal calculator behavior tests."""

import math
from typing import Any

import pytest

from app.domain.schemas import WearSeverityRequest, WearSeverityResponse
from app.services.wear_calculator import WearCalculator, classify_severity


def calculate(**overrides: object) -> WearSeverityResponse:
    values: dict[str, Any] = {
        "gear": "main",
        "touchdown_speed_ms": 69,
        "landing_weight_kg": 62000,
        "crosswind_kt": 6,
        "taxi_distance_km": 2.8,
        "outside_air_temperature_c": 30,
        "under_inflation_pct": 0,
    }
    values.update(overrides)
    return WearCalculator().calculate(WearSeverityRequest.model_validate(values))


def test_nominal_main_gear_scenario() -> None:
    result = calculate()

    assert result.gear_label == "Main gear"
    assert result.severity.index == 110
    assert result.severity.level == "MODERATE"
    assert result.estimated_wear_rate_mm_per_cycle == 0.044
    assert result.estimated_total_tread_life_cycles == 225


def test_nominal_nose_gear_scenario() -> None:
    result = calculate(gear="nose")

    assert result.gear_label == "Nose gear"
    assert result.estimated_wear_rate_mm_per_cycle == 0.031
    assert result.estimated_total_tread_life_cycles == 315


def test_main_gear_wears_faster_than_nose_gear() -> None:
    assert (
        calculate(gear="main").estimated_wear_rate_mm_per_cycle
        > calculate(gear="nose").estimated_wear_rate_mm_per_cycle
    )


@pytest.mark.parametrize(
    ("field", "higher_value"),
    [
        ("touchdown_speed_ms", 82),
        ("landing_weight_kg", 73500),
        ("crosswind_kt", 25),
        ("taxi_distance_km", 8),
        ("outside_air_temperature_c", 45),
        ("under_inflation_pct", 5),
    ],
)
def test_higher_operating_driver_increases_severity(field: str, higher_value: float) -> None:
    baseline = calculate()
    increased = calculate(**{field: higher_value})

    assert increased.severity.index > baseline.severity.index


def test_five_percent_under_inflation_triggers_warning() -> None:
    result = calculate(under_inflation_pct=5)

    assert result.pressure_effect.warning is True
    assert result.pressure_effect.message is not None
    assert "approved maintenance procedure" in result.pressure_effect.message


def test_ten_percent_under_inflation_wears_more_than_five_percent() -> None:
    five_percent = calculate(under_inflation_pct=5)
    ten_percent = calculate(under_inflation_pct=10)

    assert (
        ten_percent.estimated_wear_rate_mm_per_cycle > five_percent.estimated_wear_rate_mm_per_cycle
    )


def test_valid_outputs_are_finite_and_positive() -> None:
    result = calculate(
        touchdown_speed_ms=82,
        landing_weight_kg=73500,
        crosswind_kt=25,
        taxi_distance_km=8,
        outside_air_temperature_c=45,
        under_inflation_pct=10,
    )

    numeric_outputs = [
        result.severity.index,
        result.estimated_wear_rate_mm_per_cycle,
        result.estimated_total_tread_life_cycles,
        result.pressure_effect.multiplier,
    ]
    assert all(math.isfinite(value) for value in numeric_outputs)
    assert result.estimated_wear_rate_mm_per_cycle > 0
    assert result.estimated_total_tread_life_cycles > 0


def test_same_request_produces_same_numeric_result() -> None:
    first = calculate().model_dump(exclude={"calculation_id"})
    second = calculate().model_dump(exclude={"calculation_id"})

    assert first == second


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (89, "LOW"),
        (90, "MODERATE"),
        (119, "MODERATE"),
        (120, "HIGH"),
        (169, "HIGH"),
        (170, "CRITICAL"),
    ],
)
def test_severity_boundaries(index: int, expected: str) -> None:
    assert classify_severity(index) == expected
