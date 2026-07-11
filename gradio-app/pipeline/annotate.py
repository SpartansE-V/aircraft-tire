"""Draw detection boxes onto source images for the 2D gallery preview."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .detector import Detection

BOX_COLOR = (220, 30, 30)
TEXT_COLOR = (255, 255, 255)


def annotate_image(image_path: Path, detections: Sequence[Detection], output_path: Path) -> Path:
    """Render an annotated copy of ``image_path`` with labelled detection boxes."""
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _load_font(max(12, image.width // 80))
    line_width = max(2, image.width // 400)

    for detection in detections:
        box = [detection.x_min, detection.y_min, detection.x_max, detection.y_max]
        draw.rectangle(box, outline=BOX_COLOR, width=line_width)
        label = f"{detection.class_name} {detection.confidence:.0%}"
        _draw_label(draw, detection.x_min, detection.y_min, label, font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def _draw_label(
    draw: ImageDraw.ImageDraw, x: float, y: float, text: str, font: ImageFont.ImageFont
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = right - left, bottom - top
    pad = 3
    background = [x, y - text_h - 2 * pad, x + text_w + 2 * pad, y]
    if background[1] < 0:  # keep the label on-canvas near the top edge
        background = [x, y, x + text_w + 2 * pad, y + text_h + 2 * pad]
    draw.rectangle(background, fill=BOX_COLOR)
    draw.text((background[0] + pad, background[1] + pad), text, fill=TEXT_COLOR, font=font)


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()
