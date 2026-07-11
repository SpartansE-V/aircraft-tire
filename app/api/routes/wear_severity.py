"""Wear-severity calculator endpoint."""

from fastapi import APIRouter

from app.api.errors import ErrorResponse
from app.domain.schemas import WearSeverityRequest, WearSeverityResponse
from app.services.wear_calculator import calculator

router = APIRouter(prefix="/api/v1/wear-severity", tags=["Wear Severity"])


@router.post(
    "/calculate",
    response_model=WearSeverityResponse,
    response_model_exclude_none=True,
    summary="Calculate tire-wear severity",
    description=(
        "Estimate tire-wear severity from aircraft operating conditions for a main-gear or "
        "nose-gear tire. Results support inspection planning only and do not replace physical "
        "inspection, approved maintenance manuals, or qualified engineering approval."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Malformed JSON request body."},
        422: {"model": ErrorResponse, "description": "One or more inputs are invalid."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
async def calculate_wear_severity(request: WearSeverityRequest) -> WearSeverityResponse:
    return calculator.calculate(request)
