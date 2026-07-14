"""Fleet tire dashboard reads — parquet tires enriched with scan packs for /tyres."""

from __future__ import annotations

import json
from typing import Any

from app.domain.schemas import (
    FleetAircraftItem,
    FleetAircraftListResponse,
    FleetTireItem,
    FleetTiresResponse,
    TireDefect3D,
    TireScanImages,
)
from app.services.agent_service import AgentDataUnavailableError
from app.tire_rul.scan_annotations import images_for


def _require_ai() -> Any:
    try:
        import pandas as pd

        return pd
    except ImportError as exc:
        raise AgentDataUnavailableError(
            "The fleet tire dashboard needs the AI stack (`uv sync --extra ai`)."
        ) from exc


def _load_tables() -> dict[str, Any]:
    pd = _require_ai()
    from app.tire_rul import paths

    if not paths.TIRES.exists() or not paths.AIRCRAFT.exists():
        raise AgentDataUnavailableError(
            "Fleet dataset not found; run `make data` and "
            "`python -m app.tire_rul.enrich_tire_assets` first."
        )
    tables = {
        "aircraft": pd.read_parquet(paths.AIRCRAFT),
        "tires": pd.read_parquet(paths.TIRES),
        "inspection_records": (
            pd.read_parquet(paths.INSPECTION_RECORDS)
            if paths.INSPECTION_RECORDS.exists()
            else pd.DataFrame()
        ),
    }
    if "scan_status" not in tables["tires"].columns or "tread_depths" not in tables["tires"].columns:
        raise AgentDataUnavailableError(
            "tires.parquet is missing scan/tread columns; run "
            "`python -m app.tire_rul.enrich_tire_assets`."
        )
    return tables


def _defect_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str) and raw:
        return list(json.loads(raw))
    if isinstance(raw, list):
        return list(raw)
    return []


def _tread_payload(raw: Any) -> list[str]:
    if isinstance(raw, str) and raw:
        return list(json.loads(raw))
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


class FleetTiresService:
    def list_aircraft(self) -> FleetAircraftListResponse:
        tables = _load_tables()
        ac = tables["aircraft"].sort_values("tail_number")
        return FleetAircraftListResponse(
            aircraft=[
                FleetAircraftItem(
                    tail_number=str(row.tail_number),
                    aircraft_id=str(row.aircraft_id),
                    aircraft_type=str(row.aircraft_type),
                    home_station=str(row.home_station),
                    cycles_per_day=float(row.cycles_per_day),
                )
                for row in ac.itertuples()
            ]
        )

    def tires_for_tail(self, tail: str) -> FleetTiresResponse | None:
        tables = _load_tables()
        ac = tables["aircraft"]
        match = ac[ac["tail_number"].astype(str).str.upper() == tail.strip().upper()]
        if match.empty:
            return None
        aircraft = match.iloc[0]
        aircraft_id = str(aircraft["aircraft_id"])

        tires = tables["tires"]
        mounted = tires[(tires["is_current"]) & (tires["aircraft_id"] == aircraft_id)].copy()
        if mounted.empty:
            return FleetTiresResponse(
                tail_number=str(aircraft["tail_number"]),
                aircraft_id=aircraft_id,
                aircraft_type=str(aircraft["aircraft_type"]),
                home_station=str(aircraft["home_station"]),
                tires=[],
            )

        insp = tables["inspection_records"]
        latest: dict[str, Any] = {}
        if not insp.empty:
            subset = insp[insp["tire_id"].isin(mounted["tire_id"])].sort_values(
                "cycles_since_install"
            )
            for tire_id, grp in subset.groupby("tire_id"):
                last = grp.iloc[-1]
                latest[str(tire_id)] = {
                    "measured_groove_mm": float(last["measured_groove_mm"]),
                    "pressure_pct": float(last["pressure_pct"]),
                }

        position_order = [
            "nlg_l",
            "nlg_r",
            "mlg_l_outbd",
            "mlg_l_inbd",
            "mlg_r_inbd",
            "mlg_r_outbd",
        ]
        mounted["_ord"] = mounted["position_code"].map(
            {p: i for i, p in enumerate(position_order)}
        )
        mounted = mounted.sort_values("_ord")

        items: list[FleetTireItem] = []
        for row in mounted.itertuples():
            group = str(row.scan_group)
            side = str(row.scan_side)
            status = str(row.scan_status)
            images = images_for(group, side, scan_status=status)  # type: ignore[arg-type]
            defects_payload = _defect_payload(getattr(row, "defects_3d", None))
            tread_depths = _tread_payload(getattr(row, "tread_depths", None))
            last = latest.get(str(row.tire_id), {})
            items.append(
                FleetTireItem(
                    tire_id=str(row.tire_id),
                    aircraft_id=aircraft_id,
                    tail_number=str(aircraft["tail_number"]),
                    position=str(row.position_code),  # type: ignore[arg-type]
                    gear=str(row.gear),  # type: ignore[arg-type]
                    brand=str(row.brand),
                    serial=str(row.serial),
                    tire_size=str(row.tire_size),
                    retread_level=int(getattr(row, "retread_level", 0) or 0),
                    new_tread_mm=float(row.new_tread_mm),
                    wear_limit_mm=float(row.wear_limit_mm),
                    time_to_event_cycles=int(row.time_to_event_cycles),
                    measured_groove_mm=last.get("measured_groove_mm"),
                    pressure_pct=last.get("pressure_pct"),
                    model_type=str(row.model_type),  # type: ignore[arg-type]
                    scan_status=status,  # type: ignore[arg-type]
                    scan_group=group,
                    scan_side=side,  # type: ignore[arg-type]
                    tread_depths=tread_depths,  # type: ignore[arg-type]
                    defects=[TireDefect3D(**d) for d in defects_payload],
                    images=TireScanImages(**images),
                )
            )

        return FleetTiresResponse(
            tail_number=str(aircraft["tail_number"]),
            aircraft_id=aircraft_id,
            aircraft_type=str(aircraft["aircraft_type"]),
            home_station=str(aircraft["home_station"]),
            tires=items,
        )


fleet_tires_service = FleetTiresService()
