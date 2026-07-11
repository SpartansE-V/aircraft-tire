"""scoring.py tests — including the safety-critical invariants:
P10-not-median alerting, wear-out vs event-driven separation, priority != raw RUL, and the
low-confidence fleet-prior path.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.tire_rul import scoring
from app.tire_rul.constants import AlertCategory, AlertType, PressureLadderAction
from app.tire_rul.scoring import TireRulEstimate, WheelRisk

PRIOR_MEAN = np.array([12.0, -0.035])
PRIOR_COV = np.array([[0.7, 0.0], [0.0, 1e-4]])
SCALE = 0.09
AS_OF = date(2025, 1, 1)


# ---------------------------------------------------------------------------
# Monte-Carlo crossing + posterior
# ---------------------------------------------------------------------------
def test_mc_crossing_monotonic_in_slope():
    cov = np.array([[0.01, 0.0], [0.0, 1e-6]])
    steep = scoring.monte_carlo_crossing(np.array([12.0, -0.06]), cov, 2.0, 4000, 42)
    shallow = scoring.monte_carlo_crossing(np.array([12.0, -0.03]), cov, 2.0, 4000, 42)
    assert np.median(steep) < np.median(shallow)  # steeper wear crosses the limit sooner


def test_mc_crossing_reproducible():
    cov = np.array([[0.01, 0.0], [0.0, 1e-6]])
    a = scoring.monte_carlo_crossing(np.array([12.0, -0.05]), cov, 2.0, 2000, 7)
    b = scoring.monte_carlo_crossing(np.array([12.0, -0.05]), cov, 2.0, 2000, 7)
    assert np.array_equal(a, b)


def test_eb_posterior_zero_readings_returns_prior():
    mean, cov = scoring.eb_posterior(np.array([]), np.array([]), PRIOR_MEAN, PRIOR_COV, SCALE)
    assert np.allclose(mean, PRIOR_MEAN)
    assert np.allclose(cov, PRIOR_COV)


def test_eb_posterior_tracks_data_and_tightens():
    cycles = np.arange(20, 200, 20, dtype=float)
    true_slope = -0.05
    grooves = 13.0 + true_slope * cycles
    mean, cov = scoring.eb_posterior(cycles, grooves, PRIOR_MEAN, PRIOR_COV, SCALE)
    # posterior slope moves toward the data slope, and uncertainty shrinks vs the prior
    assert abs(mean[1] - true_slope) < abs(PRIOR_MEAN[1] - true_slope)
    assert np.trace(cov) < np.trace(PRIOR_COV)


# ---------------------------------------------------------------------------
# RUL quantiles + dates
# ---------------------------------------------------------------------------
def _estimate(cycles, grooves, n_readings, lpd=3.0):
    return scoring.estimate_wheel(
        np.asarray(cycles, float),
        np.asarray(grooves, float),
        PRIOR_MEAN,
        PRIOR_COV,
        SCALE,
        current_cycles=float(cycles[-1]),
        landings_per_day=lpd,
        as_of_date=AS_OF,
        limit_mm=2.0,
        mc_draws=3000,
        mc_seed=123,
        next_check_cycles=25,
        n_readings=n_readings,
        low_confidence_min_readings=3,
    )


def test_rul_quantiles_and_dates_ordered():
    cycles = np.arange(20, 200, 20, dtype=float)
    grooves = 13.0 - 0.05 * cycles
    est = _estimate(cycles, grooves, n_readings=len(cycles))
    assert est.rul_p10 <= est.rul_median <= est.rul_p90
    assert est.date_p10 <= est.date_median <= est.date_p90  # earliest-credible date is soonest


def test_low_confidence_has_wide_band_and_flag():
    tight = _estimate(np.arange(20, 200, 20, dtype=float), 13.0 - 0.05 * np.arange(20, 200, 20), n_readings=9)
    wide = _estimate(np.array([20.0]), np.array([11.3]), n_readings=1)
    assert wide.low_confidence and not tight.low_confidence
    assert (wide.rul_p90 - wide.rul_p10) > (tight.rul_p90 - tight.rul_p10)


# ---------------------------------------------------------------------------
# Pressure ladder
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "pressure,expected",
    [
        (101.0, PressureLadderAction.OK.value),
        (97.0, PressureLadderAction.REINFLATE.value),
        (92.0, PressureLadderAction.INSPECT.value),
        (85.0, PressureLadderAction.REMOVE.value),
        (70.0, PressureLadderAction.REMOVE_TIRE_AND_MATE.value),
    ],
)
def test_pressure_ladder_bands(threshold_config, pressure, expected):
    assert scoring.pressure_ladder_action(pressure, threshold_config.pressure_bands) == expected


# ---------------------------------------------------------------------------
# Priority (NOT a raw RUL sort)
# ---------------------------------------------------------------------------
def _make_estimate(*, p_cross, rul_median, rul_p10=None, p10_days=40, median_days=45, low_conf=False):
    rul_p10 = rul_median * 0.9 if rul_p10 is None else rul_p10
    return TireRulEstimate(
        rul_p10=rul_p10,
        rul_median=rul_median,
        rul_p90=rul_median * 1.1,
        rul_mean=rul_median,
        crossing_median_cycle=rul_median,
        p_cross_next_check=p_cross,
        frac_never=0.0,
        date_p10=AS_OF + timedelta(days=p10_days),
        date_median=AS_OF + timedelta(days=median_days),
        date_p90=AS_OF + timedelta(days=median_days + 5),
        landings_per_day=3.0,
        low_confidence=low_conf,
        intercept=12.0,
        slope=-0.035,
    )


def _risk(tail, pos, station, on_hand, cpd, est, **kw):
    return WheelRisk(
        aircraft_id=tail,
        tail_number=tail,
        position_code=pos,
        station=station,
        on_hand=on_hand,
        cycles_per_day=cpd,
        estimate=est,
        **kw,
    )


def test_priority_equal_rul_breaks_on_consequence(threshold_config):
    est = _make_estimate(p_cross=0.5, rul_median=60)
    low_util_stocked = _risk("VN-A1", "mlg_l_inbd", "HAN", 5, 2.0, est)
    high_util_nostock = _risk("VN-A2", "mlg_l_inbd", "SGN", 0, 5.5, est)
    rows = scoring.build_worklist([low_util_stocked, high_util_nostock], threshold_config)
    ranks = {r.tail_number: r.rank for r in rows}
    assert ranks["VN-A2"] < ranks["VN-A1"]  # higher utilization + zero spares ranks first


def test_priority_is_not_raw_rul_sort(threshold_config):
    # Wheel L has LOWER RUL but low utilization + spares + low crossing prob.
    low_rul = _risk("VN-L", "mlg_l_inbd", "HAN", 5, 1.8, _make_estimate(p_cross=0.25, rul_median=40))
    # Wheel H has HIGHER RUL but high utilization, no spares, high crossing prob.
    high_rul = _risk("VN-H", "mlg_l_inbd", "SGN", 0, 5.5, _make_estimate(p_cross=0.55, rul_median=70))
    rows = scoring.build_worklist([low_rul, high_rul], threshold_config)
    ranks = {r.tail_number: r.rank for r in rows}
    assert ranks["VN-H"] < ranks["VN-L"]  # ranked by risk, not by smallest RUL


# ---------------------------------------------------------------------------
# Alerts — P10 not median, and wear-out vs event-driven separation
# ---------------------------------------------------------------------------
def test_wear_out_alert_fires_on_p10_not_median(threshold_config):
    # median date OUTSIDE the 30d window, but P10 (earliest-credible) INSIDE -> alert must fire.
    est = _make_estimate(p_cross=0.05, rul_median=200, p10_days=20, median_days=45)
    risk = _risk("VN-A3", "mlg_r_inbd", "SGN", 2, 3.0, est)
    alerts = scoring.wear_out_alerts(risk, threshold_config, AS_OF)
    types = {a.alert_type for a in alerts}
    assert AlertType.EARLIEST_DATE_IN_WINDOW.value in types


def test_no_wear_out_alert_when_p10_outside_window(threshold_config):
    est = _make_estimate(p_cross=0.0, rul_median=400, p10_days=120, median_days=150)
    risk = _risk("VN-A4", "mlg_r_inbd", "SGN", 3, 3.0, est)
    alerts = scoring.wear_out_alerts(risk, threshold_config, AS_OF)
    assert all(a.alert_type != AlertType.EARLIEST_DATE_IN_WINDOW.value for a in alerts)


def test_low_confidence_suppresses_wear_out_alert(threshold_config):
    est = _make_estimate(p_cross=0.9, rul_median=10, p10_days=5, median_days=8, low_conf=True)
    risk = _risk("VN-A5", "mlg_r_inbd", "SGN", 0, 5.0, est)
    assert scoring.wear_out_alerts(risk, threshold_config, AS_OF) == []


def test_alert_categories_are_separated(threshold_config):
    est = _make_estimate(p_cross=0.5, rul_median=15, p10_days=10, median_days=14)
    # pressure 85% -> deterministic remove; plus an in-window wear-out alert
    risk = _risk("VN-A6", "mlg_l_inbd", "SGN", 0, 5.0, est, pressure_pct=85.0)
    bundle = scoring.evaluate_alerts([risk], [], threshold_config, AS_OF)
    assert all(a.category == AlertCategory.WEAR_OUT.value for a in bundle.wear_out)
    assert all(a.category == AlertCategory.EVENT_DRIVEN.value for a in bundle.event_driven)
    assert any(a.alert_type == AlertType.PRESSURE_LADDER.value for a in bundle.event_driven)
    assert any(a.alert_type == AlertType.EARLIEST_DATE_IN_WINDOW.value for a in bundle.wear_out)
    # a pressure rule never leaks into the wear-out list
    assert all(a.alert_type != AlertType.PRESSURE_LADDER.value for a in bundle.wear_out)


# ---------------------------------------------------------------------------
# Spares demand
# ---------------------------------------------------------------------------
def test_spares_flags_stockout_week(threshold_config):
    # 5 wheels whose earliest-credible (P10) crossing dates land in week 3 at SGN; stock = 3.
    risks = []
    for i in range(5):
        est = _make_estimate(p_cross=0.4, rul_median=70, p10_days=21, median_days=24)
        risks.append(_risk(f"VN-S{i}", "mlg_l_inbd", "SGN", 3, 4.0, est))
    demand = scoring.spares_demand(risks, {"SGN": 3}, AS_OF, weeks=12)
    sgn = [d for d in demand if d.station == "SGN"]
    # expected demand never exceeds the conservative P90 demand
    assert all(d.expected_demand <= d.p90_demand for d in sgn)
    # a stock-out is projected once cumulative demand (5) exceeds stock (3)
    assert any(d.projected_stockout for d in sgn)
    # week 0 (nothing due yet) is not a stock-out
    assert not sgn[0].projected_stockout


def test_wear_rate_accelerating():
    assert scoring.wear_rate_accelerating(0.05, 0.035, 0.30) is True  # +43% > 30%
    assert scoring.wear_rate_accelerating(0.04, 0.035, 0.30) is False  # +14% < 30%
    assert scoring.wear_rate_accelerating(0.05, float("nan"), 0.30) is False


# ---------------------------------------------------------------------------
# Tire status report
# ---------------------------------------------------------------------------
def test_status_report_healthy(threshold_config):
    est = _make_estimate(p_cross=0.0, rul_median=250, p10_days=200, median_days=210)
    r = _risk("VN-H", "mlg_l_inbd", "HAN", 5, 3.0, est, pressure_pct=100.0, pressure_action="ok")
    rep = scoring.tire_status_report(r, threshold_config, AS_OF)
    assert rep.status == "healthy"
    assert abs(rep.rul_days - 250 / 3.0) < 1.0  # RUL landings / utilization


def test_status_report_damage_forces_replace(threshold_config):
    est = _make_estimate(p_cross=0.0, rul_median=250, p10_days=200, median_days=210)
    r = _risk("VN-D", "mlg_l_inbd", "HAN", 5, 3.0, est, pressure_pct=100.0)
    rep = scoring.tire_status_report(r, threshold_config, AS_OF, damage_findings=["cut", "bulge"])
    assert rep.status == "replace_now"
    assert "cut" in rep.explanation  # CV finding surfaced in the report


def test_status_report_pressure_remove(threshold_config):
    est = _make_estimate(p_cross=0.0, rul_median=250, p10_days=200, median_days=210)
    r = _risk("VN-P", "mlg_l_inbd", "HAN", 5, 3.0, est, pressure_pct=85.0, pressure_action="remove")
    rep = scoring.tire_status_report(r, threshold_config, AS_OF)
    assert rep.status == "replace_now"


def test_status_report_schedule(threshold_config):
    est = _make_estimate(p_cross=0.5, rul_median=40, p10_days=15, median_days=18)
    r = _risk("VN-S", "mlg_l_inbd", "SGN", 0, 4.0, est, pressure_pct=100.0)
    rep = scoring.tire_status_report(r, threshold_config, AS_OF)
    assert rep.status == "schedule"
    assert "Schedule" in rep.recommended_action
