"""FastAPI application entry point."""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api.errors import install_error_handlers, internal_error_response
from app.api.routes.crack_detector import router as crack_detector_router
from app.api.routes.health import router as health_router
from app.api.routes.tread_depth import router as tread_depth_router
from app.api.routes.wear_severity import router as wear_severity_router
from app.config import Settings, get_settings
from app.domain.schemas import RootResponse

SERVICE_NAME = "Aircraft Tire Wear Severity Calculator"
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
            "Estimate aircraft-tire wear severity for main-gear and nose-gear tires from "
            "operating conditions. Severity categories support inspection planning only. "
            "Results do not replace physical inspection, aircraft maintenance manuals, or "
            "qualified engineering approval."
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
    application.include_router(wear_severity_router)
    application.include_router(crack_detector_router)
    application.include_router(tread_depth_router)
    return application


app = create_app()
