from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from ..services.uploads import UploadService

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _get_service(request: Request) -> UploadService:
    return request.app.state.upload_service


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_images(
    request: Request,
    files: list[UploadFile] = File(..., description="One or more image files."),
    overwrite: bool = Form(default=False),
) -> dict[str, object]:
    service = _get_service(request)
    try:
        return await service.save_images(files=files, overwrite=overwrite)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
