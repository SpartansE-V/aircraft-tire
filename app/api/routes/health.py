"""Health endpoint."""

from fastapi import APIRouter

from app.domain.schemas import HealthResponse

router = APIRouter(tags=["Service"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check service health",
)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy")
