"""Train the models and write the prognostics evaluation report.

Headline model: a statsmodels MixedLM random-slope degradation model of tread depth vs
cumulative landings, partially pooled by wheel position. train.py distills it into a compact
population *prior* (per-position intercept/slope, the random-effects covariance, and the
residual scale). scoring.eb_posterior then forms a per-tire posterior from that prior plus the
tire's own readings — so the same math serves both this evaluation and the live app.

Supporting models: a lifelines Weibull AFT survival model (censoring-correct) and a LightGBM
regressor baseline (with SHAP) that anchors accuracy and proves the linear-wear assumption
leaves little signal on the table.
"""

from __future__ import annotations

import json
import pickle
import warnings

import numpy as np
import pandas as pd

from . import paths
from .config import get_generator_config, get_threshold_config
from .constants import ALL_POSITIONS
from .evaluation import evaluate_degradation
from .features import FEATURE_COLUMNS, build_features, split_by_tire

BASELINE_POSITION = "mlg_l_inbd"  # C(position_code) treatment-coding reference (alphabetically first)


def _load_tables() -> dict[str, pd.DataFrame]:
    return {
        "fleets": pd.read_parquet(paths.FLEETS),
        "aircraft": pd.read_parquet(paths.AIRCRAFT),
        "wheel_positions": pd.read_parquet(paths.WHEEL_POSITIONS),
        "tires": pd.read_parquet(paths.TIRES),
        "inspection_records": pd.read_parquet(paths.INSPECTION_RECORDS),
        "operational_cycles": pd.read_parquet(paths.OPERATIONAL_CYCLES),
        "station_stock": pd.read_parquet(paths.STATION_STOCK),
        "_ground_truth": pd.read_parquet(paths.GROUND_TRUTH),
    }


def fit_mixedlm(train: pd.DataFrame):
    import statsmodels.formula.api as smf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = smf.mixedlm(
            "measured_groove_mm ~ cycles_since_install * C(position_code)",
            data=train,
            groups=train["tire_id"],
            re_formula="~cycles_since_install",
        )
        return model.fit(method="lbfgs", maxiter=200)


def build_prior(res, cfg_version: str) -> dict:
    fe = res.fe_params
    positions = {}
    for p in ALL_POSITIONS:
        pos = p.value
        icpt = float(fe["Intercept"] + fe.get(f"C(position_code)[T.{pos}]", 0.0))
        slope = float(fe["cycles_since_install"] + fe.get(f"cycles_since_install:C(position_code)[T.{pos}]", 0.0))
        positions[pos] = {"intercept": icpt, "slope": slope}
    cov_re = np.asarray(res.cov_re, dtype=float).tolist()
    return {
        "version": cfg_version,
        "baseline_position": BASELINE_POSITION,
        "positions": positions,
        "cov_re": cov_re,
        "scale": float(res.scale),
    }


def fit_weibull(tires: pd.DataFrame, aircraft: pd.DataFrame):
    from lifelines import WeibullAFTFitter

    df = tires.merge(aircraft[["aircraft_id", "cycles_per_day"]], on="aircraft_id", how="left")
    df = pd.DataFrame(
        {
            "duration": df["time_to_event_cycles"].clip(lower=1),
            "event": (df["outcome"] == "worn").astype(int),  # WORN observed; EARLY_REMOVAL/IN_SERVICE censored
            "is_nose": (df["gear"] == "nose").astype(int),
            "cycles_per_day": df["cycles_per_day"].fillna(df["cycles_per_day"].median()),
        }
    )
    waf = WeibullAFTFitter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        waf.fit(df, duration_col="duration", event_col="event")
    return waf, df


def fit_lightgbm(feats: pd.DataFrame, tires: pd.DataFrame, train_ids: list[str], test_ids: list[str]):
    """RUL-in-cycles regression baseline on WORN-tire inspections. Returns (booster, shap_df, test_mae)."""
    try:
        import lightgbm as lgb
        import shap
    except OSError as exc:  # libomp missing on some macOS setups
        print(f"  [lightgbm baseline skipped: {exc}]")
        return None, None, None

    worn = set(tires.query("outcome == 'worn'")["tire_id"])
    df = feats[feats["tire_id"].isin(worn)].copy()
    df["rul_cycles"] = df["time_to_event_cycles"] - df["cycles_since_install"]
    df = df[df["rul_cycles"] >= 0]

    tr = df[df["tire_id"].isin(set(train_ids))]
    te = df[df["tire_id"].isin(set(test_ids))]
    x_tr, y_tr = tr[FEATURE_COLUMNS], tr["rul_cycles"]
    x_te, y_te = te[FEATURE_COLUMNS], te["rul_cycles"]

    model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31, verbose=-1)
    model.fit(x_tr, y_tr)
    model.booster_.save_model(str(paths.LIGHTGBM))

    test_mae = float(np.mean(np.abs(model.predict(x_te) - y_te))) if len(te) else None

    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(x_te if len(te) else x_tr)
    mean_abs = np.abs(sv).mean(axis=0)
    shap_df = (
        pd.DataFrame({"feature": FEATURE_COLUMNS, "mean_abs_shap": mean_abs})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )
    shap_df.to_parquet(paths.SHAP_VALUES, index=False)
    return model, shap_df, test_mae


