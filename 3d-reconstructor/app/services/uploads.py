from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from ..config import Settings
from ..domain import UploadBatch, utc_now

SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
}


class UploadService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def save_images(
        self,
        *,
        files: list[UploadFile],
        overwrite: bool = False,
    ) -> dict[str, object]:
        workspace_root = self.settings.workspace_root.resolve()
        project_uuid = str(uuid.uuid4())
        if not files:
            raise ValueError("At least one file is required.")

        target_dir = (self.settings.images_root / project_uuid).resolve()
        try:
            target_dir.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("Upload target must stay inside the configured workspace.") from exc

        if target_dir.exists() and any(target_dir.iterdir()) and not overwrite:
            raise ValueError(
                "Target upload directory already exists and is not empty. Set overwrite=true to replace it."
            )

        target_dir.mkdir(parents=True, exist_ok=True)

        saved_files: list[str] = []
        for upload in files:
            source_name = upload.filename or ""
            safe_name = self._normalize_filename(source_name)
            destination = target_dir / safe_name
            destination.relative_to(target_dir)

            if destination.exists() and not overwrite:
                raise ValueError(f"File already exists: {safe_name}. Set overwrite=true to replace it.")

            await upload.seek(0)
            with destination.open("wb") as buffer:
                shutil.copyfileobj(upload.file, buffer)
            saved_files.append(safe_name)
            await upload.close()

        image_dir = str(target_dir.relative_to(workspace_root)).replace("\\", "/")
        payload = UploadBatch(
            project_uuid=project_uuid,
            image_dir=image_dir,
            absolute_dir=str(target_dir),
            file_count=len(saved_files),
            files=saved_files,
            created_at=utc_now(),
        )
        return payload.to_dict()

    def _normalize_filename(self, filename: str) -> str:
        if not filename:
            raise ValueError("Every uploaded file must have a filename.")

        basename = Path(filename).name.strip()
        if not basename:
            raise ValueError("Every uploaded file must have a valid filename.")

        extension = Path(basename).suffix.lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{extension or '<none>'}'. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}"
            )

        stem = SAFE_FILENAME_PATTERN.sub("-", Path(basename).stem).strip("-._")
        if not stem:
            raise ValueError(f"Invalid filename: {filename}")
        return f"{stem}{extension}"
