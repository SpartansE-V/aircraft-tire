#!/usr/bin/env python3
"""Run tyre-quality inference on cut mock tyre images and save JSON annotations."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CRAFT_DETECTOR_ROOT = Path(__file__).resolve().parents[2] / "craft-detector-service"
REPO_ROOT = CRAFT_DETECTOR_ROOT.parent
if str(CRAFT_DETECTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(CRAFT_DETECTOR_ROOT))

CUT_DIR = Path(__file__).parent / "cut"
ANNOTATIONS_DIR = Path(__file__).parent / "annotations"


def load_env() -> None:
    for env_path in (CRAFT_DETECTOR_ROOT / ".env", REPO_ROOT / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

from app.config import get_settings  # noqa: E402
from app.integrations.roboflow.manager import RoboflowManager  # noqa: E402


def build_manager() -> RoboflowManager:
    settings = get_settings()
    if not settings.roboflow.api_key:
        raise RuntimeError(
            "Roboflow API key is not configured. "
            "Set ROBOFLOW__API_KEY in craft-detector-service/.env"
        )

    return RoboflowManager(
        api_url=settings.roboflow.api_url,
        api_key=settings.roboflow.api_key,
        model_settings=settings.roboflow.tyre_quality,
    )


def annotate_image(manager: RoboflowManager, image_path: Path) -> dict:
    predictions = manager.infer(str(image_path))
    return {"predictions": predictions}


def main() -> None:
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    image_files = sorted(CUT_DIR.glob("*.png"))
    if not image_files:
        print(f"No PNG files found in {CUT_DIR}")
        return

    manager = build_manager()
    model_id = get_settings().roboflow.tyre_quality.model_id
    print(f"Using model: {model_id}")
    print(f"Annotating {len(image_files)} images...")

    for index, image_path in enumerate(image_files, start=1):
        output_path = ANNOTATIONS_DIR / f"{image_path.stem}.json"
        result = annotate_image(manager, image_path)
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        prediction_count = len(result["predictions"])
        print(f"[{index}/{len(image_files)}] {image_path.name} -> {prediction_count} predictions")

    print(f"Done. Saved annotations to {ANNOTATIONS_DIR}")


if __name__ == "__main__":
    main()
