"""Remaining-useful-life (RUL) prediction and maintenance-agent endpoints."""

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api.errors import ErrorBody, ErrorResponse
from app.domain.schemas import (
    MAX_WORKLIST_TOP_N,
    AgentChatRequest,
    AgentChatResponse,
    FleetWorklistResponse,
    RulPredictionRequest,
    RulPredictionResponse,
    WheelStatusResponse,
)
from app.services.agent_service import (
    AgentBackendError,
    AgentDataUnavailableError,
    agent_service,
)
from app.services.rul_service import rul_service

router = APIRouter(prefix="/api/v1/rul", tags=["RUL Prediction"])

_FLEET_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {
        "model": ErrorResponse,
        "description": "The fleet dataset/AI stack is not available on this deployment.",
    }
}


def _fleet_unavailable_response(exc: AgentDataUnavailableError) -> JSONResponse:
    payload = ErrorResponse(error=ErrorBody(code="FLEET_DATA_UNAVAILABLE", message=str(exc)))
    return JSONResponse(status_code=503, content=payload.model_dump(exclude_none=True))


@router.post(
    "/predict",
    response_model=RulPredictionResponse,
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
async def predict_rul(request: RulPredictionRequest) -> RulPredictionResponse:
    return rul_service.predict(request)


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
