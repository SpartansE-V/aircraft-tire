from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    api_prefix: str
    colmap_binary: str
    workspace_root: Path
    images_root: Path
    outputs_root: Path
    default_camera_model: str
    default_matcher: str


def _path_from_env(name: str, default: Path) -> Path:
    raw_value = os.getenv(name)
    value = Path(raw_value).expanduser() if raw_value else default
    return value.resolve()


@lru_cache
def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[1]
    workspace_root = _path_from_env("COLMAP_WORKSPACE_ROOT", root_dir / "workspace")
    images_root = _path_from_env("COLMAP_IMAGES_ROOT", workspace_root / "images")
    outputs_root = _path_from_env("COLMAP_OUTPUTS_ROOT", workspace_root / "runs")
    return Settings(
        app_name="COLMAP Reconstruction API",
        api_prefix="/api/v1",
        colmap_binary=os.getenv("COLMAP_BINARY", "colmap"),
        workspace_root=workspace_root,
        images_root=images_root,
        outputs_root=outputs_root,
        default_camera_model=os.getenv("COLMAP_DEFAULT_CAMERA_MODEL", "SIMPLE_RADIAL"),
        default_matcher=os.getenv("COLMAP_DEFAULT_MATCHER", "exhaustive"),
    )


def ensure_directories(settings: Settings) -> None:
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.images_root.mkdir(parents=True, exist_ok=True)
    settings.outputs_root.mkdir(parents=True, exist_ok=True)
