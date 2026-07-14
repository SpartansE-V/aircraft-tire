"""Maintenance Decision Agent service — bridges the FastAPI layer into app.tire_rul.agent.

Owns the fleet snapshot (`ToolContext`): parquet tables + fitted prior + per-inspection
features + per-wheel risk estimates, cached per as-of date. The agent itself (LLM
tool-calling loop, or the offline deterministic planner) lives in app.tire_rul.agent and is
reused untouched; this module only translates between the public API contract and it.

The fleet dataset and pandas belong to the `ai` extra — on a base install (or when the
data/artifacts folders are absent) every entry point raises AgentDataUnavailableError,
which the route layer maps to 503 so /api/v1/tire_rul/predict keeps working stand-alone.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import TYPE_CHECKING
from uuid import uuid4

from app.domain.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentToolCall,
    FleetWorklistResponse,
    InspectionReading,
    PriorityWheel,
    WheelStatusResponse,
)
from app.services.tire_rul_service import DISCLAIMER

if TYPE_CHECKING:
    from app.tire_rul.agent.tools import ToolContext


logger = logging.getLogger(__name__)


class AgentDataUnavailableError(RuntimeError):
    """The fleet dataset (or its `ai`-extra dependencies) is not available on this deploy."""


class AgentBackendError(RuntimeError):
    """An explicitly requested LLM backend failed (bad credentials, no model access, ...)."""


def _load_context(as_of: date) -> ToolContext:
    """Assemble the agent's ToolContext for one as-of date (cached via _cached_context)."""

    try:
        import pandas as pd

        from app.tire_rul.app import assemble_wheels
        from app.tire_rul.features import build_features
    except ImportError as exc:
        raise AgentDataUnavailableError(
            "The maintenance agent needs the AI stack (`uv sync --extra ai`)."
        ) from exc

    from app.tire_rul import paths
    from app.tire_rul.agent.tools import ToolContext
    from app.tire_rul.config import get_threshold_config

    missing = [p.name for p in (*paths.CORE_TABLES, paths.MIXEDLM_COV) if not p.exists()]
    if missing:
        raise AgentDataUnavailableError(
            f"Fleet dataset/artifacts not found ({', '.join(missing)}); "
            "run `make data` and `make train` first."
        )

    tables = {
        "aircraft": pd.read_parquet(paths.AIRCRAFT),
        "tires": pd.read_parquet(paths.TIRES),
        "inspection_records": pd.read_parquet(paths.INSPECTION_RECORDS),
        "operational_cycles": pd.read_parquet(paths.OPERATIONAL_CYCLES),
        "station_stock": pd.read_parquet(paths.STATION_STOCK),
        "tire_scans": pd.read_parquet(paths.TIRE_SCANS) if paths.TIRE_SCANS.exists() else None,
        "defect_logs": pd.read_parquet(paths.DEFECT_LOGS) if paths.DEFECT_LOGS.exists() else None,
    }
    with open(paths.MIXEDLM_COV, "rb") as prior_file:
        prior = pickle.load(prior_file)
    tc = get_threshold_config()
    feats = build_features(tables)
    risks = assemble_wheels(tables, feats, prior, tc, as_of)
    return ToolContext(tables=tables, risks=risks, tc=tc, as_of=as_of, prior=prior, feats=feats)


@lru_cache(maxsize=2)
def _cached_context(as_of: date) -> ToolContext:
    return _load_context(as_of)


