"""Canonical combined aircraft-tire assessment endpoint."""

from fastapi import APIRouter

from app.api.errors import ErrorResponse
from app.domain.assessment_schemas import TireAssessmentRequest, TireAssessmentResponse
from app.services.tire_assessor import tire_assessor

router = APIRouter(prefix="/api", tags=["Tire Assessment"])


@router.post(
    "/tire-assessments",
    response_model=TireAssessmentResponse,
    response_model_exclude_none=True,
    summary="Assess current and future aircraft-tire condition",
    description=(
        "Return representative-cycle severity, future tread distribution, pressure-policy "
        "comparison, current-condition status, scenario drivers, confidence, limitations, and "
        "inspection-planning guidance from one request. This demonstration endpoint does not "
        "determine serviceability or replace approved maintenance data and physical inspection."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Malformed JSON request body."},
        422: {"model": ErrorResponse, "description": "One or more inputs are invalid."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
async def assess_tire(request: TireAssessmentRequest) -> TireAssessmentResponse:
    return tire_assessor.assess(request)
