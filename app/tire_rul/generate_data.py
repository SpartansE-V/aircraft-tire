"""Physics-informed synthetic data generator (the critical path).

There is no real aircraft-tire dataset available, so we simulate one. Wear is modelled
at the LANDING-EVENT grain and aggregated to sparse inspections:

    wear_per_landing = base_wear[position]
                       * f_load * f_severity * f_taxi * f_temp   (aircraft-landing level)
                       * f_inflation * process_noise             (per-wheel level)
                       * per_tire_susceptibility                  (per-tire, LogNormal)
                       * accel_event_multiplier                   (rare 3-6x spikes)
                       * underinflation_multiplier                (sustained low-pressure runs)

Groove depth starts at a sampled new-tread depth (11-14 mm) and decreases toward the
2.0 mm serviceable limit. A tire is removed WORN when it reaches the limit, EARLY_REMOVAL
if a FOD/damage competing-risk hazard fires first, or left IN_SERVICE (right-censored) if
still mounted at the end of the history window.

Measurement noise (gauge + gross mis-reads) is applied ONLY to the recorded inspection
value and kept SEPARATE from process noise. The hidden ``_ground_truth.parquet`` sidecar
stores the true groove depth and per-tire true wear rate for validation ONLY — no
downstream feature or model may read it.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import paths
from .config import GeneratorConfig, get_generator_config
from .constants import ALL_POSITIONS, TireOutcome, WheelPosition


def _uuid(id_rng: np.random.Generator) -> str:
    """Deterministic UUID drawn from a dedicated stream (keeps physics draws untouched)."""
    return str(uuid.UUID(bytes=id_rng.bytes(16)))


def _clip_pos(a: np.ndarray, lo: float) -> np.ndarray:
    return np.clip(a, lo, None)


def generate(cfg: GeneratorConfig) -> dict[str, pd.DataFrame]:
    """Run the full simulation and return all tables as DataFrames (no disk I/O)."""
    ss = np.random.SeedSequence(cfg.seed)
    # spawn(3): the first two children equal spawn(2)'s, so phys/id streams — and thus the wear
    # physics — stay byte-identical. aux drives the ADDITIONAL sensor/log signals only.
    phys_seed, id_seed, aux_seed = ss.spawn(3)
    rng = np.random.default_rng(phys_seed)
    id_rng = np.random.default_rng(id_seed)
    aux_rng = np.random.default_rng(aux_seed)
    sensors = cfg.sensors

    start = cfg.start_date
    as_of = cfg.as_of_date
    n_days = (as_of - start).days
    wear_limit = cfg.wear_limit_mm

    fac = cfg.factors
    station_codes = [s.code for s in cfg.stations]

    fleet_id = _uuid(id_rng)
    fleets = [{"fleet_id": fleet_id, "name": "Pilot Narrowbody Fleet", "aircraft_type": cfg.aircraft_type}]

    aircraft_rows: list[dict] = []
    cycle_rows: list[dict] = []
    tire_rows: list[dict] = []
    insp_rows: list[dict] = []
    gt_rows: list[dict] = []

    for ac_idx in range(cfg.n_aircraft):
        aircraft_id = _uuid(id_rng)
        tail = f"VN-A{300 + ac_idx}"
        home = station_codes[ac_idx % len(station_codes)]
        cpd = float(rng.uniform(*cfg.cycles_per_day))
        aircraft_rows.append(
            {
                "aircraft_id": aircraft_id,
                "fleet_id": fleet_id,
                "tail_number": tail,
                "aircraft_type": cfg.aircraft_type,
                "home_station": home,
                "cycles_per_day": round(cpd, 2),
            }
        )

        # --- Aircraft-landing timeline (shared across all 6 wheels) ---
        landing_dates: list[date] = []
        cur = start
        for _ in range(n_days):
            k = int(rng.poisson(cpd))
            for _ in range(k):
                landing_dates.append(cur)
            cur = cur + timedelta(days=1)
        n = len(landing_dates)
        if n == 0:
            continue

        f_load = _clip_pos(rng.normal(1.0, fac["load"]["sd"], n), 0.3)
        f_sev = _clip_pos(rng.normal(1.0, fac["severity"]["sd"], n), 0.3)
        f_taxi = _clip_pos(rng.normal(1.0, fac["taxi"]["sd"], n), 0.3)
        f_temp = _clip_pos(rng.normal(1.0, fac["temp"]["sd"], n), 0.3)
        hard = rng.random(n) < cfg.hard_landing_prob
        hard_g = np.where(hard, rng.uniform(*cfg.hard_landing_g, n), rng.uniform(0.9, 1.2, n))
        taxi_m = np.clip(rng.normal(1200, 350, n), 200, None)

        # Additional sensor/log signals (aux stream — does NOT perturb wear physics).
        # brake_energy & sink_rate derive from the already-drawn severity / hard-landing signals.
        s = sensors
        brake_energy = s.get("brake_energy_base_mj", 2.6) * f_sev
        sink_rate = s.get("sink_rate_base_fpm", 130) * hard_g
        amb_lo, amb_hi = s.get("ambient_temp_c", [-5, 45])
        ambient_temp = aux_rng.uniform(amb_lo, amb_hi, n)
        crosswind = np.clip(
            np.abs(aux_rng.normal(0, s.get("crosswind_kt_scale", 7.0), n)), 0, s.get("crosswind_kt_max", 30.0)
        )
        lat_lo, lat_hi = s.get("lateral_load_g", [0.04, 0.34])
        lateral = aux_rng.uniform(lat_lo, lat_hi, n)
        turn_dir = aux_rng.choice(["L", "R"], n)
        runway = aux_rng.choice(
            s.get("runway_condition_codes", [6, 5, 4, 3, 2]),
            size=n,
            p=s.get("runway_condition_weights", [0.62, 0.20, 0.10, 0.05, 0.03]),
        )
        high_wear = hard & (aux_rng.random(n) < s.get("high_wear_event_prob", 0.15))

        for i in range(n):
            cycle_rows.append(
                {
                    "cycle_id": _uuid(id_rng),
                    "aircraft_id": aircraft_id,
                    "cycle_date": landing_dates[i],
                    "landing_number": i + 1,
                    "hard_landing": bool(hard[i]),
                    "hard_landing_g": round(float(hard_g[i]), 3),
                    "taxi_distance_m": round(float(taxi_m[i]), 1),
                    "load_factor": round(float(f_load[i]), 4),
                    "brake_energy_mj": round(float(brake_energy[i]), 3),
                    "sink_rate_fpm": round(float(sink_rate[i]), 1),
                    "ambient_temp_c": round(float(ambient_temp[i]), 1),
                    "crosswind_kt": round(float(crosswind[i]), 1),
                    "lateral_load_g": round(float(lateral[i]), 3),
                    "turn_direction": str(turn_dir[i]),
                    "runway_condition": int(runway[i]),
                    "high_wear_event": bool(high_wear[i]),
                    "origin": home,
                    "dest": station_codes[(ac_idx + i) % len(station_codes)],
                }
            )

        # --- Per-wheel wear simulation ---
        for pos in ALL_POSITIONS:
            base = cfg.base_wear_mm_per_landing[pos.value]
            crit = pos  # (position enum kept for clarity)

            # Pre-draw per-wheel per-landing arrays (vectorized).
            infl = _clip_pos(rng.normal(1.0, fac["inflation"]["sd"], n), 0.5)
            noise = _clip_pos(rng.normal(1.0, cfg.process_noise_sd, n), 0.3)
            accel_hit = rng.random(n) < cfg.accel_event_prob
            accel_val = np.where(accel_hit, rng.uniform(*cfg.accel_multiplier, n), 1.0)
            uinfl_start = rng.random(n) < cfg.underinflation_event_prob
            fod_draw = rng.random(n)
            gauge = rng.normal(0.0, cfg.gauge_noise_sd_mm, n)
            gross_hit = rng.random(n) < cfg.gross_misread_prob
            gross = np.where(gross_hit, rng.normal(0.0, cfg.gross_misread_sd_mm, n), 0.0)

            _simulate_position(
                cfg=cfg,
                rng=rng,
                id_rng=id_rng,
                aircraft_id=aircraft_id,
                pos=crit,
                base=base,
                landing_dates=landing_dates,
                f_load=f_load,
                f_sev=f_sev,
                f_taxi=f_taxi,
                f_temp=f_temp,
                infl=infl,
                noise=noise,
                accel_val=accel_val,
                uinfl_start=uinfl_start,
                fod_draw=fod_draw,
                gauge=gauge,
                gross=gross,
                wear_limit=wear_limit,
                tire_rows=tire_rows,
                insp_rows=insp_rows,
                gt_rows=gt_rows,
            )

    station_rows = [
        {"station_code": s.code, "tire_size": cfg.tire_size, "on_hand": s.spare_stock} for s in cfg.stations
    ]
    wheel_pos_rows = [
        {"position_code": p.value, "gear": p.gear, "is_nose": p.is_nose, "description": p.name} for p in ALL_POSITIONS
    ]

    tires_df = pd.DataFrame(tire_rows)
    # Retread level (casing history) — aux stream, assigned after the physics is fixed.
    if len(tires_df):
        tires_df["retread_level"] = aux_rng.choice(
            sensors.get("retread_level_values", [0, 1, 2, 3, 4, 5]),
            size=len(tires_df),
            p=sensors.get("retread_level_weights", [0.34, 0.25, 0.20, 0.12, 0.06, 0.03]),
        ).astype(int)

    tables = {
        "fleets": pd.DataFrame(fleets),
        "aircraft": pd.DataFrame(aircraft_rows),
        "wheel_positions": pd.DataFrame(wheel_pos_rows),
        "tires": tires_df,
        "inspection_records": pd.DataFrame(insp_rows),
        "operational_cycles": pd.DataFrame(cycle_rows),
        "station_stock": pd.DataFrame(station_rows),
        "_ground_truth": pd.DataFrame(gt_rows),
    }
    _coerce_dates(tables)
    return tables


def _simulate_position(
    *,
    cfg: GeneratorConfig,
    rng: np.random.Generator,
    id_rng: np.random.Generator,
    aircraft_id: str,
    pos: WheelPosition,
    base: float,
    landing_dates: list[date],
    f_load: np.ndarray,
    f_sev: np.ndarray,
    f_taxi: np.ndarray,
    f_temp: np.ndarray,
    infl: np.ndarray,
    noise: np.ndarray,
    accel_val: np.ndarray,
    uinfl_start: np.ndarray,
    fod_draw: np.ndarray,
    gauge: np.ndarray,
    gross: np.ndarray,
    wear_limit: float,
    tire_rows: list[dict],
    insp_rows: list[dict],
    gt_rows: list[dict],
) -> None:
    """Simulate the sequence of tire installations at one (aircraft, position) wheel."""
    n = len(landing_dates)
    insp_lo, insp_hi = int(cfg.inspection_interval_cycles[0]), int(cfg.inspection_interval_cycles[1])
    run_lo, run_hi = int(cfg.underinflation_run_cycles[0]), int(cfg.underinflation_run_cycles[1])

    def new_tire() -> dict:
        return {
            "tire_id": _uuid(id_rng),
            "brand": str(rng.choice(cfg.brands)),
            "new_tread": float(rng.uniform(*cfg.new_tread_mm)),
            "suscept": float(rng.lognormal(0.0, cfg.susceptibility_sigma)),
            "cycles_on": 0,
            "install_i": 0,
            "depth": 0.0,
            "next_insp": int(rng.integers(insp_lo, insp_hi + 1)),
        }

    tire = new_tire()
    tire["depth"] = tire["new_tread"]
    tire["install_i"] = 0
    in_run = 0
    run_mult = 1.0

    def close_tire(outcome: TireOutcome, end_i: int, censored: bool) -> None:
        cycles_on = tire["cycles_on"]
        realized_rate = (
            (tire["new_tread"] - tire["depth"]) / cycles_on if cycles_on > 0 else base
        )
        tire_rows.append(
            {
                "tire_id": tire["tire_id"],
                "aircraft_id": aircraft_id,
                "position_code": pos.value,
                "gear": pos.gear,
                "brand": tire["brand"],
                "serial": f"{tire['brand'][:2].upper()}{tire['tire_id'][:8]}",
                "tire_size": cfg.tire_size,
                "install_date": landing_dates[tire["install_i"]],
                "removal_date": (None if censored else landing_dates[end_i]),
                "new_tread_mm": round(tire["new_tread"], 3),
                "wear_limit_mm": wear_limit,
                "outcome": outcome.value,
                "censored": censored,
                "time_to_event_cycles": cycles_on,
                "is_current": censored,
            }
        )
        gt_rows.append(
            {
                "gt_key": f"tire:{tire['tire_id']}",
                "tire_id": tire["tire_id"],
                "inspection_id": None,
                "cycles_since_install": cycles_on,
                "true_groove_mm": round(tire["depth"], 4),
                "tire_true_new_tread_mm": round(tire["new_tread"], 4),
                "tire_true_wear_rate_mm_per_landing": round(realized_rate, 6),
            }
        )

    for i in range(n):
        # Underinflation run bookkeeping (per wheel).
        if in_run == 0 and uinfl_start[i]:
            in_run = int(rng.integers(run_lo, run_hi + 1))
            run_mult = float(rng.uniform(*cfg.underinflation_wear_multiplier))
        if in_run > 0:
            u_mult = run_mult
            in_run -= 1
            low_pressure = True
        else:
            u_mult = 1.0
            low_pressure = False

        wear = (
            base
            * f_load[i]
            * f_sev[i]
            * f_taxi[i]
            * f_temp[i]
            * infl[i]
            * noise[i]
            * tire["suscept"]
            * float(accel_val[i])
            * u_mult
        )
        tire["depth"] -= wear
        tire["cycles_on"] += 1

        # Inspection?
        if tire["cycles_on"] >= tire["next_insp"]:
            insp_id = _uuid(id_rng)
            true_groove = tire["depth"]
            measured = true_groove + gauge[i] + gross[i]
            measured = max(measured, 0.1)  # a gauge never reads below ~0
            if low_pressure:
                pressure_pct = float(rng.uniform(80.0, 94.0))
            else:
                pressure_pct = float(np.clip(rng.normal(100.5, 2.0), 92.0, 106.0))
            insp_rows.append(
                {
                    "inspection_id": insp_id,
                    "tire_id": tire["tire_id"],
                    "aircraft_id": aircraft_id,
                    "position_code": pos.value,
                    "inspection_date": landing_dates[i],
                    "cycles_since_install": tire["cycles_on"],
                    "measured_groove_mm": round(measured, 3),
                    "pressure_pct": round(pressure_pct, 2),
                }
            )
            gt_rows.append(
                {
                    "gt_key": f"insp:{insp_id}",
                    "tire_id": tire["tire_id"],
                    "inspection_id": insp_id,
                    "cycles_since_install": tire["cycles_on"],
                    "true_groove_mm": round(true_groove, 4),
                    "tire_true_new_tread_mm": round(tire["new_tread"], 4),
                    "tire_true_wear_rate_mm_per_landing": None,
                }
            )
            tire["next_insp"] += int(rng.integers(insp_lo, insp_hi + 1))

        # Removal?
        removed: TireOutcome | None = None
        if tire["depth"] <= wear_limit:
            removed = TireOutcome.WORN
        elif fod_draw[i] < cfg.fod_hazard_per_landing:
            removed = TireOutcome.EARLY_REMOVAL
        if removed is not None:
            close_tire(removed, end_i=i, censored=False)
            tire = new_tire()
            tire["depth"] = tire["new_tread"]
            tire["install_i"] = min(i + 1, n - 1)
            in_run = 0
            run_mult = 1.0

    # End of window: whatever is mounted is still in service (right-censored).
    close_tire(TireOutcome.IN_SERVICE, end_i=n - 1, censored=True)


def _coerce_dates(tables: dict[str, pd.DataFrame]) -> None:
    """Normalize all date columns to UTC timestamps (per project timezone rules)."""
    date_cols = {
        "aircraft": [],
        "tires": ["install_date", "removal_date"],
        "inspection_records": ["inspection_date"],
        "operational_cycles": ["cycle_date"],
    }
    for name, cols in date_cols.items():
        df = tables.get(name)
        if df is None or df.empty:
            continue
        for c in cols:
            tables[name][c] = pd.to_datetime(df[c], utc=True)


def write_tables(tables: dict[str, pd.DataFrame]) -> None:
    paths.ensure_dirs()
    tables["fleets"].to_parquet(paths.FLEETS, index=False)
    tables["aircraft"].to_parquet(paths.AIRCRAFT, index=False)
    tables["wheel_positions"].to_parquet(paths.WHEEL_POSITIONS, index=False)
    tables["tires"].to_parquet(paths.TIRES, index=False)
    tables["inspection_records"].to_parquet(paths.INSPECTION_RECORDS, index=False)
    tables["operational_cycles"].to_parquet(paths.OPERATIONAL_CYCLES, index=False)
    tables["station_stock"].to_parquet(paths.STATION_STOCK, index=False)
    tables["_ground_truth"].to_parquet(paths.GROUND_TRUTH, index=False)


def main() -> None:
    cfg = get_generator_config()
    tables = generate(cfg)
    write_tables(tables)
    t = tables["tires"]
    mix = t["outcome"].value_counts(normalize=True).to_dict()
    print(f"Wrote {len(tables['aircraft'])} aircraft, {len(t)} tires, "
          f"{len(tables['inspection_records'])} inspections, "
          f"{len(tables['operational_cycles'])} operational cycles to {paths.DATA_DIR}")
    print("Outcome mix:", {k: round(v, 3) for k, v in mix.items()})
    # Link mock-tyre scan packs (status / model_type / 3D defects) onto current tires.
    from app.tire_rul.enrich_tire_assets import enrich_tires

    enrich_tires(seed=cfg.seed)


# Convenience for tests: a small-fleet config override.
def small_config(cfg: GeneratorConfig | None = None, n_aircraft: int = 4) -> GeneratorConfig:
    cfg = cfg or get_generator_config()
    return replace(cfg, n_aircraft=n_aircraft)


if __name__ == "__main__":
    main()
