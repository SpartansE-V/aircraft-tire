"""Tire image assessment: Depth model + VLM (damage + report) + OCR (serial).

The offline backend is deterministic and runs with no external API — it analyzes the pixels of
the synthetic images so its outputs can be validated against known ground truth. `get_vlm("claude")`
swaps in a Claude-vision backend as the production VLM (lazy-imported; falls back with a clear
error if the `anthropic` SDK or an API key is unavailable).
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

from app.rul.cv.images import (
    BOX,
    DARK_THRESHOLD,
    GROOVE_COUNT,
    GROOVE_MAX_EXTRA,
    GROOVE_MIN_W,
    SAT_THRESHOLD,
)


@dataclass
class TireScan:
    serial: str
    serial_confidence: float
    tread_depth_mm: float
    depth_confidence: float
    damage_findings: list[str]
    condition_report: str
    scan_confidence: float
    scan_date: str | None = None


# ---------------------------------------------------------------------------
# Depth model — recover tread depth from groove geometry
# ---------------------------------------------------------------------------
def estimate_tread_depth(
    image: Image.Image, new_tread_mm: float = 13.0, wear_limit_mm: float = 2.0
) -> tuple[float, float]:
    """Estimate tread depth (mm) from the tread region's groove coverage. Returns (depth, confidence)."""
    arr = np.asarray(image.convert("RGB")).astype(np.float32)
    left, top, right, bottom = BOX
    region = arr[top:bottom, left:right]
    gray = region.mean(axis=2)
    sat = region.max(axis=2) - region.min(axis=2)
    dark_gray = (gray < DARK_THRESHOLD) & (sat < SAT_THRESHOLD)  # grooves, not colored damage
    dark_frac = float(dark_gray.mean())

    pitch = (right - left) / GROOVE_COUNT
    width_est = dark_frac * pitch  # dark fraction ≈ groove_width / pitch
    r_est = float(np.clip((width_est - GROOVE_MIN_W) / GROOVE_MAX_EXTRA, 0.0, 1.0))
    depth = wear_limit_mm + r_est * (new_tread_mm - wear_limit_mm)
    # confidence: high when groove coverage is well inside the calibrated band, lower at the rails
    confidence = round(float(0.97 - 0.12 * abs(r_est - 0.5) * 2), 2)
    return round(depth, 2), confidence


