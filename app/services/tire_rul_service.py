"""RUL prediction service — the backend's only bridge into the app.tire_rul model package.

The FastAPI layer (routes + domain schemas) stays free of ML concerns; this module owns the
translation between the public TireRulPredictionRequest/Response contract and app.tire_rul.scoring,
the pure-numpy degradation brain (empirical-Bayes posterior + Monte-Carlo first passage).
"""

from __future__ import annotations

import pickle
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

import numpy as np

from app.domain.schemas import (
    NGAFID_REF_IAS_KT,
    NGAFID_REF_NORMAC_G,
    NGAFID_REF_OAT_C,
    NGAFID_REF_VSPD_FPM,
    TireRulPredictionRequest,
    TireRulPredictionResponse,
    TireRulQuantiles,
    TireRulStatus,
    WearToLimitDates,
)
from app.tire_rul import paths, scoring
from app.tire_rul.config import ThresholdConfig, get_threshold_config

DISCLAIMER = (
    "Decision-support estimate for inspection planning only. It prioritizes within existing "
    "maintenance limits and does not replace physical inspection, aircraft maintenance manuals, "
    "or qualified engineering approval."
)


def _wear_exposure_multiplier(request: TireRulPredictionRequest) -> float:
    """Combine normalized flight factors with wheel-position sensitivities.

    Exponents prevent double-counting correlated factors and encode physical allocation: braking
    loads the mains most, taxi steering loads the nose, and crosswind/lateral exposure loads the
    outboard mains most. The safety bound avoids an implausible product dominating the posterior.
    """

    c = request.flight_conditions
    is_nose = request.position.startswith("nlg")
    is_outboard = request.position.endswith("outbd")
    braking_weight = 0.35 if is_nose else 1.0
    taxi_weight = 1.0 if is_nose else 0.55
    crosswind_weight = 0.4 if is_nose else (1.0 if is_outboard else 0.6)
    multiplier = (
        c.landing_load_factor
        * c.braking_energy_factor**braking_weight
        * c.takeoff_severity_factor**0.45
        * c.taxi_heat_factor**taxi_weight
        * c.temperature_factor**0.35
        * c.inflation_factor
        * c.runway_roughness_factor**0.6
        * c.hard_landing_factor
        * c.crosswind_factor**crosswind_weight
    )
    return float(np.clip(multiplier, 0.25, 6.0))


# True (and ground) speed climbs ~2% per 1000 ft of field elevation for the same indicated
# airspeed (thin air). Mirrors web/src/sim.ts CAL.tasPctPer1000ft so the RUL planner and the
# 3D landing model derive touchdown speed identically.
_TAS_PCT_PER_1000FT = 2.0


def _ngafid_sensor_multiplier(request: TireRulPredictionRequest) -> float:
    """Convert raw NGAFID FDR sensors into a position-weighted tire-wear multiplier.

    Only the five NGAFID sensors that physically drive tire wear are used — IAS, VSpd, NormAc,
    OAT and AltMSL. The electrical/engine/CHT/EGT channels describe powerplant and avionics health
    and never touch the tire. Fuel quantity (FQtyL/R) is excluded too: gross weight would scale the
    absolute touchdown load, but fuel is only a partial weight proxy (it ignores payload / zero-fuel
    weight) and per-cycle gross weight is not part of this planning contract, so the measured NormAc
    load factor is used as the vertical-load signal instead.

    The speed physics is taken straight from the landing simulator (web/src/sim.ts, tuned for this
    widebody fleet) so the planner and the 3D model agree there:

      * spin-up scrub grows with the square of true ground speed, and field elevation raises true
        speed ~2%/1000 ft for the same indicated airspeed (IAS + AltMSL).

    The vertical-load and thermal terms are bounded planning heuristics — NOT lifted from sim.ts,
    which derives its single load factor from sink alone and uses OAT only for brake/bead heat:

      * tire peak load scales with the measured touchdown load factor (NormAc), where 1.0 g is the
        static design load. NormAc is the primary vertical-load signal; VSpd only nudges it within a
        narrow band, because NGAFID samples NormAc at 1 Hz and can undersample the sub-second
        touchdown spike that the sink rate still reflects. VSpd's contribution is clamped to a small
        range so the two do not fully double-count.
      * hotter air (OAT) wears the tread faster (a modest, bounded assumption).

    Nose tires steer rather than absorb the landing impact, so the speed and load terms are
    down-weighted for nose positions. Returns 1.0 when no sensor block was supplied.
    """
    sensors = request.flight_sensors
    if sensors is None:
        return 1.0

    is_nose = request.position.startswith("nlg")

    # Thin air makes the same indicated airspeed a faster true arrival — and scrub goes with v².
    true_gs_kt = sensors.indicated_airspeed_kt * (
        1.0 + (_TAS_PCT_PER_1000FT / 100.0) * (sensors.altitude_msl_ft / 1000.0)
    )
    speed_term = (true_gs_kt / NGAFID_REF_IAS_KT) ** 2  # spin-up scrub ∝ true-ground-speed²
    load_term = sensors.normal_acceleration_g / NGAFID_REF_NORMAC_G  # tire peak load ∝ landing g
    # VSpd is only a minor nudge on top of NormAc (they measure the same impact), so it is clamped
    # to a narrow band. The floor also stops a low/zero sink reading (0**0.25 == 0) from collapsing
    # the whole product.
    sink_ratio = max(sensors.vertical_speed_fpm, 0.0) / NGAFID_REF_VSPD_FPM
    sink_term = float(np.clip(sink_ratio**0.25, 0.85, 1.25))
    # Warmer rubber wears faster; kept a modest, bounded effect.
    temp_term = float(
        np.clip(1.0 + 0.006 * (sensors.outside_air_temperature_c - NGAFID_REF_OAT_C), 0.85, 1.25)
    )

    speed_weight = 0.5 if is_nose else 1.0
    load_weight = 0.4 if is_nose else 1.0
    sink_weight = 0.4 if is_nose else 1.0

    multiplier = (
        speed_term**speed_weight * load_term**load_weight * sink_term**sink_weight * temp_term
    )
    return float(np.clip(multiplier, 0.25, 6.0))


