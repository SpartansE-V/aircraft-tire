"""Known-answer tests for the pure prognostics metric functions."""

from __future__ import annotations

import numpy as np

from app.tire_rul.evaluation import (
    alpha_lambda_accuracy,
    asymmetric_score,
    mae,
    median_abs_pct_error,
)


def test_mae_known_answer():
    pred = np.array([10.0, 20.0, 30.0])
    true = np.array([12.0, 18.0, 33.0])
    # abs errors: 2, 2, 3 -> mean 2.333...
    assert abs(mae(pred, true) - (7.0 / 3.0)) < 1e-9


def test_alpha_lambda_accuracy_known_answer():
    true = np.array([100.0, 100.0, 100.0, 100.0])
    pred = np.array([100.0, 115.0, 125.0, 80.0])  # rel err 0.0, 0.15, 0.25, 0.20
    # within +/-0.20: rows 0 (0.0), 1 (0.15), 3 (0.20) -> 3/4
    assert abs(alpha_lambda_accuracy(pred, true, 0.2) - 0.75) < 1e-9


def test_alpha_lambda_excludes_nonpositive_true():
    true = np.array([0.0, 50.0])
    pred = np.array([999.0, 55.0])  # first excluded (true<=0); second within 20%
    assert alpha_lambda_accuracy(pred, true, 0.2) == 1.0


def test_asymmetric_score_penalizes_late_more_than_early():
    """A late prediction (over-estimated RUL, the dangerous direction) must score worse than an
    equally-sized early prediction."""
    true = np.array([100.0])
    late = np.array([110.0])  # d = +10
    early = np.array([90.0])  # d = -10
    s_late = asymmetric_score(late, true)
    s_early = asymmetric_score(early, true)
    assert s_late > s_early > 0


def test_asymmetric_score_zero_at_perfect():
    true = np.array([50.0, 80.0])
    assert abs(asymmetric_score(true.copy(), true)) < 1e-12


def test_median_abs_pct_error_known_answer():
    true = np.array([100.0, 200.0, 400.0])
    pred = np.array([110.0, 180.0, 400.0])  # rel: 0.10, 0.10, 0.0 -> median 0.10
    assert abs(median_abs_pct_error(pred, true) - 0.10) < 1e-9
