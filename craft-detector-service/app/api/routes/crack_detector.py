"""Tyre-quality detection endpoint backed by a Roboflow YOLO model."""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.errors import ErrorResponse
from app.config import get_settings
from app.domain.schemas import TyreQualityPrediction, TyreQualityResponse
from app.integrations.roboflow.controller import (
    ImageFetchError,
    ImageInputError,
    TyreQualityController,
)

router = APIRouter(prefix="/api/v1/crack-detector", tags=["Tyre Quality Detection"])


def _get_controller() -> TyreQualityController:
    settings = get_settings()
    return TyreQualityController(settings.roboflow)


@router.post(
    "/detect",
    response_model=TyreQualityResponse,
    response_model_exclude_none=True,
    summary="Detect tyre quality from an image",
    description=(
        "Run YOLO-based tyre-quality detection on an uploaded image or a public image URL. "
        "Supply exactly one input: multipart field `image` for file upload, or form field "
        "`image_url` for a publicly accessible http/https image."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Image input is missing or invalid."},
        422: {"model": ErrorResponse, "description": "Request validation failed."},
        502: {"model": ErrorResponse, "description": "Upstream image fetch or inference failed."},
        500: {"model": ErrorResponse, "description": "Unexpected server error."},
    },
)
async def detect_tyre_quality(
    image: Annotated[
        UploadFile | None,
        File(description="Image file upload."),
    ] = None,
    image_url: Annotated[
        str | None,
        Form(description="Public http/https image URL."),
    ] = None,
) -> TyreQualityResponse:
    controller = _get_controller()

    try:
        raw_predictions = await controller.detect(image=image, image_url=image_url)
    except ImageInputError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_IMAGE_INPUT",
                    "message": str(exc),
                }
            },
        ) from exc
    except ImageFetchError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "IMAGE_FETCH_FAILED",
                    "message": str(exc),
                }
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "INFERENCE_FAILED",
                    "message": str(exc),
                }
            },
        ) from exc

    predictions = [TyreQualityPrediction.model_validate(item) for item in raw_predictions]
    return TyreQualityResponse(predictions=predictions)
