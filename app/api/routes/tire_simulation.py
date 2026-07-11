"""Demonstration-only v2 tire profile and scenario-simulation endpoints."""

from fastapi import APIRouter

from app.api.errors import ErrorResponse
from app.domain.simulation_schemas import (
    SimulationProfileCatalog,
    TireSimulationRequest,
    TireSimulationResponse,
)
from app.services.tire_simulator import tire_simulator

router = APIRouter(prefix="/api/v2", tags=["Tire Simulation"])


@router.get(
    "/tire-profiles",
    response_model=SimulationProfileCatalog,
    summary="List demonstration simulation profiles",
    description=(
        "List server-controlled pilot profiles. These profiles contain modeling assumptions only; "
        "they do not contain approved aircraft or tire limits."
    ),
)
async def list_tire_profiles() -> SimulationProfileCatalog:
    return tire_simulator.list_profiles()


@router.post(
    "/tire-simulations",
    response_model=TireSimulationResponse,
    summary="Simulate a future tire-wear scenario",
    description=(
        "Run a reproducible, uncalibrated scenario simulation from measured tire condition and "
        "bounded future operating assumptions. Results include uncertainty ranges and an explicit "
        "pressure-policy comparison. The endpoint does not provide certified limits, determine "
        "serviceability, authorize dispatch, or replace approved maintenance data and inspection."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Malformed JSON request body."},
        422: {"model": ErrorResponse, "description": "One or more inputs are invalid."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
async def simulate_tire_scenario(request: TireSimulationRequest) -> TireSimulationResponse:
    return tire_simulator.simulate(request)
