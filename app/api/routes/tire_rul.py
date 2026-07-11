"""Remaining-useful-life (RUL) prediction and maintenance-agent endpoints."""

import threading
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from app.api.errors import ErrorBody, ErrorResponse
from app.domain.schemas import (
    MAX_WORKLIST_TOP_N,
    AgentChatRequest,
    AgentChatResponse,
    FleetAircraftListResponse,
    FleetTiresResponse,
    FleetWorklistResponse,
    StrictSchema,
    TireRulPredictionRequest,
    TireRulPredictionResponse,
    WheelStatusResponse,
)
from app.services.agent_service import (
    AgentBackendError,
    AgentDataUnavailableError,
    agent_service,
)
from app.services.fleet_tires_service import fleet_tires_service
from app.services.tire_rul_service import tire_rul_service
from app.tire_rul.enrich_tire_assets import enrich_tires

# RUL stands for Remaining Useful Life
router = APIRouter(prefix="/api/v1/tire_rul", tags=["Tire Remaining Useful Life Prediction"])

_ENRICH_LOCK = threading.Lock()
_DEFAULT_ENRICH_SEED = 20260712

_FLEET_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {
        "model": ErrorResponse,
        "description": "The fleet dataset/AI stack is not available on this deployment.",
    }
}


class EnrichTireAssetsResponse(StrictSchema):
    """Summary after rewriting tires.parquet scan packs."""

    seed: int
    current_tires: int = Field(ge=0)
    status_counts: dict[str, int]
    model_counts: dict[str, int]
    group_counts: dict[str, int]


def _fleet_unavailable_response(exc: AgentDataUnavailableError) -> JSONResponse:
    payload = ErrorResponse(error=ErrorBody(code="FLEET_DATA_UNAVAILABLE", message=str(exc)))
    return JSONResponse(status_code=503, content=payload.model_dump(exclude_none=True))


