"""Tools the Maintenance Decision Agent can call.

Each tool wraps a slice of the pipeline (RUL, CV scan, MEL dispatch, AMM thresholds, spares,
defect history) and returns JSON-serializable data. The agent (LLM tool-calling, or the offline
deterministic planner) composes these into a grounded maintenance decision. Tools are read-only —
the agent proposes work-order drafts, it never mutates state (human-in-the-loop).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.tire_rul import scoring
from app.tire_rul.config import ThresholdConfig
from app.tire_rul.constants import ALL_POSITIONS
from app.tire_rul.grounding import dispatch_for_wheel, extract_defect_log, grounded_thresholds
from app.tire_rul.grounding.defect_logs import POSITION_ALIASES

_VALID_POS = {p.value for p in ALL_POSITIONS}


def _norm_pos(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip().lower()
    if s in _VALID_POS:
        return s
    spaced = s.replace("_", " ")
    for alias, code in sorted(POSITION_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in spaced:
            return code
    return None


@dataclass
class ToolContext:
    tables: dict
    risks: list
    tc: ThresholdConfig
    as_of: date
    prior: dict | None = None  # MixedLM population prior (enables triggering fresh predictions)
    feats: object | None = None  # feature frame (readings per tire) for on-demand prediction
    _by: dict = field(default_factory=dict, repr=False)
    _tid: dict = field(default_factory=dict, repr=False)
    _scans: dict = field(default_factory=dict, repr=False)
    _ac_id: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._by = {(r.tail_number, r.position_code): r for r in self.risks}
        self._ac_id = {r.tail_number: r.aircraft_id for r in self.risks}
        cur = self.tables["tires"][self.tables["tires"]["is_current"]]
        self._tid = {(t.aircraft_id, t.position_code): t.tire_id for t in cur.itertuples()}
        scans = self.tables.get("tire_scans")
        self._scans = {row.tire_id: row for row in scans.itertuples()} if scans is not None else {}

    def risk(self, tail: str, position: str):
        return self._by.get((tail, _norm_pos(position)))


# ---------------------------------------------------------------------------
# Tool functions: (ctx, **args) -> dict
# ---------------------------------------------------------------------------
def list_priority_wheels(ctx: ToolContext, top_n: int = 10, station: str | None = None) -> dict:
    worklist = scoring.build_worklist(ctx.risks, ctx.tc)
    rows = []
    for w in worklist:
        r = ctx._by.get((w.tail_number, w.position_code))
        if station and (r is None or r.station != station):
            continue
        rows.append(
            {
                "tail": w.tail_number,
                "position": w.position_code,
                "priority": round(w.priority, 3),
                "rul_median_landings": round(w.rul_median),
                "p_cross_next_check": round(w.p_cross_next_check, 2),
                "earliest_date": w.earliest_date.isoformat(),
                "action": w.action,
            }
        )
        if len(rows) >= int(top_n):
            break
    return {"wheels": rows}


def get_wheel_status(ctx: ToolContext, tail: str, position: str) -> dict:
    r = ctx.risk(tail, position)
    if r is None:
        return {"error": f"no current wheel for {tail} {position}"}
    rep = scoring.tire_status_report(r, ctx.tc, ctx.as_of)
    e = r.estimate
    return {
        "tail": tail,
        "position": r.position_code,
        "status": rep.status,
        "headline": rep.headline,
        "rul_median_landings": round(e.rul_median),
        "rul_p10_landings": round(e.rul_p10),
        "earliest_credible_date": e.date_p10.isoformat(),
        "p_cross_next_check": round(e.p_cross_next_check, 2),
        "pressure_pct": None if r.pressure_pct is None else round(r.pressure_pct),
        "pressure_action": r.pressure_action,
        "station": r.station,
        "spares_on_hand": r.on_hand,
        "utilization_per_day": round(r.cycles_per_day, 1),
        "recommended_action": rep.recommended_action,
        "low_confidence": e.low_confidence,
    }


def get_tire_scan(ctx: ToolContext, tail: str, position: str) -> dict:
    ac_id = ctx._ac_id.get(tail)
    tid = ctx._tid.get((ac_id, _norm_pos(position)))
    row = ctx._scans.get(tid)
    if row is None:
        return {"error": "no scan for this wheel"}
    return {
        "serial": row.serial,
        "laser_groove_mm": round(float(row.laser_groove_mm), 2),
        "damage_findings": list(row.damage_findings),
        "scan_confidence": round(float(row.scan_confidence), 2),
    }


def check_dispatch(ctx: ToolContext, tail: str, position: str) -> dict:
    r = ctx.risk(tail, position)
    scan = get_tire_scan(ctx, tail, position)
    damage = scan.get("damage_findings", []) if "error" not in scan else []
    rep = scoring.tire_status_report(r, ctx.tc, ctx.as_of, damage_findings=damage) if r else None
    worn_damaged = bool(damage) or (rep is not None and rep.status == "replace_now")
    d = dispatch_for_wheel(worn_damaged, "worn/damaged tire" if worn_damaged else "serviceable tire")
    return {
        "dispatchable": d.dispatchable,
        "mel_item": d.mel_item,
        "category": d.category,
        "interval_days": d.interval_days,
        "provisions": d.provisions,
        "ref": d.ref,
        "acute_damage": bool(damage),
    }


def get_amm_thresholds(ctx: ToolContext) -> dict:
    return {
        "thresholds": [
            {"name": r["threshold"], "value": r["config"], "amm_ref": r["amm_ref"]} for r in grounded_thresholds(ctx.tc)
        ]
    }


def check_spares(ctx: ToolContext, station: str) -> dict:
    stock = dict(zip(ctx.tables["station_stock"]["station_code"], ctx.tables["station_stock"]["on_hand"], strict=False))
    demand = scoring.spares_demand(ctx.risks, stock, ctx.as_of, weeks=8)
    sd = [d for d in demand if d.station == station]
    stockout = next((d.week_start.isoformat() for d in sd if d.projected_stockout), None)
    on_hand = stock.get(station)
    return {
        "station": station,
        # Cast off pandas' numpy scalar so the result stays JSON-serializable (LLM loop + API).
        "on_hand": None if on_hand is None else int(on_hand),
        "projected_stockout_week": stockout,
        "next_weeks": [
            {"week": d.week_start.isoformat(), "expected": d.expected_demand, "p90": d.p90_demand} for d in sd[:6]
        ],
    }


def render_scan_image(ctx: ToolContext, tail: str, position: str):
    """Deterministically re-render a wheel's scan image (same recipe as the Tire Scan screen).

    Returns (PIL image | None, meta dict). Shared by get_damage_area and the chat UI so the
    annotated image an engineer sees matches what the tool analyzed.
    """
    import zlib

    from app.tire_rul.cv import render_tire_image

    ac_id = ctx._ac_id.get(tail)
    tid = ctx._tid.get((ac_id, _norm_pos(position)))
    if tid is None:
        return None, {"error": f"no current wheel for {tail} {position}"}
    row = ctx._scans.get(tid)
    tires = ctx.tables["tires"]
    trow = tires[tires["tire_id"] == tid].iloc[0]
    laser = float(row.laser_groove_mm) if row is not None else float(trow["new_tread_mm"])
    damage = list(row.damage_findings) if row is not None else []
    seed = int(zlib.crc32(str(tid).encode()) % (2**31))
    img = render_tire_image(
        laser, new_tread_mm=float(trow["new_tread_mm"]), damage=damage, serial=str(trow["serial"]), seed=seed
    )
    return img, {"serial": str(trow["serial"]), "laser_groove_mm": laser, "damage": damage, "tire_id": tid}


def get_damage_area(ctx: ToolContext, tail: str, position: str) -> dict:
    """Locate damage regions (type, pixel bbox, tread location) on the wheel's latest scan."""
    from app.tire_rul.cv import locate_damage

    img, meta = render_scan_image(ctx, tail, position)
    if img is None:
        return meta
    regions = locate_damage(img)
    return {
        "tail": tail,
        "position": _norm_pos(position),
        "serial": meta["serial"],
        "image_size": [img.width, img.height],
        "regions": regions,
        "note": "bbox = [x0, y0, x1, y1] in scan pixels",
    }