@lru_cache(maxsize=1)
def _load_prior() -> dict[str, Any]:
    """Load the fitted population degradation prior (per-position params + covariance + scale)."""

    with open(paths.MIXEDLM_COV, "rb") as prior_file:
        prior: dict[str, Any] = pickle.load(prior_file)
    return prior


@lru_cache(maxsize=1)
def _load_thresholds() -> ThresholdConfig:
    """Load the scoring thresholds (wear limit, MC draws, next-check interval, ...)."""

    return get_threshold_config()


class TireRulService:
    """Serve remaining-useful-life forecasts from the fitted prior plus a tire's own readings."""

    def predict(self, request: TireRulPredictionRequest) -> TireRulPredictionResponse:
        prior = _load_prior()
        thresholds = _load_thresholds()
        as_of = request.as_of_date or datetime.now(UTC).date()

        cycles = np.array([r.cycles_since_install for r in request.readings], dtype=float)
        grooves = np.array([r.measured_groove_mm for r in request.readings], dtype=float)
        n_readings = len(request.readings)
        factor_multiplier = _wear_exposure_multiplier(request)
        sensor_multiplier = _ngafid_sensor_multiplier(request)
        # Combine the abstract wear factors with the raw-sensor exposure, then re-bound the product
        # so an extreme pairing cannot dominate the posterior.
        exposure_multiplier = float(np.clip(factor_multiplier * sensor_multiplier, 0.25, 6.0))
        effective_planned_landings = request.planned_landings * exposure_multiplier

        prior_mean, prior_cov, scale = scoring.prior_arrays(prior, request.position)
        estimate = scoring.estimate_wheel(
            cycles,
            grooves,
            prior_mean,
            prior_cov,
            scale,
            current_cycles=request.current_cycles + effective_planned_landings,
            landings_per_day=request.landings_per_day,
            as_of_date=as_of,
            limit_mm=thresholds.wear_limit_mm,
            mc_draws=thresholds.mc_draws,
            mc_seed=thresholds.mc_seed,
            next_check_cycles=thresholds.next_check_interval_cycles,
            n_readings=n_readings,
            low_confidence_min_readings=thresholds.low_confidence_min_readings,
        )

        risk = scoring.WheelRisk(
            aircraft_id="",
            tail_number="",
            position_code=request.position,
            station="",
            on_hand=0,
            cycles_per_day=request.landings_per_day,
            estimate=estimate,
        )
        report = scoring.tire_status_report(risk, thresholds, as_of)

        return TireRulPredictionResponse(
            prediction_id=uuid4(),
            position=request.position,
            rul_landings=TireRulQuantiles(
                p10=round(estimate.rul_p10, 1),
                median=round(estimate.rul_median, 1),
                p90=round(estimate.rul_p90, 1),
                mean=round(estimate.rul_mean, 1),
            ),
            wear_to_limit_dates=WearToLimitDates(
                earliest_credible_p10=estimate.date_p10,
                median=estimate.date_median,
                p90=estimate.date_p90,
            ),
            p_cross_before_next_check=round(estimate.p_cross_next_check, 4),
            landings_per_day=request.landings_per_day,
            wear_exposure_multiplier=round(exposure_multiplier, 3),
            sensor_wear_multiplier=round(sensor_multiplier, 3),
            effective_planned_landings=round(effective_planned_landings, 1),
            readings_used=n_readings,
            low_confidence=estimate.low_confidence,
            status=TireRulStatus(
                status=report.status,
                severity=report.severity,
                headline=report.headline,
                recommended_action=report.recommended_action,
            ),
            wear_limit_mm=thresholds.wear_limit_mm,
            model_version=f"rul-mixedlm-{prior.get('version', 'unknown')}",
            disclaimer=DISCLAIMER,
        )


tire_rul_service = TireRulService()