# ---------------------------------------------------------------------------
# Damage detection (pixel signature of the synthetic markers)
# ---------------------------------------------------------------------------
def _damage_masks(image: Image.Image) -> dict[str, np.ndarray]:
    arr = np.asarray(image.convert("RGB")).astype(int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    return {
        "cut": (r > 150) & (g < 95) & (b < 95),
        "bulge": (r > 185) & (g > 95) & (g < 185) & (b < 95),
        "fod": (b > 150) & (r < 115) & (g < 150),
    }


_DAMAGE_MIN_PX = {"cut": 40, "bulge": 40, "fod": 25}


def detect_damage(image: Image.Image) -> list[str]:
    masks = _damage_masks(image)
    return [name for name, mask in masks.items() if int(mask.sum()) > _DAMAGE_MIN_PX[name]]


def _region_label(bbox: list[int]) -> str:
    """Human-readable tread location for a damage bbox (e.g. 'upper center tread')."""
    left, top, right, bottom = BOX
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    third = (right - left) / 3
    h = "left" if cx < left + third else ("right" if cx > right - third else "center")
    v = "upper" if cy < (top + bottom) / 2 else "lower"
    return f"{v} {h} tread"


def locate_damage(image: Image.Image) -> list[dict]:
    """Damage regions with pixel bounding boxes + a plain-language location.

    Returns [{type, bbox [x0,y0,x1,y1], area_px, location}] — what an engineer needs to find the
    spot on the actual tire without opening the scan viewer.
    """
    regions: list[dict] = []
    for name, mask in _damage_masks(image).items():
        if int(mask.sum()) <= _DAMAGE_MIN_PX[name]:
            continue
        ys, xs = np.nonzero(mask)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        regions.append(
            {"type": name, "bbox": bbox, "area_px": int(mask.sum()), "location": _region_label(bbox)}
        )
    return regions


# ---------------------------------------------------------------------------
# OCR (serial) — mock reads the embedded label; production OCR reads pixels
# ---------------------------------------------------------------------------
def read_serial(image: Image.Image) -> tuple[str, float]:
    serial = str(image.info.get("serial", "") or "")
    return (serial, 0.95 if serial else 0.0)


# ---------------------------------------------------------------------------
# VLM backends
# ---------------------------------------------------------------------------
class VlmBackend(Protocol):
    def analyze(self, image: Image.Image) -> dict: ...


# Shared inspection prompt (mentions JSON so OpenAI's json_object mode is satisfied).
VLM_PROMPT = (
    "You are an aircraft-tire inspection VLM. Examine this tire image and respond with ONLY a "
    'JSON object: {"damage": [any of "cut","bulge","fod" that are visible], "report": '
    '"<one-sentence condition summary; distinguish acute damage (immediate removal) from normal '
    'wear>"}. Return an empty damage list if the tire looks serviceable.'
)


def _image_b64_png(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode()


def _parse_vlm_json(text: str) -> dict:
    """Parse a VLM JSON reply into {damage, report}; robust to stray text around the JSON."""
    snippet = text[text.find("{") : text.rfind("}") + 1] if "{" in text else text
    data = json.loads(snippet)
    damage = [d for d in data.get("damage", []) if d in ("cut", "bulge", "fod")]
    return {"damage": damage, "report": str(data.get("report", ""))}


class MockVlm:
    """Deterministic offline VLM: damage from pixel signatures + a templated condition report."""

    def analyze(self, image: Image.Image) -> dict:
        damage = detect_damage(image)
        if damage:
            report = (
                "Detected structural damage: "
                + ", ".join(damage)
                + ". This is ACUTE damage — requires immediate removal per AMM criteria, "
                "not a scheduled wear replacement."
            )
        else:
            report = (
                "Tread grooves clearly defined; no cuts, bulges, or FOD detected. "
                "Wear appears within normal limits — a scheduled (not urgent) item."
            )
        return {"damage": damage, "report": report}


class OpenAiVlm:
    """Production VLM backend — OpenAI vision. Lazy-imports the SDK; needs OPENAI_API_KEY.

    Model via constructor or the ``OPENAI_VLM_MODEL`` env var (default ``gpt-4o-mini``). The SDK
    honors ``OPENAI_BASE_URL`` for OpenAI-compatible / Azure endpoints.
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("OPENAI_VLM_MODEL", "gpt-4o-mini")

    def analyze(self, image: Image.Image) -> dict:
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError("OpenAiVlm needs the 'openai' SDK (pip install openai).") from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OpenAiVlm needs OPENAI_API_KEY in the environment.")

        b64 = _image_b64_png(image)
        client = openai.OpenAI()  # reads OPENAI_API_KEY (+ OPENAI_BASE_URL) from the environment
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VLM_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
        )
        return _parse_vlm_json(resp.choices[0].message.content or "")


def _aws_credentials_present() -> bool:
    """Best-effort check for AWS credentials (env keys, profile, Bedrock token, or ~/.aws)."""
    import pathlib

    if any(
        os.environ.get(k)
        for k in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_BEARER_TOKEN_BEDROCK", "AWS_ROLE_ARN")
    ):
        return True
    return (pathlib.Path.home() / ".aws" / "credentials").exists()


class BedrockVlm:
    """Production VLM backend — Claude on Amazon Bedrock via the Mantle client (Messages API).

    Model IDs on Bedrock take an ``anthropic.`` prefix (default ``anthropic.claude-opus-4-8``;
    override via ``BEDROCK_VLM_MODEL``). Region from ``AWS_REGION``/``AWS_DEFAULT_REGION``
    (default ``us-east-1``); credentials from the standard AWS chain (env keys, profile, SSO).
    """

    def __init__(self, model: str | None = None, region: str | None = None):
        self.model = model or os.environ.get("BEDROCK_VLM_MODEL", "anthropic.claude-opus-4-8")
        self.region = (
            region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        )

    def analyze(self, image: Image.Image) -> dict:
        try:
            from anthropic import AnthropicBedrockMantle
        except ImportError as exc:
            raise RuntimeError(
                "BedrockVlm needs the Anthropic SDK with Bedrock support (pip install 'anthropic[bedrock]')."
            ) from exc
        if not _aws_credentials_present():
            raise RuntimeError(
                "BedrockVlm needs AWS credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, "
                "AWS_PROFILE, or a configured ~/.aws)."
            )
        client = AnthropicBedrockMantle(aws_region=self.region)
        msg = client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": _image_b64_png(image)},
                        },
                        {"type": "text", "text": VLM_PROMPT},
                    ],
                }
            ],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        return _parse_vlm_json(text)


class ClaudeVlm:
    """Production VLM backend — Claude vision. Lazy-imports the SDK; needs ANTHROPIC_API_KEY."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("ANTHROPIC_VLM_MODEL", "claude-opus-4-8")

    def analyze(self, image: Image.Image) -> dict:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("ClaudeVlm needs the 'anthropic' SDK (pip install anthropic).") from exc
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ClaudeVlm needs ANTHROPIC_API_KEY in the environment.")

        b64 = _image_b64_png(image)
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                        {"type": "text", "text": VLM_PROMPT},
                    ],
                }
            ],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        return _parse_vlm_json(text)