@router.post(
    "/predict",
    response_model=TireRulPredictionResponse,
    response_model_exclude_none=True,
    summary="Predict tire remaining useful life",
    description=(
        "Forecast a tire's remaining useful life (landings to the wear limit) and wear-to-limit "
        "dates from its tread-depth readings and utilization, using the fitted population "
        "degradation prior. Results support inspection planning only and do not replace physical "
        "inspection, approved maintenance manuals, or qualified engineering approval."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Malformed JSON request body."},
        422: {"model": ErrorResponse, "description": "One or more inputs are invalid."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
async def predict_rul(request: TireRulPredictionRequest) -> TireRulPredictionResponse:
    return tire_rul_service.predict(request)


# The agent/fleet handlers are sync (`def`) on purpose: FastAPI runs them in its threadpool,
# so a slow LLM tool-calling loop never blocks the event loop.
@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Chat with the maintenance decision agent",
    description=(
        "Ask the tire-maintenance agent a natural-language question ('what should I do about "
        "VN-A320's main gear?', 'plan tonight's tire maintenance for SGN'). The agent "
        "investigates by calling pipeline tools (RUL forecast, CV scan, MEL dispatch, spares, "
        "defect history), and returns a grounded Markdown answer plus its tool-call trace. "
        "Stateless: send the full conversation each call, ending with the newest user message."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Malformed JSON request body."},
        422: {"model": ErrorResponse, "description": "One or more inputs are invalid."},
        502: {
            "model": ErrorResponse,
            "description": "The explicitly requested LLM backend failed.",
        },
        **_FLEET_UNAVAILABLE,
    },
)
def agent_chat(request: AgentChatRequest) -> AgentChatResponse | JSONResponse:
    try:
        return agent_service.chat(request)
    except AgentDataUnavailableError as exc:
        return _fleet_unavailable_response(exc)
    except AgentBackendError as exc:
        payload = ErrorResponse(error=ErrorBody(code="AGENT_BACKEND_FAILED", message=str(exc)))
        return JSONResponse(status_code=502, content=payload.model_dump(exclude_none=True))


@router.get(
    "/fleet/worklist",
    response_model=FleetWorklistResponse,
    summary="Ranked maintenance worklist for the fleet",
    description=(
        "Wheels ranked by composite priority — P(cross the wear limit before the next check) x "
        "consequence (utilization, position, spares) — with plain-language reasons and "
        "recommended actions. Optionally filtered to one station."
    ),
    responses=_FLEET_UNAVAILABLE,
)
def fleet_worklist(
    top_n: int = Query(default=10, ge=1, le=MAX_WORKLIST_TOP_N),
    station: str | None = Query(default=None, max_length=8),
) -> FleetWorklistResponse | JSONResponse:
    try:
        return agent_service.fleet_worklist(top_n=top_n, station=station)
    except AgentDataUnavailableError as exc:
        return _fleet_unavailable_response(exc)


@router.get(
    "/wheel/status",
    response_model=WheelStatusResponse,
    summary="Condition and forecast for one mounted wheel",
    description=(
        "Current status report for a wheel of the fleet: condition category, RUL quantiles, "
        "wear-to-limit dates, pressure ladder, spares at the home station, and the recommended "
        "action. Position accepts codes (mlg_l_inbd) or plain language ('left main inboard')."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No current wheel for that tail/position."},
        **_FLEET_UNAVAILABLE,
    },
)
def wheel_status(
    tail: str = Query(max_length=16),
    position: str = Query(max_length=32),
) -> WheelStatusResponse | JSONResponse:
    try:
        status = agent_service.wheel_status(tail=tail, position=position)
    except AgentDataUnavailableError as exc:
        return _fleet_unavailable_response(exc)
    if status is None:
        payload = ErrorResponse(
            error=ErrorBody(
                code="WHEEL_NOT_FOUND",
                message=f"No current wheel for {tail} at position '{position}'.",
            )
        )
        return JSONResponse(status_code=404, content=payload.model_dump(exclude_none=True))
    return status


@router.get(
    "/fleet/aircraft",
    response_model=FleetAircraftListResponse,
    summary="List fleet aircraft tails",
    description="Aircraft available for the /tyres dashboard (from aircraft.parquet).",
    responses=_FLEET_UNAVAILABLE,
)
def fleet_aircraft() -> FleetAircraftListResponse | JSONResponse:
    try:
        return fleet_tires_service.list_aircraft()
    except AgentDataUnavailableError as exc:
        return _fleet_unavailable_response(exc)


@router.get(
    "/fleet/tires",
    response_model=FleetTiresResponse,
    summary="Current tires for one aircraft (scan status + 3D defects)",
    description=(
        "Currently-mounted tires for a tail: construction model_type, scan_status "
        "(healthy / warning / error from crack & tread-shallow annotations), linked "
        "mock-tyre frame images, and 3D defect overlays for the /tyres viewer."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Unknown tail number."},
        **_FLEET_UNAVAILABLE,
    },
)
def fleet_tires(
    tail: str = Query(max_length=16, description="Aircraft tail number, e.g. VN-A300"),
) -> FleetTiresResponse | JSONResponse:
    try:
        payload = fleet_tires_service.tires_for_tail(tail)
    except AgentDataUnavailableError as exc:
        return _fleet_unavailable_response(exc)
    if payload is None:
        body = ErrorResponse(
            error=ErrorBody(code="AIRCRAFT_NOT_FOUND", message=f"No aircraft with tail '{tail}'.")
        )
        return JSONResponse(status_code=404, content=body.model_dump(exclude_none=True))
    return payload


@router.post(
    "/fleet/enrich-scans",
    response_model=EnrichTireAssetsResponse,
    summary="Re-enrich fleet tires with mock-tyre scan packs",
    description=(
        "Runs the same job as `python -m app.tire_rul.enrich_tire_assets`: assigns scan "
        "groups, tread-depth bands, construction types, and 3D crack overlays onto "
        "tires.parquet. Deterministic for a fixed seed. Concurrent runs are rejected."
    ),
    responses={
        409: {
            "model": ErrorResponse,
            "description": "An enrich job is already running.",
        },
        **_FLEET_UNAVAILABLE,
    },
)
def enrich_fleet_scans(
    seed: int = Query(
        default=_DEFAULT_ENRICH_SEED,
        ge=0,
        description="RNG seed for deterministic scan/status assignment.",
    ),
) -> EnrichTireAssetsResponse | JSONResponse:
    if not _ENRICH_LOCK.acquire(blocking=False):
        payload = ErrorResponse(
            error=ErrorBody(
                code="ENRICH_IN_PROGRESS",
                message="An enrich-scans job is already running.",
            )
        )
        return JSONResponse(status_code=409, content=payload.model_dump(exclude_none=True))

    try:
        try:
            tires = enrich_tires(seed=seed)
        except ImportError:
            return _fleet_unavailable_response(
                AgentDataUnavailableError(
                    "Enriching tire scan packs needs the AI stack (`uv sync --extra ai`)."
                )
            )
        except FileNotFoundError as exc:
            detail = str(exc).strip() or (
                "Fleet dataset or mock-tyre assets not found; "
                "run `make data` locally or bake assets/mock-tyres/release into the image."
            )
            return _fleet_unavailable_response(AgentDataUnavailableError(detail))
        except AgentDataUnavailableError as exc:
            return _fleet_unavailable_response(exc)

        current = tires[tires["is_current"].fillna(False).astype(bool)]
        return EnrichTireAssetsResponse(
            seed=seed,
            current_tires=int(len(current)),
            status_counts={
                str(k): int(v) for k, v in current["scan_status"].value_counts().items()
            },
            model_counts={
                str(k): int(v) for k, v in current["model_type"].value_counts().items()
            },
            group_counts={
                str(k): int(v) for k, v in current["scan_group"].value_counts().items()
            },
        )
    finally:
        _ENRICH_LOCK.release()
