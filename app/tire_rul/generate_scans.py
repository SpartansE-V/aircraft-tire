"""Generate the imaging/scanning layer: a `tire_scans` record per currently-mounted tire.

Realizes the `tire_scans` table from DATA_SOURCES.md — the automated-diagnostics output
(laser tread depth + VLM damage + OCR serial). Depth comes from the latest inspection plus a
tighter *laser* precision noise; acute damage (cut/bulge/FOD) is injected on a small fraction
of tires so the wear-vs-damage split is demonstrable. Reproducible from the generator seed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.tire_rul import paths
from app.tire_rul.config import get_generator_config
from app.tire_rul.cv.images import DAMAGE_TYPES

DAMAGE_RATE = 0.06  # fraction of currently-mounted tires showing acute damage
LASER_PRECISION_SD = 0.12  # laser tread-depth noise (mm) — tighter than the 0.25mm manual gauge


def generate_scans(cfg=None) -> pd.DataFrame:
    cfg = cfg or get_generator_config()
    rng = np.random.default_rng(cfg.seed + 999)

    tires = pd.read_parquet(paths.TIRES)
    insp = pd.read_parquet(paths.INSPECTION_RECORDS)
    cur = tires[tires["is_current"]].copy()

    latest = (
        insp.sort_values("cycles_since_install").groupby("tire_id").tail(1).set_index("tire_id")["measured_groove_mm"]
    )
    as_of = pd.Timestamp(cfg.as_of_date, tz="UTC")

    rows = []
    for _, t in cur.iterrows():
        tid = t["tire_id"]
        base = float(latest.get(tid, t["new_tread_mm"]))
        laser = float(np.clip(base + rng.normal(0, LASER_PRECISION_SD), 0.1, t["new_tread_mm"]))
        damage = [str(rng.choice(DAMAGE_TYPES))] if rng.random() < DAMAGE_RATE else []
        rows.append(
            {
                "tire_id": tid,
                "serial": t["serial"],
                "new_tread_mm": float(t["new_tread_mm"]),
                "laser_groove_mm": round(laser, 2),
                "damage_findings": damage,
                "scan_confidence": round(float(rng.uniform(0.9, 0.98)), 2),
                "scan_date": as_of,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    paths.ensure_dirs()
    df = generate_scans()
    df.to_parquet(paths.TIRE_SCANS, index=False)
    n_damage = int(df["damage_findings"].apply(len).gt(0).sum())
    print(f"Wrote {len(df)} tire scans to {paths.TIRE_SCANS} ({n_damage} with acute damage flagged)")


if __name__ == "__main__":
    main()
