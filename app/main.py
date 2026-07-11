"""FastAPI application entry point."""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from app.api.errors import install_error_handlers, internal_error_response
from app.api.routes.crack_detector import router as crack_detector_router
from app.api.routes.health import router as health_router
from app.api.routes.tire_assessment import router as tire_assessment_router
from app.api.routes.tire_rul import router as tire_rul_router
from app.api.routes.tread_depth import router as tread_depth_router
from app.config import Settings, get_settings
from app.domain.schemas import RootResponse
from app.tire_rul.mock_tyres_assets import (
    fetch_s3_object,
    local_file,
    s3_key_for,
)

SERVICE_NAME = "Aircraft Tire Assessment API"
SERVICE_VERSION = "1.0.0"

logger = logging.getLogger("wear_severity_api.requests")
logging.basicConfig(level=logging.INFO, format="%(message)s")

RequestHandler = Callable[[Request], Awaitable[Response]]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""

    runtime_settings = settings or get_settings()
    application = FastAPI(
        title=SERVICE_NAME,
        version=SERVICE_VERSION,
        description=(
            "Assess current and future aircraft-tire condition from measured condition and "
            "bounded operating assumptions. The active development release supports scenario "
            "planning only and does not replace physical inspection, approved maintenance data, "
            "or engineering approval."
        ),
        docs_url="/docs",
        redoc_url=None,
    )

    install_error_handlers(application)

    @application.middleware("http")
    async def request_context(request: Request, call_next: RequestHandler) -> Response:
        request_id = request.headers.get("X-Request-ID", "").strip() or str(uuid4())
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            response = internal_error_response()

        response.headers["X-Request-ID"] = request_id
        duration_ms = round((perf_counter() - started_at) * 1000, 3)
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "INFO" if response.status_code < 500 else "ERROR",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
                separators=(",", ":"),
            )
        )
        return response

    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @application.get(
        "/",
        response_model=RootResponse,
        tags=["Service"],
        summary="Get service metadata",
    )
    async def root() -> RootResponse:
        return RootResponse(
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            status="available",
            documentation="/docs",
        )

    application.include_router(health_router)
    application.include_router(tire_assessment_router)
    application.include_router(crack_detector_router)
    application.include_router(tread_depth_router)
    application.include_router(tire_rul_router)

    @application.get(
        "/assets/mock-tyres/{asset_path:path}",
        include_in_schema=False,
        name="mock-tyres",
    )
    async def mock_tyres_asset(asset_path: str) -> Response:
        """Serve scan images from disk when present, otherwise from the uploads bucket."""
        # Mounted URLs look like /assets/mock-tyres/release/1h233b/circle.png
        rel = (
            asset_path[len("release/") :]
            if asset_path.startswith("release/")
            else asset_path
        )

        disk = local_file(rel)
        if disk is not None:
            return FileResponse(disk)

        key = s3_key_for(rel)
        if key:
            fetched = fetch_s3_object(key)
            if fetched is not None:
                body, content_type = fetched
                return Response(content=body, media_type=content_type)

        raise HTTPException(status_code=404, detail="Mock tyre asset not found.")

    return application


app = create_app()