class AgentService:
    """Serve the Maintenance Decision Agent and fleet worklist/status reads over one snapshot."""

    def _context(self) -> ToolContext:
        return _cached_context(datetime.now(UTC).date())

    def chat(self, request: AgentChatRequest) -> AgentChatResponse:
        from app.tire_rul.agent import MaintenanceAgent

        ctx = self._context()
        history = [m.model_dump() for m in request.messages]
        try:
            result = MaintenanceAgent(ctx, backend=request.backend).chat(history)
        except Exception as exc:
            # An LLM backend can fail at call time even when it looked available (expired
            # credentials, no model access, network). An explicit choice surfaces the failure;
            # 'auto' promises best-effort, so it degrades to the offline deterministic planner.
            if request.backend != "auto":
                logger.warning("Agent backend '%s' failed", request.backend, exc_info=exc)
                raise AgentBackendError(
                    f"The '{request.backend}' agent backend failed; check its credentials "
                    "or retry with backend='mock'."
                ) from exc
            logger.warning("Auto-selected LLM backend failed; using offline planner", exc_info=exc)
            result = MaintenanceAgent(ctx, backend="mock").chat(history)
            result["backend"] = "offline-mock (auto fallback)"
        # Tool results are arbitrary dicts and may carry numpy scalars from pandas frames;
        # round-trip through JSON (default=str) so the response always serializes.
        trace = [
            AgentToolCall(
                tool=t["tool"],
                args=json.loads(json.dumps(t["args"], default=str)),
                result=json.loads(json.dumps(t["result"], default=str)),
            )
            for t in result["trace"]
        ]
        return AgentChatResponse(
            chat_id=uuid4(),
            answer=result["answer"],
            trace=trace,
            backend=result["backend"],
            as_of_date=ctx.as_of,
            disclaimer=DISCLAIMER,
        )

    def fleet_worklist(self, top_n: int, station: str | None) -> FleetWorklistResponse:
        from app.tire_rul import scoring

        ctx = self._context()
        by_wheel = {(r.tail_number, r.position_code): r for r in ctx.risks}
        wheels: list[PriorityWheel] = []
        for row in scoring.build_worklist(ctx.risks, ctx.tc):
            risk = by_wheel[(row.tail_number, row.position_code)]
            if station and risk.station != station:
                continue
            wheels.append(
                PriorityWheel(
                    rank=len(wheels) + 1,
                    tail_number=row.tail_number,
                    position=row.position_code,
                    station=risk.station,
                    priority=round(row.priority, 3),
                    p_cross_before_next_check=round(row.p_cross_next_check, 4),
                    rul_median_landings=round(row.rul_median, 1),
                    rul_p10_landings=round(row.rul_p10, 1),
                    earliest_credible_date=row.earliest_date,
                    low_confidence=row.low_confidence,
                    reason=row.reason,
                    action=row.action,
                )
            )
            if len(wheels) >= top_n:
                break
        return FleetWorklistResponse(as_of_date=ctx.as_of, wheels=wheels, disclaimer=DISCLAIMER)

    def wheel_status(self, tail: str, position: str) -> WheelStatusResponse | None:
        from app.tire_rul import scoring
        from app.tire_rul.app import current_cycles_map
        from app.tire_rul.constants import PressureLadderAction

        ctx = self._context()
        risk = ctx.risk(tail, position)
        if risk is None:
            return None
        report = scoring.tire_status_report(risk, ctx.tc, ctx.as_of)
        estimate = risk.estimate
        consequence = scoring.consequence_weight(
            risk.position_code,
            risk.cycles_per_day,
            risk.on_hand,
            ctx.tc.priority,
            hard_landing_recent=risk.hard_landings_recent > 0,
            pressure_rule_active=risk.pressure_action
            in (PressureLadderAction.REMOVE.value, PressureLadderAction.REMOVE_TIRE_AND_MATE.value),
        )
        tires = ctx.tables["tires"]
        mounted = tires[
            (tires["is_current"])
            & (tires["aircraft_id"] == risk.aircraft_id)
            & (tires["position_code"] == risk.position_code)
        ]
        tire_id = mounted.iloc[0]["tire_id"]
        # Inspection history and landed-cycle count come from the feature frame and the
        # operational-cycles table. Both are optional on a minimal snapshot (a degraded deploy
        # without the model prior, or a hand-built context), so fall back to an empty history
        # there — mirroring how the agent's tools degrade when `feats`/`prior` are absent.
        readings: list[InspectionReading] = []
        newest_reading_cycles = 0.0
        if ctx.feats is not None:
            tire_features = ctx.feats[ctx.feats["tire_id"] == tire_id].sort_values(
                "cycles_since_install"
            )
            readings = [
                InspectionReading(
                    cycles_since_install=float(row.cycles_since_install),
                    measured_groove_mm=float(row.measured_groove_mm),
                )
                for row in tire_features.itertuples()
            ]
            if not tire_features.empty:
                newest_reading_cycles = float(tire_features["cycles_since_install"].max())
        if ctx.tables.get("operational_cycles") is not None:
            current_cycles = float(
                current_cycles_map(ctx.tables, ctx.as_of).get(tire_id, newest_reading_cycles)
            )
        else:
            current_cycles = newest_reading_cycles
        return WheelStatusResponse(
            tail_number=risk.tail_number,
            position=risk.position_code,
            status=report.status,
            severity=report.severity,
            headline=report.headline,
            explanation=report.explanation,
            recommended_action=report.recommended_action,
            rul_median_landings=round(estimate.rul_median, 1),
            rul_p10_landings=round(estimate.rul_p10, 1),
            earliest_credible_date=estimate.date_p10,
            p_cross_before_next_check=round(estimate.p_cross_next_check, 4),
            priority=round(scoring.priority_score(estimate.p_cross_next_check, consequence), 3),
            pressure_pct=None if risk.pressure_pct is None else round(risk.pressure_pct, 1),
            pressure_action=risk.pressure_action,
            station=risk.station,
            spares_on_hand=risk.on_hand,
            utilization_landings_per_day=round(risk.cycles_per_day, 1),
            current_cycles=current_cycles,
            readings=readings,
            low_confidence=estimate.low_confidence,
            as_of_date=ctx.as_of,
            disclaimer=DISCLAIMER,
        )


agent_service = AgentService()
