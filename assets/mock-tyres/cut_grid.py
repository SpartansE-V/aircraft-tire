#!/usr/bin/env python3
"""Split grid mock tyre images into individual pieces.

Filenames follow the pattern: {rows}x{cols}-{index}.png
e.g. 4x4-1.png is a 4-row by 4-column grid image.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

RAW_DIR = Path(__file__).parent / "raw"
CUT_DIR = Path(__file__).parent / "cut"
FILENAME_PATTERN = re.compile(r"^(\d+)x(\d+)-(\d+)\.png$", re.IGNORECASE)


def parse_filename(filename: str) -> tuple[int, int, int] | None:
    match = FILENAME_PATTERN.match(filename)
    if not match:
        return None
    rows, cols, index = (int(match.group(i)) for i in range(1, 4))
    return rows, cols, index


def cut_image(image_path: Path, rows: int, cols: int, source_index: int) -> list[Path]:
    image = Image.open(image_path)
    width, height = image.size
    piece_width = width // cols
    piece_height = height // rows

    saved_paths: list[Path] = []
    piece_index = 1

    for row in range(rows):
        for col in range(cols):
            left = col * piece_width
            top = row * piece_height
            right = left + piece_width if col < cols - 1 else width
            bottom = top + piece_height if row < rows - 1 else height

            piece = image.crop((left, top, right, bottom))
            output_name = f"{rows}x{cols}-{source_index}-{piece_index}.png"
            output_path = CUT_DIR / output_name
            piece.save(output_path)
            saved_paths.append(output_path)
            piece_index += 1

    return saved_paths


def main() -> None:
    CUT_DIR.mkdir(parents=True, exist_ok=True)

    image_files = sorted(RAW_DIR.glob("*.png"))
    if not image_files:
        print(f"No PNG files found in {RAW_DIR}")
        return

    total_pieces = 0
    for image_path in image_files:
        parsed = parse_filename(image_path.name)
        if parsed is None:
            print(f"Skipping unrecognized filename: {image_path.name}")
            continue

        rows, cols, source_index = parsed
        saved = cut_image(image_path, rows, cols, source_index)
        total_pieces += len(saved)
        print(f"{image_path.name} -> {len(saved)} pieces")

    print(f"Done. Saved {total_pieces} pieces to {CUT_DIR}")


if __name__ == "__main__":
    main()
