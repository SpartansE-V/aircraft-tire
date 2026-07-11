from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .domain import ReconstructionOptions

_OPTIM_LEVELS = {"coarse", "refine", "refine+depth"}


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
    image_size: int = Field(default=512, description="MASt3R input size: 512 (recommended) or 224.")
    min_conf_thr: float = Field(default=1.5, ge=0.0, description="Confidence threshold for the exported cloud.")
    optim_level: str | None = Field(default=None, description="coarse | refine | refine+depth.")
    scene_graph: str | None = Field(default=None, description="Pairing graph, e.g. 'complete', 'swin-3', 'oneref-0'.")
    shared_intrinsics: bool = Field(default=False, description="Assume one shared camera intrinsic for all images.")
    lr1: float | None = Field(default=None, description="Coarse-alignment learning rate.")
    niter1: int | None = Field(default=None, ge=0, description="Coarse-alignment iterations.")
    lr2: float | None = Field(default=None, description="Fine-alignment learning rate.")
    niter2: int | None = Field(default=None, ge=0, description="Fine-alignment iterations.")
    matching_conf_thr: float | None = Field(default=None, description="Matching confidence threshold.")
    device: str | None = Field(default=None, description="'cuda' or 'cpu'; defaults to server auto-detect.")

    @field_validator("image_size")
    @classmethod
    def validate_image_size(cls, value: int) -> int:
        if value not in {224, 512}:
            raise ValueError("image_size must be 224 or 512")
        return value

    @field_validator("optim_level")
    @classmethod
    def validate_optim_level(cls, value: str | None) -> str | None:
        if value is not None and value not in _OPTIM_LEVELS:
            raise ValueError(f"optim_level must be one of {sorted(_OPTIM_LEVELS)}")
        return value

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str | None) -> str | None:
        if value is not None and value not in {"cuda", "cpu"}:
            raise ValueError("device must be 'cuda' or 'cpu'")
        return value

    def to_options(self, settings: Settings) -> ReconstructionOptions:
        return ReconstructionOptions(
            project_id=self.project_id,
            image_dir=self._resolve_image_dir(settings),
            image_size=self.image_size,
            min_conf_thr=self.min_conf_thr,
            optim_level=self.optim_level or settings.optim_level,
            lr1=self.lr1 if self.lr1 is not None else settings.lr1,
            niter1=self.niter1 if self.niter1 is not None else settings.niter1,
            lr2=self.lr2 if self.lr2 is not None else settings.lr2,
            niter2=self.niter2 if self.niter2 is not None else settings.niter2,
            matching_conf_thr=(
                self.matching_conf_thr if self.matching_conf_thr is not None else settings.matching_conf_thr
            ),
            scene_graph=self.scene_graph or settings.scene_graph,
            shared_intrinsics=self.shared_intrinsics,
            device=self.device,
        )

    def _resolve_image_dir(self, settings: Settings) -> str:
        """Infer the workspace-relative image directory from the upload project_id."""
        workspace_root = settings.workspace_root.resolve()
        project_dir = (settings.images_root / self.project_id).resolve()
        try:
            relative = project_dir.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("Configured images directory is outside the workspace root.") from exc
        return str(relative).replace("\\", "/")