def load_prior() -> dict:
    with open(paths.MIXEDLM_COV, "rb") as f:
        return pickle.load(f)


def main() -> None:
    paths.ensure_dirs()
    cfg = get_generator_config()
    tc = get_threshold_config()
    tables = _load_tables()
    feats = build_features(tables)

    _, _, train_ids, test_ids = split_by_tire(feats, test_frac=0.25, seed=11)
    train = feats[feats["tire_id"].isin(set(train_ids))]

    print(f"Fitting MixedLM on {len(train)} readings / {len(train_ids)} train tires...")
    res = fit_mixedlm(train)
    prior = build_prior(res, cfg.version)
    with open(paths.MIXEDLM, "wb") as f:
        pickle.dump(res, f)
    with open(paths.MIXEDLM_COV, "wb") as f:
        pickle.dump(prior, f)
    print(f"  MixedLM converged={res.converged}; residual sd={np.sqrt(res.scale):.3f} mm")

    print("Fitting Weibull AFT survival model...")
    waf, _ = fit_weibull(tables["tires"], tables["aircraft"])
    with open(paths.WEIBULL_AFT, "wb") as f:
        pickle.dump(waf, f)
    weibull_median_main = float(waf.predict_median(pd.DataFrame([{"is_nose": 0, "cycles_per_day": 3.0}])).iloc[0])
    weibull_median_nose = float(waf.predict_median(pd.DataFrame([{"is_nose": 1, "cycles_per_day": 3.0}])).iloc[0])

    print("Fitting LightGBM baseline + SHAP...")
    _, shap_df, lgbm_mae = fit_lightgbm(feats, tables["tires"], train_ids, test_ids)

    print("Evaluating on whole-tire holdout...")
    deg = evaluate_degradation(feats, tables["tires"], prior, tables["_ground_truth"], cfg, tc, test_ids)

    mix = tables["tires"]["outcome"].value_counts(normalize=True).round(3).to_dict()
    report = {
        "config_version": cfg.version,
        "seed": cfg.seed,
        "n_tires": int(len(tables["tires"])),
        "n_train_tires": len(train_ids),
        "n_test_tires": len(test_ids),
        "outcome_mix": mix,
        "degradation_model": deg,
        "weibull_median_life_cycles": {"main": weibull_median_main, "nose": weibull_median_nose},
        "lightgbm_baseline_rul_mae_cycles": lgbm_mae,
        "top_features_shap": shap_df.head(5).to_dict("records") if shap_df is not None else None,
    }
    with open(paths.EVAL_REPORT, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print("\n=== Evaluation summary ===")
    print(f"  RUL MAE (cycles):            {deg['rul_mae_cycles']:.1f}")
    print(f"  RUL MAE second half:        {deg['rul_mae_cycles_second_half']:.1f}")
    print(f"  Wear-to-limit date MAE @30d: {deg['wear_to_limit_date_mae_days_at_30d']:.1f} days")
    print(f"  alpha-lambda acc (2nd half): {deg['alpha_lambda_accuracy_second_half']:.2f}")
    print(f"  prognostic horizon (cycles): {deg['prognostic_horizon_cycles']:.0f}")
    print(f"  asymmetric score (2nd half): {deg['asymmetric_score_second_half']:.3f}  "
          f"(frac late 2nd half {deg['frac_late_second_half']:.2f})")
    print(f"  GT wear-rate recovery MAPE:  {deg['ground_truth_wear_rate_recovery_median_abs_pct']:.3f}")
    print(f"  LightGBM baseline RUL MAE:   {lgbm_mae}")
    print(f"  Report written to {paths.EVAL_REPORT}")


if __name__ == "__main__":
    main()
