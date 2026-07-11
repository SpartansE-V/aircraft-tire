from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from .config import ensure_directories, get_settings
from .job_store import JobStore
from .routes.health import router as health_router
from .routes.reconstructions import router as reconstructions_router
from .routes.uploads import router as uploads_router
from .services.mast3r_reconstructor import Mast3rService
from .services.uploads import UploadService


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_directories(settings)

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.state.job_store = JobStore()
    app.state.reconstruction_service = Mast3rService(settings=settings, store=app.state.job_store)
    app.state.upload_service = UploadService(settings=settings)

    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(reconstructions_router, prefix=settings.api_prefix)
    app.include_router(uploads_router, prefix=settings.api_prefix)

    _patch_binary_upload_docs(app)
    return app


def _patch_binary_upload_docs(app: FastAPI) -> None:
    """Make Swagger UI render a file picker for upload fields."""
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()  # cached on app.openapi_schema; patch is idempotent
        _add_binary_format(schema)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def _add_binary_format(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "string" and node.get("contentMediaType") == "application/octet-stream":
            node["format"] = "binary"
        for value in node.values():
            _add_binary_format(value)
    elif isinstance(node, list):
        for value in node:
            _add_binary_format(value)


app = create_app()
