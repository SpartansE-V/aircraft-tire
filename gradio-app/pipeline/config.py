"""Environment-backed configuration for the combined reconstruction app.

Reconstruction is delegated to the MASt3R HTTP service (3d-reconstructor).
Detection model ids / thresholds mirror ``app/config/config.yaml`` (crack detector).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DetectionModel:
    key: str
    label: str
    model_id: str
    model_confidence_threshold: float
    filter_confidence_threshold: float


DETECTION_MODELS: dict[str, DetectionModel] = {
    "crack": DetectionModel(
        key="crack",
        label="Crack / tyre quality",
        model_id=os.getenv("CRACK_MODEL_ID", "tyre-quality-qccvy/1"),
        model_confidence_threshold=0.2,
        filter_confidence_threshold=0.5,
    ),
    "tread": DetectionModel(
        key="tread",
        label="Tread depth",
        model_id=os.getenv("TREAD_MODEL_ID", "tyre_tread_depth_set/1"),
        model_confidence_threshold=0.2,
        filter_confidence_threshold=0.5,
    ),
}

DEFAULT_DETECTION_MODEL = "crack"
OPTIM_LEVELS = ["refine+depth", "refine", "coarse"]


@dataclass(frozen=True, slots=True)
class Config:
    reconstructor_api_url: str
    reconstructor_poll_interval: float
    reconstructor_job_timeout: float
    # MASt3R reconstruction defaults (surfaced in the UI).
    default_image_size: int
    default_min_conf_thr: float
    default_optim_level: str
    roboflow_api_url: str
    roboflow_api_key: str
    max_upload_bytes: int
    workspace_root: Path
    # Colour applied to 3D points that fall inside a detected defect region.
    defect_color: tuple[int, int, int]

    @property
    def has_roboflow_key(self) -> bool:
        return bool(self.roboflow_api_key.strip())


def _path_from_env(name: str, default: Path) -> Path:
    raw_value = os.getenv(name)
    value = Path(raw_value).expanduser() if raw_value else default
    return value.resolve()


def _load_local_dotenv() -> None:
    """Populate os.environ from the app's local .env (if present).

    Without this, running `python app.py` without first `source`-ing .env leaves
    RECONSTRUCTOR_API_URL unset -> it defaults to http://localhost:8000 and silently
    talks to a local reconstructor instead of the configured (e.g. deployed) one.
    Real exported env vars win (setdefault), so `source .env` still overrides.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@lru_cache
def get_config() -> Config:
    _load_local_dotenv()
    root_dir = Path(__file__).resolve().parents[1]
    return Config(
        reconstructor_api_url=os.getenv("RECONSTRUCTOR_API_URL", "http://localhost:8000").rstrip("/"),
        reconstructor_poll_interval=float(os.getenv("RECONSTRUCTOR_POLL_INTERVAL", "3")),
        reconstructor_job_timeout=float(os.getenv("RECONSTRUCTOR_JOB_TIMEOUT", "1800")),
        default_image_size=int(os.getenv("MAST3R_IMAGE_SIZE", "512")),
        default_min_conf_thr=float(os.getenv("MAST3R_MIN_CONF_THR", "1.5")),
        default_optim_level=os.getenv("MAST3R_OPTIM_LEVEL", "refine+depth"),
        roboflow_api_url=os.getenv("ROBOFLOW_API_URL", "https://serverless.roboflow.com"),
        roboflow_api_key=os.getenv("ROBOFLOW_API_KEY") or os.getenv("ROBOFLOW__API_KEY", ""),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        workspace_root=_path_from_env("GRADIO_WORKSPACE_ROOT", root_dir / "workspace"),
        defect_color=(220, 30, 30),
    )
