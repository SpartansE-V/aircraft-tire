"""scoring.py — the portable brain (pure functions, no I/O, no Streamlit).

Everything the product decides lives here as pure functions so it can be lifted behind a
FastAPI service later without a rewrite. Given a population degradation *prior* (learned by
train.py) plus a tire's own inspection readings, this module:

  * forms an empirical-Bayes per-tire wear posterior (works for data-rich and data-poor tires),
  * runs a Monte-Carlo first-passage to the 2.0 mm limit to get RUL + wear-to-limit dates,
  * scores per-wheel priority as P(cross before next check) x consequence (NOT a raw RUL sort),
  * rolls per-wheel crossing dates into weekly station spares demand, and
  * evaluates a DUAL alert engine: probabilistic wear-out alerts (fired on the conservative
    P10 lower bound, never the median) kept SEPARATE from deterministic FAA/Goodyear rules.

Design invariants enforced here:
  - wear-out alerts use the P10 (earliest-credible) date, never the median;
  - wear-out (model) alerts and event-driven (rule) alerts are returned in separate lists;
  - low-confidence tires (few readings) get a wide band and are labelled, never a tight number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .config import PressureBand, PriorityWeights, ThresholdConfig
from .constants import (
    AlertCategory,
    AlertType,
    PressureLadderAction,
    Severity,
)

# A crossing that never happens (non-wearing MC draw) is capped to this many cycles for quantiles.
NEVER_CROSS_CYCLES = 5000.0
MAX_HORIZON_DAYS = 3650


# ---------------------------------------------------------------------------
# Degradation posterior + Monte-Carlo first passage
# ---------------------------------------------------------------------------
def eb_posterior(
    cycles: np.ndarray,
    grooves: np.ndarray,
    prior_mean: np.ndarray,
    prior_cov: np.ndarray,
    scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Empirical-Bayes posterior over the wear line (intercept, slope) for one tire.

    Bayesian linear regression: groove = intercept + slope * cycles + eps, eps ~ N(0, scale),
    with prior beta ~ N(prior_mean, prior_cov) from the fitted population model. A tire with 0
    readings returns the prior; more readings pull the posterior toward the tire's own data.
    """
    prior_mean = np.asarray(prior_mean, dtype=float)
    prior_cov = np.asarray(prior_cov, dtype=float)
    lam0 = np.linalg.inv(prior_cov)
    x = np.asarray(cycles, dtype=float)
    y = np.asarray(grooves, dtype=float)
    if x.size == 0:
        return prior_mean.copy(), prior_cov.copy()
    design = np.column_stack([np.ones_like(x), x])
    scale = max(float(scale), 1e-6)
    lam_n = lam0 + (design.T @ design) / scale
    cov_n = np.linalg.inv(lam_n)
    mean_n = cov_n @ (lam0 @ prior_mean + (design.T @ y) / scale)
    return mean_n, cov_n


def predict_wear_line(intercept: float, slope: float, cycles: np.ndarray) -> np.ndarray:
    return intercept + slope * np.asarray(cycles, dtype=float)


def prior_arrays(prior: dict, position_code: str) -> tuple[np.ndarray, np.ndarray, float]:
    """Pull (prior_mean, prior_cov, scale) for a wheel position out of a persisted prior dict."""
    positions = prior["positions"]
    pos = positions.get(position_code) or positions[prior["baseline_position"]]
    mean = np.array([pos["intercept"], pos["slope"]], dtype=float)
    cov = np.array(prior["cov_re"], dtype=float)
    return mean, cov, float(prior["scale"])


