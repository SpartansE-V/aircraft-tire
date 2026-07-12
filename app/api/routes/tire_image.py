"""Tire-photo upload + vision-assessment endpoint.

One request stores the photo (S3, via the AWS upload service) and screens it with the vision
model, returning a combined result. The browser calls this same-origin; the backend does the
cross-origin upload the browser cannot.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.errors import ErrorResponse
from app.config import get_settings
from app.domain.tire_image_schemas import TireImageAssessmentResponse
from app.services.tire_image_service import InvalidImageError, assess_tire_image

router = APIRouter(prefix="/api/v1/tire-image", tags=["Tire Image Assessment"])


@router.post(
    "/assess",
    response_model=TireImageAssessmentResponse,
    response_model_exclude_none=True,
    summary="Upload a tire photo and screen it with the vision model",
    description=(
        "Persist a tire photo to object storage and run a vision-language model over it, returning "
        "the storage location together with an acute-damage screen (cut / bulge / FOD) and a "
        "condition summary. Informational only: this does not determine serviceability or replace "
        "physical inspection and approved maintenance data."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Missing, non-image, or oversized upload."},
        422: {"model": ErrorResponse, "description": "Request validation failed."},
        503: {"model": ErrorResponse, "description": "Vision assessment stack unavailable."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
async def assess_tire_photo(
    image: Annotated[UploadFile, File(description="Tire photo (JPEG/PNG, <= 4 MB).")],
    tire_id: Annotated[str | None, Form(description="Wheel position, e.g. L1.")] = None,
    aircraft_id: Annotated[str | None, Form(description="Aircraft registration/tail.")] = None,
    backend: Annotated[
        str | None,
        Form(description="VLM backend override: auto | mock | openai | claude | bedrock."),
    ] = None,
) -> TireImageAssessmentResponse:
    settings = get_settings()

    if image.content_type and not image.content_type.startswith("image/"):
        raise _bad_request("INVALID_IMAGE_INPUT", "Uploaded file must be an image.")

    max_bytes = settings.uploads.max_upload_bytes
    limit_mb = max_bytes / (1024 * 1024)
    # Reject on the parser-reported size before pulling the body into a bytes object, so an
    # oversized upload can't exhaust memory. The post-read check is a fallback when size is unknown.
    if image.size is not None and image.size > max_bytes:
        raise _bad_request("IMAGE_TOO_LARGE", f"Image exceeds the {limit_mb:.0f} MB upload limit.")

    image_bytes = await image.read()
    if not image_bytes:
        raise _bad_request("INVALID_IMAGE_INPUT", "Uploaded image is empty.")
    if len(image_bytes) > max_bytes:
        raise _bad_request("IMAGE_TOO_LARGE", f"Image exceeds the {limit_mb:.0f} MB upload limit.")

    try:
        return await run_in_threadpool(
            assess_tire_image,
            image_bytes=image_bytes,
            filename=image.filename or "tire.jpg",
            content_type=image.content_type,
            tire_id=tire_id,
            aircraft_id=aircraft_id,
            backend=backend,
            settings=settings.uploads,
        )
    except InvalidImageError as exc:
        raise _bad_request("INVALID_IMAGE_INPUT", str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "ASSESSMENT_UNAVAILABLE", "message": str(exc)}},
        ) from exc


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": {"code": code, "message": message}})
