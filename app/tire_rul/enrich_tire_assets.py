"""Assign mock-tyre scan packs, tread-depth bands, and construction types onto tires.

Updates ``tires.parquet`` with:
  model_type, scan_group, scan_side, tread_depths (JSON list), scan_status,
  defects_3d (JSON — crack overlays only; healthy tires get []).

Status equation (see ``status_from_treads_and_cracks``):
  healthy — all treads in {4-5mm, 5-6mm}, no cracks → no 3D highlight
  warning — at least one 3-4mm tread (no worn bands, no cracks)
  error   — any tread in {1-2mm, 2-3mm} OR any crack

Tread groove counts: radial=6, type_vii=4, type_iii=4.
Both tires on the same gear share ``model_type``.
"""

from __future__ import annotations

import json
from itertools import cycle

import numpy as np
import pandas as pd

from app.tire_rul import paths
from app.tire_rul.scan_annotations import (
    SCAN_GROUPS,
    TREAD_COUNT,
    TireModelType,
    extract_cracks,
    images_for,
    status_from_treads_and_cracks,
    write_group_annotations,
)

MODEL_TYPES: tuple[TireModelType, ...] = ("radial", "type_vii", "type_iii")
# Target mix of demo conditions across current tires.
STATUS_CYCLE = ("healthy", "warning", "error")

GEAR_PAIRS: tuple[tuple[str, str], ...] = (
    ("nlg_l", "nlg_r"),
    ("mlg_l_inbd", "mlg_l_outbd"),
    ("mlg_r_inbd", "mlg_r_outbd"),
)


def _sample_treads(
    rng: np.random.Generator,
    model_type: TireModelType,
    target: str,
) -> list[str]:
    n = TREAD_COUNT[model_type]
    if target == "healthy":
        return [str(rng.choice(["4-5mm", "5-6mm"])) for _ in range(n)]
    if target == "warning":
        depths = [str(rng.choice(["4-5mm", "5-6mm"])) for _ in range(n)]
        depths[int(rng.integers(0, n))] = "3-4mm"
        return depths
    # error via worn groove (caller may also attach cracks)
    depths = [str(rng.choice(["3-4mm", "4-5mm", "5-6mm"])) for _ in range(n)]
    depths[int(rng.integers(0, n))] = str(rng.choice(["1-2mm", "2-3mm"]))
    return depths


def enrich_tires(*, seed: int = 20260712) -> pd.DataFrame:
    for group_id in SCAN_GROUPS:
        write_group_annotations(group_id)

    tires = pd.read_parquet(paths.TIRES)
    rng = np.random.default_rng(seed)

    drop_cols = (
        "scan_status",
        "model_type",
        "scan_group",
        "scan_side",
        "scan_profile",
        "defects_3d",
        "tread_depths",
    )
    for col in drop_cols:
        if col in tires.columns:
            tires = tires.drop(columns=[col])

    for col in (
        "scan_status",
        "model_type",
        "scan_group",
        "scan_side",
        "defects_3d",
        "tread_depths",
    ):
        tires[col] = pd.Series(pd.NA, index=tires.index, dtype="object")

    current = tires["is_current"].fillna(False).astype(bool)
    cur_idx = tires.index[current].tolist()
    rng.shuffle(cur_idx)

    groups = list(SCAN_GROUPS)
    rng.shuffle(groups)
    group_cycle = cycle(groups)
    status_targets = list(STATUS_CYCLE)
    rng.shuffle(status_targets)
    status_cycle = cycle(status_targets)

    pair_of = {pos: pair for pair in GEAR_PAIRS for pos in pair}
    model_by_gear: dict[tuple[str, tuple[str, str]], TireModelType] = {}

    for idx in cur_idx:
        row = tires.loc[idx]
        aircraft_id = str(row["aircraft_id"])
        position = str(row["position_code"])
        pair = pair_of.get(position)
        if pair is None:
            model_type: TireModelType = str(rng.choice(MODEL_TYPES))  # type: ignore[assignment]
        else:
            key = (aircraft_id, pair)
            if key not in model_by_gear:
                model_by_gear[key] = str(rng.choice(MODEL_TYPES))  # type: ignore[assignment]
            model_type = model_by_gear[key]

        # Any of the 4 scan groups; flatten side is fixed by condition.
        group_id = next(group_cycle)
        target = next(status_cycle)
        # healthy/warning → flatten-right; error → flatten-left (+ crack annotations)
        side = "left" if target == "error" else "right"

        tread_depths = _sample_treads(rng, model_type, target)
        if target == "error":
            defects = extract_cracks(group_id, "left")
            if not defects:
                tread_depths = _sample_treads(rng, model_type, "error")
        else:
            defects = []

        has_cracks = len(defects) > 0
        status = status_from_treads_and_cracks(tread_depths, has_cracks=has_cracks)
        # Keep side consistent with final status (error always left / else right).
        side = "left" if status == "error" else "right"

        tires.at[idx, "model_type"] = model_type
        tires.at[idx, "scan_group"] = group_id
        tires.at[idx, "scan_side"] = side
        tires.at[idx, "tread_depths"] = json.dumps(tread_depths)
        tires.at[idx, "scan_status"] = status
        tires.at[idx, "defects_3d"] = json.dumps(defects if status == "error" else [])

    hist = ~current
    tires.loc[hist, "model_type"] = tires.loc[hist, "model_type"].fillna("radial")

    paths.ensure_dirs()
    tires.to_parquet(paths.TIRES, index=False)

    cur = tires[current]
    print(
        f"Enriched {len(cur)} current tires · "
        f"status={cur['scan_status'].value_counts().to_dict()} · "
        f"model={cur['model_type'].value_counts().to_dict()} · "
        f"groups={cur['scan_group'].value_counts().to_dict()}"
    )
    # Smoke-check images helper stays importable for the API.
    sample = cur.iloc[0]
    _ = images_for(
        str(sample["scan_group"]),
        str(sample["scan_side"]),  # type: ignore[arg-type]
        scan_status=str(sample["scan_status"]),  # type: ignore[arg-type]
    )
    return tires


def main() -> None:
    enrich_tires()


if __name__ == "__main__":
    main()