def monte_carlo_crossing(
    mean: np.ndarray,
    cov: np.ndarray,
    limit_mm: float,
    n_draws: int,
    seed: int,
) -> np.ndarray:
    """Draw (intercept, slope) samples and solve the cycle where each wear line hits the limit.

    Non-wearing draws (slope >= 0) never cross and are returned as +inf.
    """
    rng = np.random.default_rng(seed)
    mean = np.asarray(mean, dtype=float)
    cov = np.asarray(cov, dtype=float)
    cov = 0.5 * (cov + cov.T) + np.eye(2) * 1e-10  # symmetrize + tiny jitter for PD safety
    try:
        chol = np.linalg.cholesky(cov)  # lower-triangular
    except np.linalg.LinAlgError:  # fall back to an eigen-clip factor if not quite PD
        w, vecs = np.linalg.eigh(cov)
        chol = vecs @ np.diag(np.sqrt(np.clip(w, 1e-12, None)))
    z = rng.standard_normal((int(n_draws), 2))
    # Component-wise affine transform (avoids numpy 2.0's spurious matmul FPE warnings on 2x2).
    b0 = mean[0] + z[:, 0] * chol[0, 0] + z[:, 1] * chol[0, 1]
    b1 = mean[1] + z[:, 0] * chol[1, 0] + z[:, 1] * chol[1, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        crossing = (limit_mm - b0) / b1
    crossing = np.where(b1 < -1e-9, crossing, np.inf)  # only wearing draws cross
    crossing = np.where(crossing >= 0, crossing, 0.0)  # a past crossing means already overdue
    return crossing


@dataclass(frozen=True)
class TireRulEstimate:
    rul_p10: float
    rul_median: float
    rul_p90: float
    rul_mean: float
    crossing_median_cycle: float
    p_cross_next_check: float
    frac_never: float
    date_p10: date
    date_median: date
    date_p90: date
    landings_per_day: float
    low_confidence: bool
    intercept: float
    slope: float


def _rul_quantiles(crossings: np.ndarray, current_cycles: float) -> dict:
    rul = crossings - float(current_cycles)
    rul = np.where(np.isfinite(rul), np.clip(rul, 0.0, None), NEVER_CROSS_CYCLES)
    return {
        "p10": float(np.percentile(rul, 10)),
        "median": float(np.percentile(rul, 50)),
        "p90": float(np.percentile(rul, 90)),
        "mean": float(np.mean(rul)),
        "frac_never": float(np.mean(~np.isfinite(crossings))),
    }


def _cycles_to_date(as_of: date, rul_cycles: float, landings_per_day: float) -> date:
    lpd = max(float(landings_per_day), 1e-6)
    days = min(rul_cycles / lpd, MAX_HORIZON_DAYS)
    return as_of + timedelta(days=float(days))


def estimate_wheel(
    cycles: np.ndarray,
    grooves: np.ndarray,
    prior_mean: np.ndarray,
    prior_cov: np.ndarray,
    scale: float,
    *,
    current_cycles: float,
    landings_per_day: float,
    as_of_date: date,
    limit_mm: float,
    mc_draws: int,
    mc_seed: int,
    next_check_cycles: int,
    n_readings: int,
    low_confidence_min_readings: int,
) -> TireRulEstimate:
    """End-to-end per-wheel RUL + wear-to-limit dates + P(cross before next check)."""
    mean, cov = eb_posterior(cycles, grooves, prior_mean, prior_cov, scale)
    crossings = monte_carlo_crossing(mean, cov, limit_mm, mc_draws, mc_seed)
    q = _rul_quantiles(crossings, current_cycles)
    p_cross = p_cross_within(crossings, current_cycles, next_check_cycles)
    finite = crossings[np.isfinite(crossings)]
    crossing_median = float(np.percentile(finite, 50)) if finite.size else float("inf")
    return TireRulEstimate(
        rul_p10=q["p10"],
        rul_median=q["median"],
        rul_p90=q["p90"],
        rul_mean=q["mean"],
        crossing_median_cycle=crossing_median,
        p_cross_next_check=p_cross,
        frac_never=q["frac_never"],
        # earliest-credible RUL (p10) -> earliest date; largest RUL (p90) -> latest date
        date_p10=_cycles_to_date(as_of_date, q["p10"], landings_per_day),
        date_median=_cycles_to_date(as_of_date, q["median"], landings_per_day),
        date_p90=_cycles_to_date(as_of_date, q["p90"], landings_per_day),
        landings_per_day=float(landings_per_day),
        low_confidence=n_readings < low_confidence_min_readings,
        intercept=float(mean[0]),
        slope=float(mean[1]),
    )


def p_cross_within(crossings: np.ndarray, current_cycles: float, horizon_cycles: float) -> float:
    """P(the wear line crosses the limit within `horizon_cycles` of the current cycle)."""
    target = float(current_cycles) + float(horizon_cycles)
    return float(np.mean(crossings <= target))


def wear_rate_accelerating(recent_rate: float, baseline_rate: float, threshold: float) -> bool:
    """True if the tire's recent wear rate exceeds its own baseline by > threshold (e.g. 30%)."""
    if baseline_rate is None or np.isnan(baseline_rate) or baseline_rate <= 0:
        return False
    if recent_rate is None or np.isnan(recent_rate):
        return False
    return (recent_rate - baseline_rate) / baseline_rate > threshold


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------
def consequence_weight(
    position_code: str,
    cycles_per_day: float,
    station_on_hand: int,
    weights: PriorityWeights,
    *,
    hard_landing_recent: bool = False,
    pressure_rule_active: bool = False,
    util_ref: float = 6.0,
    stock_ref: float = 5.0,
) -> float:
    """Blend AOG-exposure (utilization), position criticality, and spare scarcity into a weight."""
    crit = float(weights.position_criticality.get(position_code, 1.0))
    util_norm = float(np.clip(cycles_per_day / util_ref, 0.0, 1.0))
    spare_shortage = float(np.clip(1.0 - station_on_hand / stock_ref, 0.0, 1.0))
    base = 1.0 + weights.utilization_weight * util_norm + weights.spare_shortage_weight * spare_shortage
    if hard_landing_recent:
        base *= weights.hard_landing_multiplier
    if pressure_rule_active:
        base *= weights.pressure_ladder_multiplier
    return crit * base


def priority_score(p_cross_before_next_check: float, consequence: float) -> float:
    """Priority = probability x consequence. Deliberately NOT a raw RUL sort."""
    return float(p_cross_before_next_check) * float(consequence)


@dataclass
class WheelRisk:
    """Per-wheel bundle used to build the worklist and alerts."""

    aircraft_id: str
    tail_number: str
    position_code: str
    station: str
    on_hand: int
    cycles_per_day: float
    estimate: TireRulEstimate
    hard_landings_recent: int = 0
    pressure_pct: float | None = None
    pressure_action: str = PressureLadderAction.OK.value
    recent_wear_rate: float | None = None
    baseline_wear_rate: float | None = None


@dataclass
class WorklistRow:
    rank: int
    tail_number: str
    position_code: str
    priority: float
    p_cross_next_check: float
    rul_median: float
    rul_p10: float
    earliest_date: date
    low_confidence: bool
    reason: str
    action: str


def _reason_and_action(risk: WheelRisk, tc: ThresholdConfig) -> tuple[str, str]:
    est = risk.estimate
    bits = [f"P(cross before next check)={est.p_cross_next_check:.0%}"]
    if risk.cycles_per_day >= 4.0:
        bits.append(f"high utilization ({risk.cycles_per_day:.1f}/day)")
    if risk.on_hand == 0:
        bits.append(f"0 spares at {risk.station}")
    elif risk.on_hand <= 2:
        bits.append(f"only {risk.on_hand} spares at {risk.station}")
    if risk.pressure_action in (PressureLadderAction.REMOVE.value, PressureLadderAction.REMOVE_TIRE_AND_MATE.value):
        bits.append("pressure-ladder removal flag")
    if wear_rate_accelerating(risk.recent_wear_rate, risk.baseline_wear_rate, tc.wear_accel_threshold):
        bits.append("wear rate accelerating")
    if est.low_confidence:
        bits.append("fleet prior — low confidence")

    if risk.pressure_action in (PressureLadderAction.REMOVE.value, PressureLadderAction.REMOVE_TIRE_AND_MATE.value):
        action = "Remove now (pressure)"
    elif est.p_cross_next_check >= tc.p_cross_threshold:
        action = f"Schedule removal (~{est.rul_p10:.0f} cyc earliest)"
    elif (est.date_p10 - _today_from(est)).days <= tc.planning_window_days:
        action = "Pre-position spare"
    else:
        action = "Monitor"
    return "; ".join(bits), action


def _today_from(est: TireRulEstimate) -> date:
    """Recover the as-of date: date_p10 is as_of + p10_rul/lpd, so back it out."""
    return est.date_p10 - timedelta(days=min(est.rul_p10 / max(est.landings_per_day, 1e-6), MAX_HORIZON_DAYS))


def build_worklist(risks: list[WheelRisk], tc: ThresholdConfig) -> list[WorklistRow]:
    """Rank wheels by composite priority (probability x consequence) and attach reasons."""
    scored = []
    for r in risks:
        cons = consequence_weight(
            r.position_code,
            r.cycles_per_day,
            r.on_hand,
            tc.priority,
            hard_landing_recent=r.hard_landings_recent > 0,
            pressure_rule_active=r.pressure_action
            in (PressureLadderAction.REMOVE.value, PressureLadderAction.REMOVE_TIRE_AND_MATE.value),
        )
        pr = priority_score(r.estimate.p_cross_next_check, cons)
        scored.append((pr, r))
    scored.sort(key=lambda t: t[0], reverse=True)

    rows: list[WorklistRow] = []
    for i, (pr, r) in enumerate(scored, start=1):
        reason, action = _reason_and_action(r, tc)
        rows.append(
            WorklistRow(
                rank=i,
                tail_number=r.tail_number,
                position_code=r.position_code,
                priority=pr,
                p_cross_next_check=r.estimate.p_cross_next_check,
                rul_median=r.estimate.rul_median,
                rul_p10=r.estimate.rul_p10,
                earliest_date=r.estimate.date_p10,
                low_confidence=r.estimate.low_confidence,
                reason=reason,
                action=action,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Spares demand
# ---------------------------------------------------------------------------
@dataclass
class WeekDemand:
    station: str
    week_start: date
    expected_demand: float
    p90_demand: float
    on_hand: int
    projected_stockout: bool


def spares_demand(
    risks: list[WheelRisk],
    on_hand_by_station: dict[str, int],
    as_of_date: date,
    weeks: int = 12,
) -> list[WeekDemand]:
    """Roll per-wheel crossing dates into weekly removal demand per station vs on-hand stock.

    Expected demand uses each wheel's median wear-to-limit date; P90 (conservative planning)
    uses the earliest-credible P10 date (earlier -> sooner demand). A running cumulative
    balance flags the first week each station is projected to run out.
    """
    week_starts = [as_of_date + timedelta(weeks=w) for w in range(weeks)]
    stations = sorted(on_hand_by_station)
    exp = {s: np.zeros(weeks) for s in stations}
    p90 = {s: np.zeros(weeks) for s in stations}

    for r in risks:
        s = r.station
        if s not in exp:
            continue
        wk_exp = _week_index(r.estimate.date_median, as_of_date, weeks)
        wk_p90 = _week_index(r.estimate.date_p10, as_of_date, weeks)  # earlier date -> conservative
        if wk_exp is not None:
            exp[s][wk_exp] += 1.0
        if wk_p90 is not None:
            p90[s][wk_p90] += 1.0

    out: list[WeekDemand] = []
    for s in stations:
        stock = int(on_hand_by_station[s])
        cum_p90 = 0.0
        for w in range(weeks):
            cum_p90 += p90[s][w]
            out.append(
                WeekDemand(
                    station=s,
                    week_start=week_starts[w],
                    expected_demand=float(exp[s][w]),
                    p90_demand=float(p90[s][w]),
                    on_hand=stock,
                    projected_stockout=cum_p90 > stock,
                )
            )
    return out


def _week_index(d: date, as_of: date, weeks: int) -> int | None:
    delta_days = (d - as_of).days
    if delta_days < 0:
        return 0
    w = delta_days // 7
    if w >= weeks:
        return None
    return int(w)


# ---------------------------------------------------------------------------
# Alerts — dual engine (wear-out model alerts vs deterministic rules)
# ---------------------------------------------------------------------------
@dataclass
class Alert:
    category: str  # AlertCategory
    alert_type: str  # AlertType
    severity: str  # Severity
    tail_number: str
    position_code: str
    message: str


def pressure_ladder_action(pressure_pct: float, bands: tuple[PressureBand, ...]) -> str:
    """Return the Goodyear/FAA action for a cold-pressure reading (% of service pressure).

    Bands are evaluated in order; the first whose [min_pct, max_pct) contains the reading wins.
    """
    for b in bands:
        if b.min_pct <= pressure_pct < b.max_pct:
            return b.action
    # below the lowest band -> most severe
    return PressureLadderAction.REMOVE_TIRE_AND_MATE.value


_PRESSURE_SEVERITY = {
    PressureLadderAction.OK.value: Severity.INFO.value,
    PressureLadderAction.REINFLATE.value: Severity.INFO.value,
    PressureLadderAction.INSPECT.value: Severity.WARNING.value,
    PressureLadderAction.REMOVE.value: Severity.CRITICAL.value,
    PressureLadderAction.REMOVE_TIRE_AND_MATE.value: Severity.CRITICAL.value,
}


def wear_out_alerts(risk: WheelRisk, tc: ThresholdConfig, as_of_date: date) -> list[Alert]:
    """Probabilistic model alerts. ALWAYS fire on the P10 (earliest-credible) bound, never median."""
    est = risk.estimate
    alerts: list[Alert] = []
    if est.low_confidence:
        return alerts  # never emit a hard wear-out alert on a low-confidence fleet-prior tire

    earliest_days = (est.date_p10 - as_of_date).days
    if 0 <= earliest_days <= tc.planning_window_days:
        alerts.append(
            Alert(
                AlertCategory.WEAR_OUT.value,
                AlertType.EARLIEST_DATE_IN_WINDOW.value,
                Severity.CRITICAL.value if earliest_days <= tc.planning_window_days / 2 else Severity.WARNING.value,
                risk.tail_number,
                risk.position_code,
                f"Earliest-credible wear-to-limit date {est.date_p10.isoformat()} "
                f"({earliest_days}d) is inside the {tc.planning_window_days}d planning window.",
            )
        )
    if est.p_cross_next_check >= tc.p_cross_threshold:
        alerts.append(
            Alert(
                AlertCategory.WEAR_OUT.value,
                AlertType.P_CROSS_HIGH.value,
                Severity.WARNING.value,
                risk.tail_number,
                risk.position_code,
                f"P(cross limit before next check) = {est.p_cross_next_check:.0%} "
                f"(threshold {tc.p_cross_threshold:.0%}).",
            )
        )
    if wear_rate_accelerating(risk.recent_wear_rate, risk.baseline_wear_rate, tc.wear_accel_threshold):
        alerts.append(
            Alert(
                AlertCategory.WEAR_OUT.value,
                AlertType.WEAR_ACCEL.value,
                Severity.WARNING.value,
                risk.tail_number,
                risk.position_code,
                f"Wear rate {risk.recent_wear_rate:.4f} mm/cyc is >"
                f"{tc.wear_accel_threshold:.0%} above baseline {risk.baseline_wear_rate:.4f}.",
            )
        )
    return alerts


def event_driven_alerts(risk: WheelRisk, tc: ThresholdConfig) -> list[Alert]:
    """Deterministic, standards-grounded rules (day-one, no model needed)."""
    alerts: list[Alert] = []
    if risk.pressure_pct is not None:
        action = pressure_ladder_action(risk.pressure_pct, tc.pressure_bands)
        if action != PressureLadderAction.OK.value:
            alerts.append(
                Alert(
                    AlertCategory.EVENT_DRIVEN.value,
                    AlertType.PRESSURE_LADDER.value,
                    _PRESSURE_SEVERITY.get(action, Severity.WARNING.value),
                    risk.tail_number,
                    risk.position_code,
                    f"Cold pressure {risk.pressure_pct:.0f}% of service -> action: {action.replace('_', ' ')}"
                    + (" (also remove mate)" if action == PressureLadderAction.REMOVE_TIRE_AND_MATE.value else ""),
                )
            )
    return alerts


def stockout_alerts(demand: list[WeekDemand]) -> list[Alert]:
    """Station-level projected stock-out alerts (wear-out category, aggregate)."""
    seen: set[str] = set()
    alerts: list[Alert] = []
    for wd in demand:
        if wd.projected_stockout and wd.station not in seen:
            seen.add(wd.station)
            alerts.append(
                Alert(
                    AlertCategory.WEAR_OUT.value,
                    AlertType.STATION_STOCKOUT.value,
                    Severity.WARNING.value,
                    "-",
                    "-",
                    f"Station {wd.station}: projected spare stock-out around week of "
                    f"{wd.week_start.isoformat()} (on-hand {wd.on_hand}).",
                )
            )
    return alerts


@dataclass
class AlertBundle:
    wear_out: list[Alert] = field(default_factory=list)
    event_driven: list[Alert] = field(default_factory=list)


def evaluate_alerts(
    risks: list[WheelRisk],
    demand: list[WeekDemand],
    tc: ThresholdConfig,
    as_of_date: date,
) -> AlertBundle:
    """Full dual alert engine. Wear-out (probabilistic) and event-driven (deterministic) are
    returned in SEPARATE lists and never blended."""
    bundle = AlertBundle()
    for r in risks:
        bundle.wear_out.extend(wear_out_alerts(r, tc, as_of_date))
        bundle.event_driven.extend(event_driven_alerts(r, tc))
    bundle.wear_out.extend(stockout_alerts(demand))
    return bundle


# ---------------------------------------------------------------------------
# Tire status report ("Trạng thái lốp": condition + explanation + how-much-longer)
# ---------------------------------------------------------------------------
@dataclass
class StatusReport:
    status: str  # healthy / monitor / schedule / replace_now
    severity: str  # Severity value
    headline: str  # "Serviceable for ~N more landings (~D days)"
    explanation: str  # plain-language "why"
    rul_landings: float
    rul_days: float
    recommended_action: str


def tire_status_report(
    risk: WheelRisk,
    tc: ThresholdConfig,
    as_of_date: date,
    damage_findings: list[str] | None = None,
) -> StatusReport:
    """Unified tire condition + RUL report. `damage_findings` is the hook for the future CV
    layer (VLM/depth) — e.g. ["cut", "bulge", "FOD"]; when present, it forces a removal status."""
    e = risk.estimate
    lpd = max(risk.cycles_per_day, 1e-6)
    rul_days = e.rul_median / lpd
    earliest_days = (e.date_p10 - as_of_date).days
    damage_findings = damage_findings or []
    pressure_remove = risk.pressure_action in (
        PressureLadderAction.REMOVE.value,
        PressureLadderAction.REMOVE_TIRE_AND_MATE.value,
    )
    accel = wear_rate_accelerating(risk.recent_wear_rate, risk.baseline_wear_rate, tc.wear_accel_threshold)

    if damage_findings or pressure_remove or e.rul_median <= 5:
        status, severity = "replace_now", Severity.CRITICAL.value
        action = "Replace before next dispatch."
    elif (0 <= earliest_days <= tc.planning_window_days) or e.p_cross_next_check >= tc.p_cross_threshold:
        status, severity = "schedule", Severity.WARNING.value
        action = f"Schedule replacement within ~{e.rul_p10:.0f} landings (by {e.date_p10.isoformat()})."
    elif accel or e.low_confidence:
        status, severity = "monitor", Severity.WARNING.value
        action = "Re-inspect at next scheduled check."
    else:
        status, severity = "healthy", Severity.INFO.value
        action = "No action — within limits."

    headline = (
        f"Serviceable for ~{e.rul_median:.0f} more landings (~{rul_days:.0f} days); "
        f"earliest-credible limit {e.date_p10.isoformat()}."
    )

    bits = [f"Estimated remaining tread life {e.rul_median:.0f} landings (earliest-credible {e.rul_p10:.0f})."]
    if damage_findings:
        bits.append("Image inspection flagged: " + ", ".join(damage_findings) + ".")
    if pressure_remove:
        bits.append(f"Cold pressure {risk.pressure_pct:.0f}% of service triggers a pressure-ladder removal.")
    elif risk.pressure_pct is not None and risk.pressure_action != PressureLadderAction.OK.value:
        bits.append(f"Cold pressure {risk.pressure_pct:.0f}% → {risk.pressure_action.replace('_', ' ')}.")
    if accel:
        bits.append(
            f"Wear rate accelerating (~{risk.recent_wear_rate:.3f} vs baseline "
            f"{risk.baseline_wear_rate:.3f} mm/landing) — under-inflation signature."
        )
    if e.low_confidence:
        bits.append("Few readings — using the fleet prior (low confidence).")
    if risk.on_hand == 0:
        bits.append(f"No spare of this size on hand at {risk.station}.")

    return StatusReport(
        status=status,
        severity=severity,
        headline=headline,
        explanation=" ".join(bits),
        rul_landings=e.rul_median,
        rul_days=rul_days,
        recommended_action=action,
    )
