"""Remaining-useful-life (RUL) prediction endpoint — the AI model behind the API."""

from fastapi import APIRouter

from app.api.errors import ErrorResponse
from app.domain.schemas import RulPredictionRequest, RulPredictionResponse
from app.services.rul_service import rul_service

router = APIRouter(prefix="/api/v1/rul", tags=["RUL Prediction"])


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
