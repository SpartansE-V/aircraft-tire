"""Feature-engineering tests: causality (no leakage), whole-tire split integrity, bounds."""

from __future__ import annotations

import numpy as np

from app.tire_rul.features import (
    FEATURE_COLUMNS,
    assign_folds,
    build_features,
    split_by_tire,
)


def test_build_features_one_row_per_inspection(tables):
    feats = build_features(tables)
    assert len(feats) == len(tables["inspection_records"])
    for col in FEATURE_COLUMNS:
        assert col in feats.columns, f"missing feature column {col}"


def test_no_ground_truth_leak(tables):
    feats = build_features(tables)
    assert not any("true_" in c for c in feats.columns)


def test_causal_no_lookahead(tables):
    """Deleting inspections AFTER a given tire-reading must not change earlier feature values.

    Take one multi-reading tire, compute features on its full history, then recompute on a
    truncated history and assert the surviving rows are identical.
    """
    feats = build_features(tables)
    # pick a tire with several readings
    counts = feats.groupby("tire_id").size().sort_values(ascending=False)
    tire_id = counts.index[0]
    n = int(counts.iloc[0])
    keep_k = n - 2  # drop the last two readings

    insp = tables["inspection_records"]
    tire_insp = insp[insp["tire_id"] == tire_id].sort_values("cycles_since_install")
    drop_ids = set(tire_insp["inspection_id"].tolist()[keep_k:])

    truncated = dict(tables)
    truncated["inspection_records"] = insp[~insp["inspection_id"].isin(drop_ids)].copy()
    feats_trunc = build_features(truncated)

    check_cols = [
        "recent_wear_rate",
        "rolling_wear_slope",
        "groove_remaining_ratio",
        "min_pressure_since_install",
        "hard_landings_since_install",
        "days_since_last_inspection",
        "brake_energy_mean",
        "crosswind_mean",
        "runway_roughness",
        "lateral_exposure",
    ]
    a = feats[feats["tire_id"] == tire_id].sort_values("cycles_since_install").head(keep_k)
    b = feats_trunc[feats_trunc["tire_id"] == tire_id].sort_values("cycles_since_install")
    assert len(b) == keep_k
    for col in check_cols:
        va = a[col].to_numpy(dtype=float)
        vb = b[col].to_numpy(dtype=float)
        assert np.allclose(va, vb, equal_nan=True), f"feature '{col}' changed when future rows were deleted (leakage)"


def test_first_reading_nans(tables):
    """The first reading of a tire has no prior reading -> recent_wear_rate / gap are NaN, not a crash."""
    feats = build_features(tables)
    first = feats.sort_values("cycles_since_install").groupby("tire_id").head(1)
    assert first["recent_wear_rate"].isna().all()
    assert first["days_since_last_inspection"].isna().all()
    # reading_index starts at 1
    assert (first["reading_index"] == 1).all()


def test_groove_remaining_ratio_bounds(tables):
    feats = build_features(tables)
    # Well before end-of-life (measured well above the limit) the ratio stays within ~[0,1].
    # Use robust quantiles: the ~1% gross mis-reads can push a handful of values past 1.
    mid = feats[feats["measured_groove_mm"] > 3.0]["groove_remaining_ratio"]
    assert mid.quantile(0.01) >= -0.05
    assert mid.quantile(0.99) <= 1.15  # gauge noise can nudge slightly over 1
    assert mid.max() <= 1.6  # even a gross mis-read stays bounded


def test_split_by_tire_disjoint_and_deterministic(tables):
    feats = build_features(tables)
    tr1, te1, train_ids1, test_ids1 = split_by_tire(feats, test_frac=0.25, seed=11)
    tr2, te2, train_ids2, test_ids2 = split_by_tire(feats, test_frac=0.25, seed=11)

    # disjoint
    assert set(train_ids1).isdisjoint(set(test_ids1))
    # every row assigned exactly once
    assert bool((tr1 ^ te1).all())
    # deterministic for a fixed seed
    assert train_ids1 == train_ids2 and test_ids1 == test_ids2
    # test fraction roughly honored
    frac = len(test_ids1) / (len(train_ids1) + len(test_ids1))
    assert 0.2 <= frac <= 0.3


def test_sensor_features_present(tables):
    feats = build_features(tables)
    for c in ["brake_energy_mean", "lateral_exposure", "crosswind_mean", "runway_roughness", "high_wear_event_rate", "retread_level"]:
        assert c in feats.columns, f"missing sensor feature {c}"
    assert feats["brake_energy_mean"].notna().all()
    assert feats["retread_level"].between(0, 5).all()


def test_lateral_exposure_allocated_inner_vs_outer(tables):
    """Outboard main tire (turn's outer side) bears more lateral scrub than inboard, than nose."""
    feats = build_features(tables)
    outbd = feats[feats["position_code"] == "mlg_l_outbd"]["lateral_exposure"].mean()
    inbd = feats[feats["position_code"] == "mlg_l_inbd"]["lateral_exposure"].mean()
    nose = feats[feats["position_code"] == "nlg_l"]["lateral_exposure"].mean()
    assert outbd > inbd > nose


def test_assign_folds_partitions_tires(tables):
    feats = build_features(tables)
    folds = assign_folds(feats, n_folds=5, seed=3)
    # a tire is entirely within one fold
    per_tire = feats.assign(fold=folds).groupby("tire_id")["fold"].nunique()
    assert (per_tire == 1).all()
    assert set(folds.unique()).issubset(set(range(5)))
