"""RUL prediction service — the backend's only bridge into the app.rul model package.

The FastAPI layer (routes + domain schemas) stays free of ML concerns; this module owns the
translation between the public RulPredictionRequest/Response contract and app.rul.scoring,
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
    RulPredictionRequest,
    RulPredictionResponse,
    RulQuantiles,
    RulStatus,
    WearToLimitDates,
)
from app.rul import paths, scoring
from app.rul.config import ThresholdConfig, get_threshold_config

DISCLAIMER = (
    "Decision-support estimate for inspection planning only. It prioritizes within existing "
    "maintenance limits and does not replace physical inspection, aircraft maintenance manuals, "
    "or qualified engineering approval."
)


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


class RulService:
    """Serve remaining-useful-life forecasts from the fitted prior plus a tire's own readings."""

    def predict(self, request: RulPredictionRequest) -> RulPredictionResponse:
        prior = _load_prior()
        thresholds = _load_thresholds()
        as_of = request.as_of_date or datetime.now(UTC).date()

        cycles = np.array([r.cycles_since_install for r in request.readings], dtype=float)
        grooves = np.array([r.measured_groove_mm for r in request.readings], dtype=float)
        n_readings = len(request.readings)

        prior_mean, prior_cov, scale = scoring.prior_arrays(prior, request.position)
        estimate = scoring.estimate_wheel(
            cycles,
            grooves,
            prior_mean,
            prior_cov,
            scale,
            current_cycles=request.current_cycles,
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

        return RulPredictionResponse(
            prediction_id=uuid4(),
            position=request.position,
            rul_landings=RulQuantiles(
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
            readings_used=n_readings,
            low_confidence=estimate.low_confidence,
            status=RulStatus(
                status=report.status,
                severity=report.severity,
                headline=report.headline,
                recommended_action=report.recommended_action,
            ),
            wear_limit_mm=thresholds.wear_limit_mm,
            model_version=f"rul-mixedlm-{prior.get('version', 'unknown')}",
            disclaimer=DISCLAIMER,
        )


rul_service = RulService()
