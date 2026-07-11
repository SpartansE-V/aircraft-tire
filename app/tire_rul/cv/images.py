"""Synthetic tire image generator.

Renders a tire tread patch where the visible groove width encodes the true tread depth
(deeper tread -> wider, darker grooves), plus optional damage markers (cut / bulge / FOD) in
signature colors and a serial label. Because the depth is *encoded in pixels*, the Depth model
in `assess.py` can genuinely recover it — giving the CV layer the same ground-truth validation
discipline as the RUL side. On real hardware these are laser/camera images instead.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

# Geometry shared with the estimator (assess.py imports these).
IMG_W, IMG_H = 360, 240
BOX = (30, 60, 330, 210)  # tread region: left, top, right, bottom (300 x 150)
GROOVE_COUNT = 8
GROOVE_MIN_W = 3.0  # groove width at the wear limit (mm-to-px calibration)
GROOVE_MAX_EXTRA = 9.0  # additional width at full new tread
TREAD_GRAY = 118
GROOVE_GRAY = 28
RUBBER = (52, 52, 55)
DARK_THRESHOLD = 60  # a groove pixel is "dark"
SAT_THRESHOLD = 28  # ...and low-saturation (so colored damage is excluded from depth)

DAMAGE_COLORS = {
    "cut": (205, 40, 40),  # red
    "bulge": (235, 140, 30),  # orange
    "fod": (40, 95, 205),  # blue
}
DAMAGE_TYPES = tuple(DAMAGE_COLORS)


def remaining_ratio(depth_mm: float, new_tread_mm: float, wear_limit_mm: float) -> float:
    return float(np.clip((depth_mm - wear_limit_mm) / max(new_tread_mm - wear_limit_mm, 1e-6), 0.0, 1.0))


def render_tire_image(
    depth_mm: float,
    new_tread_mm: float = 13.0,
    wear_limit_mm: float = 2.0,
    damage: list[str] | None = None,
    serial: str = "",
    seed: int = 0,
) -> Image.Image:
    """Render a tire scan. Groove width ∝ remaining tread; damage drawn in signature colors."""
    rng = np.random.default_rng(seed)
    r = remaining_ratio(depth_mm, new_tread_mm, wear_limit_mm)
    arr = np.empty((IMG_H, IMG_W, 3), dtype=np.float32)
    arr[:, :] = RUBBER
    left, top, right, bottom = BOX
    arr[top:bottom, left:right] = TREAD_GRAY

    pitch = (right - left) / GROOVE_COUNT
    width = GROOVE_MIN_W + GROOVE_MAX_EXTRA * r
    for i in range(GROOVE_COUNT):
        cx = left + pitch * (i + 0.5) + rng.normal(0, 0.6)
        half = (width + rng.normal(0, 0.6)) / 2.0
        x0 = max(int(round(cx - half)), left)
        x1 = min(int(round(cx + half)), right)
        if x1 > x0:
            arr[top:bottom, x0:x1] = GROOVE_GRAY

    arr += rng.normal(0, 4.0, arr.shape)  # sensor noise
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

    draw = ImageDraw.Draw(img)
    for d in damage or []:
        color = DAMAGE_COLORS.get(d)
        if color is None:
            continue
        if d == "cut":
            y = int(rng.uniform(top + 20, bottom - 20))
            draw.line([(left + 20, y), (right - 25, y + int(rng.integers(-12, 12)))], fill=color, width=5)
        elif d == "bulge":
            cx = int(rng.uniform(left + 45, right - 45))
            cy = int(rng.uniform(top + 32, bottom - 32))
            draw.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], outline=color, width=5)
        elif d == "fod":
            cx = int(rng.uniform(left + 45, right - 45))
            cy = int(rng.uniform(top + 32, bottom - 32))
            draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=color)

    if serial:
        draw.text((left, 32), f"S/N {serial}", fill=(225, 225, 225))
    img.info["serial"] = serial  # OCR stand-in (persisted via PngInfo when saved)
    return img