_BACKENDS = {"mock": MockVlm, "openai": OpenAiVlm, "claude": ClaudeVlm, "bedrock": BedrockVlm}


def get_vlm(backend: str = "mock") -> VlmBackend:
    """Return a VLM backend. "auto" picks OpenAI, then Claude, then Bedrock, then the mock."""
    b = (backend or "mock").lower()
    if b == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAiVlm()
        if os.environ.get("ANTHROPIC_API_KEY"):
            return ClaudeVlm()
        if _sdk_ok("anthropic") and _aws_credentials_present():
            return BedrockVlm()
        return MockVlm()
    if b not in _BACKENDS:
        raise ValueError(f"unknown VLM backend '{backend}' (mock | openai | claude | bedrock | auto)")
    return _BACKENDS[b]()


def vlm_available(backend: str) -> bool:
    """Whether a real backend can run right now (SDK importable + credentials present)."""
    b = (backend or "").lower()
    if b == "openai":
        return _sdk_ok("openai") and bool(os.environ.get("OPENAI_API_KEY"))
    if b == "claude":
        return _sdk_ok("anthropic") and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if b == "bedrock":
        return _sdk_ok("anthropic") and _aws_credentials_present()
    return b == "mock"


def _sdk_ok(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def assess_tire(
    image: Image.Image,
    vlm: VlmBackend | None = None,
    new_tread_mm: float = 13.0,
    wear_limit_mm: float = 2.0,
    scan_date: str | None = None,
) -> TireScan:
    """Run the full CV assessment: serial (OCR) + tread depth (Depth) + damage/report (VLM)."""
    serial, serial_conf = read_serial(image)
    depth, depth_conf = estimate_tread_depth(image, new_tread_mm, wear_limit_mm)
    result = (vlm or MockVlm()).analyze(image)
    scan_conf = round(min(serial_conf if serial else 1.0, depth_conf), 2)
    return TireScan(
        serial=serial,
        serial_confidence=serial_conf,
        tread_depth_mm=depth,
        depth_confidence=depth_conf,
        damage_findings=list(result["damage"]),
        condition_report=str(result["report"]),
        scan_confidence=scan_conf,
        scan_date=scan_date,
    )