def run_rul_prediction(ctx: ToolContext, tail: str, position: str, utilization_override: float | None = None) -> dict:
    """Trigger a fresh RUL prediction (EB posterior + Monte-Carlo first-passage) for a wheel.

    With `utilization_override` (landings/day) the wear-to-limit dates are recomputed under that
    assumption. Falls back to the precomputed estimate if the model prior isn't loaded.
    """
    r = ctx.risk(tail, position)
    if r is None:
        return {"error": f"no current wheel for {tail} {position}"}
    lpd = float(utilization_override) if utilization_override else float(r.cycles_per_day)

    triggered = False
    e = r.estimate
    if ctx.prior is not None and ctx.feats is not None:
        ac_id = ctx._ac_id.get(tail)
        tid = ctx._tid.get((ac_id, r.position_code))
        g = ctx.feats[ctx.feats["tire_id"] == tid].sort_values("cycles_since_install")
        pmean, pcov, scale = scoring.prior_arrays(ctx.prior, r.position_code)
        rc = g["cycles_since_install"].to_numpy(dtype=float)
        rg = g["measured_groove_mm"].to_numpy(dtype=float)
        e = scoring.estimate_wheel(
            rc,
            rg,
            pmean,
            pcov,
            scale,
            current_cycles=float(rc[-1]) if len(rc) else 0.0,
            landings_per_day=lpd,
            as_of_date=ctx.as_of,
            limit_mm=ctx.tc.wear_limit_mm,
            mc_draws=ctx.tc.mc_draws,
            mc_seed=ctx.tc.mc_seed,
            next_check_cycles=ctx.tc.next_check_interval_cycles,
            n_readings=len(g),
            low_confidence_min_readings=ctx.tc.low_confidence_min_readings,
        )
        triggered = True
    return {
        "tail": tail,
        "position": r.position_code,
        "prediction_triggered": triggered,
        "mc_draws": ctx.tc.mc_draws,
        "utilization_landings_per_day": round(lpd, 1),
        "rul_landings": {"p10": round(e.rul_p10), "median": round(e.rul_median), "p90": round(e.rul_p90)},
        "wear_to_limit_date": {
            "earliest_credible_p10": e.date_p10.isoformat(),
            "median": e.date_median.isoformat(),
            "p90": e.date_p90.isoformat(),
        },
        "p_cross_next_check": round(e.p_cross_next_check, 2),
        "low_confidence": e.low_confidence,
    }


