from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    api_prefix: str
    workspace_root: Path
    images_root: Path
    outputs_root: Path
    # MASt3R model + inference settings.
    mast3r_model_name: str
    mast3r_device: str  # "auto" | "cuda" | "cpu"
    image_size: int  # 512 (recommended) or 224
    min_conf_thr: float
    optim_level: str  # "coarse" | "refine" | "refine+depth"
    lr1: float
    niter1: int
    lr2: float
    niter2: int
    matching_conf_thr: float
    scene_graph: str  # "complete" | "swin-<n>" | "oneref-<i>" | ...
    shared_intrinsics: bool


def _path_from_env(name: str, default: Path) -> Path:
    raw_value = os.getenv(name)
    value = Path(raw_value).expanduser() if raw_value else default
    return value.resolve()


@lru_cache
def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parents[1]
    workspace_root = _path_from_env("MAST3R_WORKSPACE_ROOT", root_dir / "workspace")
    images_root = _path_from_env("MAST3R_IMAGES_ROOT", workspace_root / "images")
    outputs_root = _path_from_env("MAST3R_OUTPUTS_ROOT", workspace_root / "runs")
    return Settings(
        app_name="MASt3R Reconstruction API",
        api_prefix="/api/v1",
        workspace_root=workspace_root,
        images_root=images_root,
        outputs_root=outputs_root,
        mast3r_model_name=os.getenv(
            "MAST3R_MODEL_NAME", "naver/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric"
        ),
        mast3r_device=os.getenv("MAST3R_DEVICE", "auto"),
        image_size=int(os.getenv("MAST3R_IMAGE_SIZE", "512")),
        min_conf_thr=float(os.getenv("MAST3R_MIN_CONF_THR", "1.5")),
        optim_level=os.getenv("MAST3R_OPTIM_LEVEL", "refine+depth"),
        lr1=float(os.getenv("MAST3R_LR1", "0.07")),
        niter1=int(os.getenv("MAST3R_NITER1", "300")),
        lr2=float(os.getenv("MAST3R_LR2", "0.01")),
        niter2=int(os.getenv("MAST3R_NITER2", "300")),
        matching_conf_thr=float(os.getenv("MAST3R_MATCHING_CONF_THR", "0.0")),
        scene_graph=os.getenv("MAST3R_SCENE_GRAPH", "complete"),
        shared_intrinsics=os.getenv("MAST3R_SHARED_INTRINSICS", "false").strip().lower()
        in {"1", "true", "yes"},
    )


def ensure_directories(settings: Settings) -> None:
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    settings.images_root.mkdir(parents=True, exist_ok=True)
    settings.outputs_root.mkdir(parents=True, exist_ok=True)
