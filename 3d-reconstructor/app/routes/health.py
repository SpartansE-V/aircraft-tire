from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.colmap import ColmapService

router = APIRouter(tags=["health"])


def _get_service(request: Request) -> ColmapService:
    return request.app.state.colmap_service


@router.get("/health")
def healthcheck(request: Request) -> dict[str, object]:
    service = _get_service(request)
    return {
        "status": "ok",
        "service": request.app.title,
        "workspace_root": str(service.settings.workspace_root),
    }


@router.get("/colmap")
def colmap_info(request: Request) -> dict[str, object]:
    service = _get_service(request)
    return service.get_runtime_info()

