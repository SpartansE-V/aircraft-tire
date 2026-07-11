from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.mast3r_reconstructor import Mast3rService

router = APIRouter(tags=["health"])


def _get_service(request: Request) -> Mast3rService:
    return request.app.state.reconstruction_service


@router.get("/health")
def healthcheck(request: Request) -> dict[str, object]:
    service = _get_service(request)
    return {
        "status": "ok",
        "service": request.app.title,
        "workspace_root": str(service.settings.workspace_root),
    }


@router.get("/runtime")
def runtime_info(request: Request) -> dict[str, object]:
    service = _get_service(request)
    return service.get_runtime_info()
