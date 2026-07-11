"""Computer-vision layer: automated tire diagnostics from images.

Three capabilities (as specified): a Depth model (tread depth), a VLM (damage detection +
condition report), and OCR (tire serial). For the POC these run on synthetic tire images with
a deterministic, offline backend — so the pipeline runs with no external API and can be validated
against known ground truth. A Claude-vision backend is pluggable as the production VLM.
"""

from app.tire_rul.cv.assess import (
    BedrockVlm,
    ClaudeVlm,
    MockVlm,
    OpenAiVlm,
    TireScan,
    assess_tire,
    detect_damage,
    estimate_tread_depth,
    get_vlm,
    locate_damage,
    read_serial,
    vlm_available,
)
from app.tire_rul.cv.images import render_tire_image

__all__ = [
    "BedrockVlm",
    "ClaudeVlm",
    "MockVlm",
    "OpenAiVlm",
    "TireScan",
    "assess_tire",
    "detect_damage",
    "estimate_tread_depth",
    "get_vlm",
    "locate_damage",
    "read_serial",
    "render_tire_image",
    "vlm_available",
]