def search_defect_history(ctx: ToolContext, query: str) -> dict:
    logs = ctx.tables.get("defect_logs")
    if logs is None or not str(query).strip():
        return {"records": []}
    hits = logs[logs["raw_text"].str.contains(str(query), case=False, na=False)]
    recs = [extract_defect_log(t) for t in hits["raw_text"].head(8)]
    keys = ["date", "tail", "position_code", "serial", "removal_reason", "cycles"]
    return {"records": [{k: r[k] for k in keys} for r in recs]}


TOOL_FUNCS = {
    "list_priority_wheels": list_priority_wheels,
    "get_wheel_status": get_wheel_status,
    "get_tire_scan": get_tire_scan,
    "get_damage_area": get_damage_area,
    "run_rul_prediction": run_rul_prediction,
    "check_dispatch": check_dispatch,
    "get_amm_thresholds": get_amm_thresholds,
    "check_spares": check_spares,
    "search_defect_history": search_defect_history,
}


def _fn(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


_S = {"type": "string"}
_I = {"type": "integer"}

# OpenAI function-calling schemas for the tools above.
TOOL_SCHEMAS = [
    _fn(
        "list_priority_wheels",
        "Fleet-wide (or per-station) ranked worklist of wheels needing attention.",
        {"top_n": _I, "station": _S},
        [],
    ),
    _fn(
        "get_wheel_status",
        "RUL, wear-to-limit dates, pressure, station, spares and status for one wheel.",
        {"tail": _S, "position": _S},
        ["tail", "position"],
    ),
    _fn(
        "get_tire_scan",
        "Latest CV scan for a wheel: laser tread depth, VLM damage findings, OCR serial.",
        {"tail": _S, "position": _S},
        ["tail", "position"],
    ),
    _fn(
        "get_damage_area",
        "Locate damage regions on the wheel's scan: type, pixel bounding box, and tread location (e.g. 'upper center tread').",
        {"tail": _S, "position": _S},
        ["tail", "position"],
    ),
    _fn(
        "run_rul_prediction",
        "Trigger a fresh RUL prediction (Monte-Carlo) for a wheel; optional utilization_override in landings/day re-dates the forecast.",
        {"tail": _S, "position": _S, "utilization_override": {"type": "number"}},
        ["tail", "position"],
    ),
    _fn(
        "check_dispatch",
        "MEL/CDL dispatch decision for a wheel (dispatchable? category, rectification days).",
        {"tail": _S, "position": _S},
        ["tail", "position"],
    ),
    _fn("get_amm_thresholds", "The AMM-sourced thresholds the tool uses (wear limit, pressure ladder, etc.).", {}, []),
    _fn(
        "check_spares",
        "Spare-tire availability and projected weekly demand / stock-out for a station.",
        {"station": _S},
        ["station"],
    ),
    _fn(
        "search_defect_history",
        "Search historical free-text defect logs (by tail, serial, or keyword).",
        {"query": _S},
        ["query"],
    ),
]


def anthropic_tool_schemas() -> list[dict]:
    """TOOL_SCHEMAS converted to Anthropic Messages-API format (used by the Bedrock backend)."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in TOOL_SCHEMAS
    ]


def call_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"unknown tool '{name}'"}
    try:
        return fn(ctx, **(args or {}))
    except Exception as exc:  # a bad-arg tool call shouldn't kill the agent loop
        return {"error": f"{type(exc).__name__}: {exc}"}
