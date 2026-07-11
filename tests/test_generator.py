"""Generator invariant tests — the critical-path credibility gate.

If the synthetic data does not look like real aircraft-tire wear, every downstream number
is discounted. These tests lock the parameters to cited aviation ranges and prove the run
is reproducible.
"""

from __future__ import annotations

import numpy as np

from app.tire_rul.constants import NEW_TREAD_MM_MAX, NEW_TREAD_MM_MIN, TireOutcome
from app.tire_rul.generate_data import generate


def test_median_life_bands(tables):
    """Main-gear median life 250-350 landings; nose 120-200 (cited manufacturer ranges)."""
    worn = tables["tires"].query("outcome == 'worn'")
    main_median = worn.query("gear == 'main'")["time_to_event_cycles"].median()
    nose_median = worn.query("gear == 'nose'")["time_to_event_cycles"].median()
    assert 250 <= main_median <= 350, f"main-gear median life {main_median} outside 250-350"
    assert 120 <= nose_median <= 200, f"nose-gear median life {nose_median} outside 120-200"


def test_outcome_mix_bands(tables, gen_config):
    """Realized WORN / EARLY_REMOVAL / IN_SERVICE mix must fall in the configured bands."""
    mix = tables["tires"]["outcome"].value_counts(normalize=True)
    for key, (lo, hi) in gen_config.target_outcome_mix.items():
        frac = float(mix.get(key, 0.0))
        assert lo <= frac <= hi, f"outcome '{key}' fraction {frac:.3f} outside [{lo}, {hi}]"


def test_new_tread_in_range(tables):
    t = tables["tires"]
    assert t["new_tread_mm"].min() >= NEW_TREAD_MM_MIN - 1e-9
    assert t["new_tread_mm"].max() <= NEW_TREAD_MM_MAX + 1e-9


def test_true_wear_monotonic(tables):
    """Underlying true groove depth is strictly non-increasing over cycles for every tire."""
    gt = tables["_ground_truth"]
    insp_truth = gt[gt["inspection_id"].notna()].sort_values(["tire_id", "cycles_since_install"])
    bad = 0
    for _, grp in insp_truth.groupby("tire_id"):
        if len(grp) < 2:
            continue
        diffs = np.diff(grp["true_groove_mm"].to_numpy())
        if np.any(diffs > 1e-9):  # any increase is a physics violation
            bad += 1
    assert bad == 0, f"{bad} tires have non-monotonic true wear"


def test_true_wear_reaches_limit_for_worn(tables):
    """WORN tires must have crossed the 2.0 mm serviceable limit in ground truth."""
    tires = tables["tires"]
    gt_close = tables["_ground_truth"].query("inspection_id.isna()", engine="python")
    worn_ids = set(tires.query("outcome == 'worn'")["tire_id"])
    closes = gt_close[gt_close["tire_id"].isin(worn_ids)]
    assert (closes["true_groove_mm"] <= 2.0 + 1e-6).all(), "a WORN tire did not reach the wear limit"


def test_gauge_noise_separated_from_process(tables):
    """Recorded groove = true groove + gauge noise (~0.25 mm SD). Robust median-abs check
    tolerates the ~1% gross mis-read tail without being fooled by it."""
    gt = tables["_ground_truth"]
    insp_truth = gt[gt["inspection_id"].notna()][["inspection_id", "true_groove_mm"]]
    insp = tables["inspection_records"].merge(insp_truth, on="inspection_id")
    resid = insp["measured_groove_mm"] - insp["true_groove_mm"]
    median_abs = resid.abs().median()
    # N(0, 0.25) -> median|.| ~= 0.169. Allow a tolerant band.
    assert 0.12 <= median_abs <= 0.22, f"gauge median-abs residual {median_abs:.3f} inconsistent with ~0.25 SD"


def test_inspection_records_have_no_truth_leak(tables):
    """No ground-truth column may appear on the inspection table."""
    cols = set(tables["inspection_records"].columns)
    assert "true_groove_mm" not in cols
    assert not any("true_" in c for c in cols)


def test_ids_unique(tables):
    assert tables["tires"]["tire_id"].is_unique
    assert tables["inspection_records"]["inspection_id"].is_unique
    assert tables["aircraft"]["aircraft_id"].is_unique


def test_every_tire_has_outcome_and_censor(tables):
    t = tables["tires"]
    assert t["outcome"].isin([o.value for o in TireOutcome]).all()
    # WORN/EARLY_REMOVAL are observed events; IN_SERVICE is right-censored.
    assert (t.query("outcome == 'in_service'")["censored"]).all()
    assert (~t.query("outcome == 'worn'")["censored"]).all()
    # is_current mirrors censored (the mounted tire).
    assert (t["is_current"] == t["censored"]).all()


def test_sensor_signals_present_and_valid(tables):
    """The sensor/log expansion columns exist, are valid, and do NOT perturb the physics."""
    oc = tables["operational_cycles"]
    for c in [
        "brake_energy_mj",
        "sink_rate_fpm",
        "ambient_temp_c",
        "crosswind_kt",
        "lateral_load_g",
        "turn_direction",
        "runway_condition",
        "high_wear_event",
    ]:
        assert c in oc.columns, f"missing sensor column {c}"
    assert oc["runway_condition"].isin([2, 3, 4, 5, 6]).all()  # ICAO RCC
    assert oc["turn_direction"].isin(["L", "R"]).all()
    assert (oc["brake_energy_mj"] > 0).all()
    assert (oc["crosswind_kt"] >= 0).all()
    # a high-wear event can only occur on a hard landing
    assert not (oc["high_wear_event"] & ~oc["hard_landing"]).any()
    # retread level on the tires table
    t = tables["tires"]
    assert "retread_level" in t.columns
    assert t["retread_level"].between(0, 5).all()


def test_reproducible(gen_config):
    """Same seed -> byte-identical inspection records."""
    a = generate(gen_config)["inspection_records"].reset_index(drop=True)
    b = generate(gen_config)["inspection_records"].reset_index(drop=True)
    import pandas.testing as pdt

    pdt.assert_frame_equal(a, b)
