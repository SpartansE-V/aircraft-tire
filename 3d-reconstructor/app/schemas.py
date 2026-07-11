from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .domain import ReconstructionOptions


class ReconstructionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(
        ...,
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        description=(
            "Upload id (the project_uuid returned by POST /uploads/images). "
            "The image directory is inferred from it and it names the output run folder."
        ),
    )
    camera_model: str | None = Field(default=None, description="COLMAP ImageReader camera model.")
    matcher: str | None = Field(default=None, description="Either exhaustive or sequential.")
    dense: bool = Field(default=False, description="Enable dense reconstruction steps.")
    use_gpu: bool = Field(default=False, description="Enable GPU flags for SIFT and matching.")
    image_list_path: str | None = Field(default=None, description="Optional image list file relative to the workspace.")
    max_image_size: int | None = Field(default=None, ge=256, description="Optional max image size for undistortion.")

    @field_validator("matcher")
    @classmethod
    def validate_matcher(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in {"exhaustive", "sequential"}:
            raise ValueError("matcher must be either 'exhaustive' or 'sequential'")
        return value

    def to_options(self, settings: Settings) -> ReconstructionOptions:
        return ReconstructionOptions(
            project_id=self.project_id,
            image_dir=self._resolve_image_dir(settings),
            camera_model=self.camera_model or settings.default_camera_model,
            matcher=self.matcher or settings.default_matcher,
            dense=self.dense,
            use_gpu=self.use_gpu,
            image_list_path=self.image_list_path,
            max_image_size=self.max_image_size,
        )

    def _resolve_image_dir(self, settings: Settings) -> str:
        """Infer the workspace-relative image directory from the upload project_id.

        Mirrors how UploadService lays out uploads (images_root / project_id) so a
        project_id returned by the upload endpoint maps back to the same folder.
        """
        workspace_root = settings.workspace_root.resolve()
        project_dir = (settings.images_root / self.project_id).resolve()
        try:
            relative = project_dir.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("Configured images directory is outside the workspace root.") from exc
        return str(relative).replace("\\", "/")

