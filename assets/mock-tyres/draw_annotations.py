#!/usr/bin/env python3
"""Draw tyre-quality annotations onto cut images and save visualizations."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CUT_DIR = Path(__file__).parent / "cut"
ANNOTATIONS_DIR = Path(__file__).parent / "annotations"

CLASS_COLORS = {
    "bad_tyre": (220, 38, 38),
    "good_tyre": (22, 163, 74),
    "tyre_unclear_tread": (234, 179, 8),
}
DEFAULT_COLOR = (59, 130, 246)


def load_font(size: int) -> ImageFont.ImageFont:
    for font_path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(font_path).exists():
            return ImageFont.truetype(font_path, size=size)
    return ImageFont.load_default()


def prediction_box(prediction: dict) -> tuple[float, float, float, float]:
    center_x = float(prediction["x"])
    center_y = float(prediction["y"])
    width = float(prediction["width"])
    height = float(prediction["height"])
    left = center_x - width / 2
    top = center_y - height / 2
    right = center_x + width / 2
    bottom = center_y + height / 2
    return left, top, right, bottom


def draw_predictions(image_path: Path, annotation_path: Path, output_path: Path) -> int:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = load_font(max(12, min(image.size) // 28))

    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    predictions = payload.get("predictions", [])

    for prediction in predictions:
        left, top, right, bottom = prediction_box(prediction)
        class_name = str(prediction.get("class", "unknown"))
        confidence = float(prediction.get("confidence", 0))
        color = CLASS_COLORS.get(class_name, DEFAULT_COLOR)
        label = f"{class_name} {confidence:.2f}"

        draw.rectangle((left, top, right, bottom), outline=color, width=3)

        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        label_top = max(0, top - text_height - 4)
        draw.rectangle(
            (left, label_top, left + text_width + 8, label_top + text_height + 4),
            fill=color,
        )
        draw.text((left + 4, label_top + 2), label, fill=(255, 255, 255), font=font)

    image.save(output_path)
    return len(predictions)


def main() -> None:
    annotation_files = sorted(ANNOTATIONS_DIR.glob("*.json"))
    if not annotation_files:
        print(f"No JSON annotations found in {ANNOTATIONS_DIR}")
        return

    print(f"Drawing annotations for {len(annotation_files)} images...")

    for index, annotation_path in enumerate(annotation_files, start=1):
        image_path = CUT_DIR / f"{annotation_path.stem}.png"
        output_path = ANNOTATIONS_DIR / f"{annotation_path.stem}.png"

        if not image_path.exists():
            print(f"[{index}/{len(annotation_files)}] Missing image for {annotation_path.name}")
            continue

        prediction_count = draw_predictions(image_path, annotation_path, output_path)
        print(
            f"[{index}/{len(annotation_files)}] {annotation_path.stem}.png "
            f"-> {prediction_count} boxes"
        )

    print(f"Done. Saved annotated images to {ANNOTATIONS_DIR}")


if __name__ == "__main__":
    main()
