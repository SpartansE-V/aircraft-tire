"""Prognostics-grade evaluation on a whole-tire holdout.

Reports the metrics that matter for RUL: MAE (cycles and wear-to-limit days), alpha-lambda
accuracy over the second half of life, prognostic horizon, an asymmetric score that penalizes
LATE (over-estimated) RUL — the dangerous direction — more heavily than early, and a
ground-truth wear-rate recovery figure only a synthetic POC can show.

The pure metric functions (mae / alpha_lambda_accuracy / asymmetric_score /
median_abs_pct_error) are unit-tested on known-answer inputs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import scoring
from .config import GeneratorConfig, ThresholdConfig

# NASA-CMAPSS-style asymmetric scoring constants: late errors (d>0) decay slower -> penalized more.
ASYM_LATE = 10.0
ASYM_EARLY = 13.0


# ---------------------------------------------------------------------------
# Pure metric functions (unit-tested)
# ---------------------------------------------------------------------------
def mae(pred: np.ndarray, true: np.ndarray) -> float:
    pred = np.asarray(pred, dtype=float)
    true = np.asarray(true, dtype=float)
    return float(np.mean(np.abs(pred - true)))


def alpha_lambda_accuracy(pred: np.ndarray, true: np.ndarray, alpha: float = 0.2) -> float:
    """Fraction of predictions within +/- alpha of the true RUL (excludes true<=0)."""
    pred = np.asarray(pred, dtype=float)
    true = np.asarray(true, dtype=float)
    mask = true > 0
    if not mask.any():
        return float("nan")
    rel = np.abs(pred[mask] - true[mask]) / true[mask]
    return float(np.mean(rel <= alpha))


def asymmetric_score(pred: np.ndarray, true: np.ndarray, a_late: float = ASYM_LATE, a_early: float = ASYM_EARLY) -> float:
    """Mean NASA-style score. d = pred - true; late (d>0) penalized more than early (d<0)."""
    d = np.asarray(pred, dtype=float) - np.asarray(true, dtype=float)
    s = np.where(d >= 0, np.exp(d / a_late) - 1.0, np.exp(-d / a_early) - 1.0)
    return float(np.mean(s))


def median_abs_pct_error(pred: np.ndarray, true: np.ndarray) -> float:
    pred = np.asarray(pred, dtype=float)
    true = np.asarray(true, dtype=float)
    mask = true > 0
    return float(np.median(np.abs(pred[mask] - true[mask]) / true[mask]))


# ---------------------------------------------------------------------------
# Degradation-model evaluation
# ---------------------------------------------------------------------------
def _analytic_rul(intercept: float, slope: float, current_cycle: float, limit: float) -> float:
    """RUL from the posterior-mean wear line; +inf if the line never wears to the limit."""
    if slope >= -1e-9:
        return float("inf")
    crossing = (limit - intercept) / slope
    return max(crossing - current_cycle, 0.0)


def evaluate_degradation(
    feats: pd.DataFrame,
    tires: pd.DataFrame,
    prior: dict,
    gt: pd.DataFrame,
    cfg: GeneratorConfig,
    tc: ThresholdConfig,
    test_ids: list[str],
) -> dict:
    limit = cfg.wear_limit_mm
    worn = set(tires.query("outcome == 'worn'")["tire_id"])
    test_worn = [t for t in test_ids if t in worn]

    preds, trues, cyc_fracs, tire_seq = [], [], [], []
    # ground-truth wear-rate recovery (per test tire, using all its readings)
    gt_rate = (
        gt[gt["inspection_id"].isna()]
        .dropna(subset=["tire_true_wear_rate_mm_per_landing"])
        .set_index("tire_id")["tire_true_wear_rate_mm_per_landing"]
        .to_dict()
    )
    recovered_rates, true_rates = [], []

    per_tire_records: list[list[tuple[float, float]]] = []  # (true_rul, abs_rel_err) ordered by cycle

    for tid in test_worn:
        g = feats[feats["tire_id"] == tid].sort_values("cycles_since_install")
        if g.empty:
            continue
        pos = g["position_code"].iloc[0]
        total_life = float(tires.loc[tires["tire_id"] == tid, "time_to_event_cycles"].iloc[0])
        pmean, pcov, scale = scoring.prior_arrays(prior, pos)
        cyc = g["cycles_since_install"].to_numpy(dtype=float)
        grv = g["measured_groove_mm"].to_numpy(dtype=float)

        seq: list[tuple[float, float]] = []
        for i in range(len(g)):
            mean, _ = scoring.eb_posterior(cyc[: i + 1], grv[: i + 1], pmean, pcov, scale)
            pred_rul = _analytic_rul(mean[0], mean[1], cyc[i], limit)
            true_rul = total_life - cyc[i]
            if true_rul <= 0:
                continue
            pred_rul = min(pred_rul, scoring.NEVER_CROSS_CYCLES)
            preds.append(pred_rul)
            trues.append(true_rul)
            cyc_fracs.append(cyc[i] / total_life)
            tire_seq.append(tid)
            rel = abs(pred_rul - true_rul) / true_rul
            seq.append((true_rul, rel))
        per_tire_records.append(seq)

        # recovery: posterior slope with ALL readings vs sidecar true rate
        if tid in gt_rate:
            mean_all, _ = scoring.eb_posterior(cyc, grv, pmean, pcov, scale)
            recovered_rates.append(-mean_all[1])
            true_rates.append(gt_rate[tid])

    preds = np.array(preds)
    trues = np.array(trues)
    cyc_fracs = np.array(cyc_fracs)
    second_half = cyc_fracs >= 0.5

    util_median = float(feats["cycles_per_day"].median())
    date_err_days = np.abs(preds - trues) / max(util_median, 1e-6)
    # near a 30-day horizon (true remaining days in [15, 45])
    true_days = trues / max(util_median, 1e-6)
    horizon30 = (true_days >= 15) & (true_days <= 45)

    return {
        "n_test_worn_tires": len(test_worn),
        "n_eval_points": int(len(preds)),
        "rul_mae_cycles": mae(preds, trues),
        "rul_mae_cycles_second_half": mae(preds[second_half], trues[second_half]) if second_half.any() else None,
        "rul_mae_pct_of_life": float(np.mean(np.abs(preds - trues) / trues)) if len(preds) else None,
        "wear_to_limit_date_mae_days_at_30d": float(np.mean(date_err_days[horizon30])) if horizon30.any() else None,
        "alpha_lambda_accuracy_second_half": alpha_lambda_accuracy(preds[second_half], trues[second_half], 0.2)
        if second_half.any()
        else None,
        "prognostic_horizon_cycles": _prognostic_horizon(per_tire_records, alpha=0.2),
        # Asymmetric score is only meaningful near end-of-life; early-life errors explode the
        # exponential and are not the operationally relevant regime.
        "asymmetric_score_second_half": asymmetric_score(preds[second_half], trues[second_half])
        if second_half.any()
        else None,
        "frac_late": float(np.mean(preds > trues)) if len(preds) else None,
        "frac_late_second_half": float(np.mean(preds[second_half] > trues[second_half])) if second_half.any() else None,
        "ground_truth_wear_rate_recovery_median_abs_pct": median_abs_pct_error(
            np.array(recovered_rates), np.array(true_rates)
        )
        if recovered_rates
        else None,
    }


def _prognostic_horizon(per_tire_records: list[list[tuple[float, float]]], alpha: float = 0.2) -> float:
    """Mean cycles-before-failure from which predictions stay within the alpha band.

    For each tire (records ordered by increasing cycle), find the earliest reading beyond
    which every subsequent |rel_err| <= alpha, and report its true_rul (cycles remaining).
    """
    horizons = []
    for seq in per_tire_records:
        if not seq:
            continue
        horizon = 0.0
        for i in range(len(seq)):
            if all(rel <= alpha for _, rel in seq[i:]):
                horizon = seq[i][0]  # true_rul at first stably-accurate reading
                break
        horizons.append(horizon)
    return float(np.mean(horizons)) if horizons else 0.0
