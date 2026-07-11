"""Leakage-safe feature engineering and whole-tire train/test splitting.

Every feature for inspection *i* is computed from data available **up to and including**
that inspection's timestamp — never a future reading. Features are built exclusively from
the core Parquet tables; the ``_ground_truth`` sidecar is never touched here.

Evaluation always holds out **whole tires** (never random rows), so a tire cannot appear in
both train and test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Trailing window (number of readings, including current) for the rolling wear-slope feature.
ROLLING_WINDOW = 4

# Numeric columns fed to the LightGBM baseline. (MixedLM/Weibull use their own designs.)
FEATURE_COLUMNS = [
    "cycles_since_install",
    "groove_remaining_ratio",
    "recent_wear_rate",
    "rolling_wear_slope",
    "days_since_install",
    "days_since_last_inspection",
    "reading_index",
    "hard_landings_since_install",
    "hard_landing_rate",
    "min_pressure_since_install",
    "latest_pressure_pct",
    "cycles_per_day",
    # sensor/log expansion (leakage-safe window aggregates)
    "brake_energy_mean",
    "lateral_exposure",
    "crosswind_mean",
    "runway_roughness",
    "high_wear_event_rate",
    "retread_level",
]
CATEGORICAL_COLUMNS = ["position_code", "gear", "brand"]

# Lateral turn-load allocation per wheel: the outboard main tire on the turn's outer side bears
# the most scrub, so it gets the highest weight; nose tires steer rather than scrub.
_LATERAL_WEIGHT = {
    "nlg_l": 0.7,
    "nlg_r": 0.7,
    "mlg_l_inbd": 1.0,
    "mlg_l_outbd": 1.35,
    "mlg_r_inbd": 1.0,
    "mlg_r_outbd": 1.35,
}


def _trailing_slope(cycles: np.ndarray, grooves: np.ndarray, k: int) -> np.ndarray:
    """Least-squares slope (mm per cycle) over the trailing k readings, per position.

    Backward-looking only: row i uses readings [i-k+1 .. i]. NaN when < 2 usable points.
    """
    out = np.full(len(cycles), np.nan)
    for i in range(len(cycles)):
        lo = max(0, i - k + 1)
        xs = cycles[lo : i + 1]
        ys = grooves[lo : i + 1]
        if len(xs) >= 2 and np.ptp(xs) > 0:
            xm = xs.mean()
            denom = float(((xs - xm) ** 2).sum())
            if denom > 0:
                out[i] = float(((xs - xm) * (ys - ys.mean())).sum() / denom)
    return out


def _per_tire_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute within-tire causal features. `df` is already sorted by cycles_since_install."""
    parts = []
    for _, grp in df.groupby("tire_id", sort=False):
        g = grp.copy()
        cyc = g["cycles_since_install"].to_numpy(dtype=float)
        groove = g["measured_groove_mm"].to_numpy(dtype=float)

        # recent wear rate from the immediately prior reading (mm lost per cycle)
        prev_groove = np.concatenate([[np.nan], groove[:-1]])
        prev_cyc = np.concatenate([[np.nan], cyc[:-1]])
        dcyc = cyc - prev_cyc
        with np.errstate(invalid="ignore", divide="ignore"):
            recent = np.where(dcyc > 0, (prev_groove - groove) / dcyc, np.nan)
        g["recent_wear_rate"] = recent

        # rolling trailing slope (a negative value = wearing down)
        slope = _trailing_slope(cyc, groove, ROLLING_WINDOW)
        # express as positive wear rate (mm lost per cycle) for interpretability
        g["rolling_wear_slope"] = -slope

        # reading index (1-based) and cumulative min pressure so far
        g["reading_index"] = np.arange(1, len(g) + 1)
        g["min_pressure_since_install"] = g["pressure_pct"].cummin()
        g["latest_pressure_pct"] = g["pressure_pct"]

        # days since last inspection
        d = g["inspection_date"]
        g["days_since_last_inspection"] = d.diff().dt.total_seconds() / 86400.0

        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def _hard_landings(df: pd.DataFrame, ops: pd.DataFrame) -> pd.Series:
    """Count hard landings for each row's aircraft within [install_date, inspection_date].

    Causal: only landings on or before the inspection date are counted.
    """
    ops = ops[["aircraft_id", "cycle_date", "hard_landing"]].copy()
    ops["cycle_date"] = ops["cycle_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    hard_by_ac: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for ac_id, grp in ops.sort_values("cycle_date").groupby("aircraft_id"):
        dates = grp["cycle_date"].to_numpy(dtype="datetime64[ns]")
        cum = np.cumsum(grp["hard_landing"].to_numpy(dtype=int))
        hard_by_ac[ac_id] = (dates, cum)

    inst = df["install_date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    insp = df["inspection_date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    ac_ids = df["aircraft_id"].to_numpy()

    counts = np.zeros(len(df), dtype=int)
    for i in range(len(df)):
        entry = hard_by_ac.get(ac_ids[i])
        if entry is None:
            continue
        dates, cum = entry
        hi = int(np.searchsorted(dates, insp[i], side="right"))
        lo = int(np.searchsorted(dates, inst[i], side="left"))
        hi_c = int(cum[hi - 1]) if hi > 0 else 0
        lo_c = int(cum[lo - 1]) if lo > 0 else 0
        counts[i] = max(hi_c - lo_c, 0)
    return pd.Series(counts, index=df.index)


def _window_means(df: pd.DataFrame, ops: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Causal per-inspection mean of each ops column over [install_date, inspection_date]."""
    present = [c for c in cols if c in ops.columns]
    if not present:
        return pd.DataFrame(index=df.index)
    o = ops[["aircraft_id", "cycle_date", *present]].copy()
    o["cycle_date"] = o["cycle_date"].dt.tz_convert("UTC").dt.tz_localize(None)
    by_ac: dict[str, tuple[np.ndarray, dict[str, np.ndarray]]] = {}
    for ac_id, grp in o.sort_values("cycle_date").groupby("aircraft_id"):
        dates = grp["cycle_date"].to_numpy(dtype="datetime64[ns]")
        cums = {c: np.concatenate([[0.0], np.cumsum(grp[c].to_numpy(dtype=float))]) for c in present}
        by_ac[ac_id] = (dates, cums)

    inst = df["install_date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    insp = df["inspection_date"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")
    ac_ids = df["aircraft_id"].to_numpy()

    out = {c: np.full(len(df), np.nan) for c in present}
    for i in range(len(df)):
        entry = by_ac.get(ac_ids[i])
        if entry is None:
            continue
        dates, cums = entry
        hi = int(np.searchsorted(dates, insp[i], side="right"))
        lo = int(np.searchsorted(dates, inst[i], side="left"))
        cnt = hi - lo
        if cnt <= 0:
            continue
        for c in present:
            out[c][i] = (cums[c][hi] - cums[c][lo]) / cnt
    return pd.DataFrame(out, index=df.index)


def build_features(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One leakage-safe feature row per inspection."""
    insp = tables["inspection_records"].copy()
    tire_cols = [
        "tire_id",
        "gear",
        "brand",
        "new_tread_mm",
        "wear_limit_mm",
        "install_date",
        "outcome",
        "time_to_event_cycles",
        "censored",
        "is_current",
    ]
    if "retread_level" in tables["tires"].columns:
        tire_cols.append("retread_level")
    tires = tables["tires"][tire_cols]
    ac = tables["aircraft"][["aircraft_id", "cycles_per_day", "home_station"]]

    df = insp.merge(tires, on="tire_id", how="left").merge(ac, on="aircraft_id", how="left")
    df = df.sort_values(["tire_id", "cycles_since_install"]).reset_index(drop=True)

    df = _per_tire_features(df)

    # groove remaining headroom ratio: (measured - limit) / (new_tread - limit)
    denom = (df["new_tread_mm"] - df["wear_limit_mm"]).replace(0, np.nan)
    df["groove_remaining_ratio"] = (df["measured_groove_mm"] - df["wear_limit_mm"]) / denom

    df["days_since_install"] = (
        df["inspection_date"] - df["install_date"]
    ).dt.total_seconds() / 86400.0

    df["hard_landings_since_install"] = _hard_landings(df, tables["operational_cycles"])
    with np.errstate(invalid="ignore", divide="ignore"):
        df["hard_landing_rate"] = np.where(
            df["cycles_since_install"] > 0,
            df["hard_landings_since_install"] / df["cycles_since_install"],
            np.nan,
        )

    # sensor/log expansion: causal window means over [install, inspection]
    means = _window_means(
        df,
        tables["operational_cycles"],
        ["brake_energy_mj", "lateral_load_g", "crosswind_kt", "runway_condition", "high_wear_event"],
    )
    df["brake_energy_mean"] = means.get("brake_energy_mj", np.nan)
    df["crosswind_mean"] = means.get("crosswind_kt", np.nan)
    df["high_wear_event_rate"] = means.get("high_wear_event", np.nan)
    # runway roughness: rougher surface = lower ICAO RCC -> higher roughness
    df["runway_roughness"] = 6.0 - means.get("runway_condition", np.nan)
    # lateral exposure allocated inner-vs-outer by wheel position
    pos_weight = df["position_code"].map(_LATERAL_WEIGHT).fillna(1.0)
    df["lateral_exposure"] = means.get("lateral_load_g", np.nan) * pos_weight
    if "retread_level" not in df.columns:
        df["retread_level"] = np.nan

    return df


# ---------------------------------------------------------------------------
# Whole-tire splitting
# ---------------------------------------------------------------------------
def split_by_tire(
    df: pd.DataFrame, test_frac: float = 0.25, seed: int = 7, group_col: str = "tire_id"
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """Partition unique tires into disjoint train/test sets.

    Returns (train_mask, test_mask, train_ids, test_ids) where the masks align to df rows.
    """
    ids = np.array(sorted(df[group_col].unique()))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ids))
    n_test = max(1, int(round(len(ids) * test_frac)))
    test_ids = set(ids[perm[:n_test]].tolist())
    train_ids = set(ids[perm[n_test:]].tolist())
    test_mask = df[group_col].isin(test_ids).to_numpy()
    train_mask = df[group_col].isin(train_ids).to_numpy()
    return train_mask, test_mask, sorted(train_ids), sorted(test_ids)


def assign_folds(df: pd.DataFrame, n_folds: int = 5, seed: int = 7, group_col: str = "tire_id") -> pd.Series:
    """Assign a whole-tire CV fold (0..n_folds-1) to every row."""
    ids = np.array(sorted(df[group_col].unique()))
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ids))
    fold_of = {tid: int(i % n_folds) for i, tid in enumerate(ids[perm])}
    return df[group_col].map(fold_of).astype(int)
