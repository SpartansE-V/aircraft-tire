"""Convert mock-tyre COCO metadata into 3D crack overlays for the /tyres viewer.

Circle cracks
  - Wheel bbox → centre + radius (edge/2).
  - Crack ``center`` → angle (radian) around the hub; lateral % from the vertical
    centre-line (−100% left … 0 … +100% right).

Flatten cracks
  - Image width = tire perimeter → θ = 2π · (cx / width).
  - Image height = tread span → axial Y from cy.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

ScanStatus = Literal["healthy", "warning", "error"]
ScanSide = Literal["left", "right"]
TreadDepthBand = Literal["1-2mm", "2-3mm", "3-4mm", "4-5mm", "5-6mm"]
TireModelType = Literal["radial", "type_vii", "type_iii"]

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_TYRES_DIR = REPO_ROOT / "assets" / "mock-tyres" / "release"
SCAN_GROUPS = ("1h233b", "8fh20v", "av01hv", "y929rh")

TREAD_COUNT: dict[TireModelType, int] = {
    "radial": 6,
    "type_vii": 4,
    "type_iii": 4,
}

TREAD_BANDS: tuple[TreadDepthBand, ...] = ("1-2mm", "2-3mm", "3-4mm", "4-5mm", "5-6mm")
HEALTHY_BANDS = frozenset({"4-5mm", "5-6mm"})
WARNING_BAND = "3-4mm"
ERROR_BANDS = frozenset({"1-2mm", "2-3mm"})

# GLB tire approximate proportions (unit OD ≈ 1).
_OD = 0.85
_BEAD = 0.55
_HALF_W = 0.38


def status_from_treads_and_cracks(
    tread_depths: list[str],
    *,
    has_cracks: bool,
) -> ScanStatus:
    """Status equation:

    - error   — any tread in {1-2mm, 2-3mm} OR any crack
    - warning — at least one tread is 3-4mm (and not error)
    - healthy — every tread is 4-5mm or 5-6mm (and no cracks)
    """
    if has_cracks or any(t in ERROR_BANDS for t in tread_depths):
        return "error"
    if any(t == WARNING_BAND for t in tread_depths):
        return "warning"
    if tread_depths and all(t in HEALTHY_BANDS for t in tread_depths):
        return "healthy"
    # Incomplete / unexpected bands — treat as warning rather than silent healthy.
    return "warning"


def _ann_center(ann: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return (cx, cy, bw, bh) preferring the ``center`` block when present."""
    center = ann.get("center") or {}
    if "x" in center and "y" in center:
        return (
            float(center["x"]),
            float(center["y"]),
            float(center.get("width", ann.get("bbox", [0, 0, 0, 0])[2] or 1)),
            float(center.get("height", ann.get("bbox", [0, 0, 0, 0])[3] or 1)),
        )
    x, y, w, h = ann["bbox"]
    return float(x + w / 2), float(y + h / 2), float(w), float(h)


def _largest_wheel(circle: dict[str, Any]) -> dict[str, Any] | None:
    wheels = [a for a in circle.get("annotations", []) if a.get("category") == "wheel"]
    if not wheels:
        return None
    return max(wheels, key=lambda a: float(a["bbox"][2]) * float(a["bbox"][3]))


def crack_from_circle(
    ann: dict[str, Any],
    *,
    wheel_cx: float,
    wheel_cy: float,
    radius: float,
) -> dict[str, Any]:
    """Map a circle.png crack centre onto the 3D tire sidewall.

    Centre-line (vertical through hub) is index 0. Lateral percent:
    right of centre-line → +100% at the rim, left → −100%.
    Angle is the radian of the crack around the hub (0 at top, + to the right).
    """
    cx, cy, bw, bh = _ann_center(ann)
    dx = cx - wheel_cx
    dy = cy - wheel_cy
    r = max(radius, 1e-6)
    lateral_pct = max(-100.0, min(100.0, (dx / r) * 100.0))
    # 0 rad at top of wheel; positive toward the right (screen +x).
    angle_rad = math.atan2(dx, -(dy))
    norm_r = min(1.15, math.hypot(dx, dy) / r)
    radial = _BEAD + (_OD - _BEAD) * max(0.35, min(1.0, norm_r))

    at = [
        round(math.sin(angle_rad) * radial, 4),
        round((lateral_pct / 100.0) * _HALF_W * 0.35, 4),
        round(math.cos(angle_rad) * radial, 4),
    ]
    highlight_r = max(0.08, min(0.28, (max(bw, bh) / (2 * r)) * 0.35))
    return {
        "kind": "damage",
        "label": f"crack-circle-{ann.get('id', 0)}",
        "severity": "high",
        "zone": "Sidewall · crack",
        "category": "crack",
        "source": "circle",
        "angle_rad": round(angle_rad, 6),
        "lateral_pct": round(lateral_pct, 2),
        "at": at,
        "r": round(highlight_r, 4),
        "wave": True,
    }


def crack_from_flatten(
    ann: dict[str, Any],
    *,
    width: float,
    height: float,
    side: ScanSide,
) -> dict[str, Any]:
    """Map a flatten crack centre onto the outer tread. Width = full perimeter."""
    cx, cy, bw, bh = _ann_center(ann)
    u = cx / max(width, 1.0)  # 0..1 around circumference
    v = cy / max(height, 1.0)  # 0..1 across tread span
    theta = u * 2 * math.pi
    axial = (v - 0.5) * 2 * _HALF_W * 0.55
    # Left/right flatten views sit on opposite halves of the axle.
    axial_sign = -1.0 if side == "left" else 1.0
    at = [
        round(math.sin(theta) * _OD, 4),
        round(axial * axial_sign, 4),
        round(math.cos(theta) * _OD, 4),
    ]
    highlight_r = max(0.08, min(0.32, (bw / width) * math.pi * 0.4 + (bh / height) * 0.15))
    return {
        "kind": "damage",
        "label": f"crack-flatten-{side}-{ann.get('id', 0)}",
        "severity": "high",
        "zone": f"Tread · {side} · crack",
        "category": "crack",
        "source": f"flatten-{side}",
        "angle_rad": round(theta, 6),
        "lateral_pct": round((v - 0.5) * 200.0, 2),
        "at": at,
        "r": round(highlight_r, 4),
        "wave": True,
    }


def extract_cracks(group_id: str, side: ScanSide) -> list[dict[str, Any]]:
    """All crack 3D overlays for one scan group + flatten side (circle + flatten)."""
    folder = MOCK_TYRES_DIR / group_id
    payload = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    images = payload["images"]
    defects: list[dict[str, Any]] = []

    circle = images.get("circle.png")
    if circle:
        wheel = _largest_wheel(circle)
        if wheel:
            wcx, wcy, ww, wh = _ann_center(wheel)
            radius = max(ww, wh) / 2.0
            for ann in circle.get("annotations", []):
                if ann.get("category") != "crack":
                    continue
                defects.append(
                    crack_from_circle(ann, wheel_cx=wcx, wheel_cy=wcy, radius=radius)
                )

    flatten_key = f"flatten-{side}.png"
    flatten = images.get(flatten_key)
    if flatten:
        for ann in flatten.get("annotations", []):
            if ann.get("category") != "crack":
                continue
            defects.append(
                crack_from_flatten(
                    ann,
                    width=float(flatten["width"]),
                    height=float(flatten["height"]),
                    side=side,
                )
            )

    return defects


def write_group_annotations(group_id: str) -> dict[str, Any]:
    """Persist left/right crack packs (for inspection / debugging)."""
    packs = {
        "left": {"side": "left", "defects": extract_cracks(group_id, "left")},
        "right": {"side": "right", "defects": extract_cracks(group_id, "right")},
    }
    out = MOCK_TYRES_DIR / group_id / "annotations_3d.json"
    out.write_text(json.dumps(packs, indent=2), encoding="utf-8")
    return packs


def asset_url(group_id: str, filename: str) -> str:
    return f"/assets/mock-tyres/release/{group_id}/{filename}"


# Shared healthy sidewall photo (no cracks) — used for every good tire.
HEALTHY_CIRCLE_URL = "/assets/mock-tyres/release/circle.png"

# 2D overlay rules for the UI:
#   crack         → draw geometry, no text label
#   tread-shallow → draw geometry + "shallow" label
#   tread / wheel → omitted
_DISPLAY_2D = {
    "crack": None,  # no label
    "tread-shallow": "shallow",
}


def _ann_2d(ann: dict[str, Any], *, source: str | None = None) -> dict[str, Any] | None:
    cat = ann.get("category", "")
    if cat not in _DISPLAY_2D:
        return None
    cx, cy, bw, bh = _ann_center(ann)
    bbox = ann.get("bbox") or [cx - bw / 2, cy - bh / 2, bw, bh]
    seg = ann.get("segmentation") or []
    # Keep only polygon rings (list of flat [x,y,...] coords).
    polygons = [ring for ring in seg if isinstance(ring, list) and len(ring) >= 6]
    # Same key as extract_cracks() labels so 2D ↔ 3D selection can sync.
    defect_label = (
        f"crack-{source}-{ann.get('id', 0)}" if cat == "crack" and source else None
    )
    return {
        "category": cat,
        "label": _DISPLAY_2D[cat],
        "defect_label": defect_label,
        "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
        "center": {"x": cx, "y": cy},
        "segmentation": polygons,
    }


def annotations_2d_for_image(
    image_meta: dict[str, Any] | None,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Filter metadata annotations for UI overlay (crack / shallow only).

    ``source`` is the scan image stem (``circle``, ``flatten-left``, …) used to
    build ``defect_label`` matching the 3D crack overlay labels.
    """
    if not image_meta:
        return {"width": 0, "height": 0, "annotations": []}
    anns = []
    for ann in image_meta.get("annotations", []):
        item = _ann_2d(ann, source=source)
        if item:
            anns.append(item)
    return {
        "width": int(image_meta.get("width") or 0),
        "height": int(image_meta.get("height") or 0),
        "annotations": anns,
    }


def load_group_metadata(group_id: str) -> dict[str, Any]:
    path = MOCK_TYRES_DIR / group_id / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


def images_for(
    group_id: str,
    side: ScanSide | None = None,
    *,
    scan_status: ScanStatus | None = None,
) -> dict[str, Any]:
    """Expose circle + flatten + frames, with 2D overlay payloads.

    Flatten selection:
      healthy / warning → flatten-right from the assigned group (no overlays)
      error             → flatten-left from the assigned group + crack/shallow overlays

    Circle:
      healthy / warning → shared good ``release/circle.png`` (no overlays)
      error             → group circle.png + crack overlays
    """
    # Side is determined by status (caller side is ignored when status is set).
    if scan_status in ("healthy", "warning"):
        flatten_side: ScanSide = "right"
        use_healthy_circle = True
    elif scan_status == "error":
        flatten_side = "left"
        use_healthy_circle = False
    else:
        flatten_side = side or "right"
        use_healthy_circle = False

    meta = load_group_metadata(group_id)
    images_meta = meta.get("images", {})
    circle_url = HEALTHY_CIRCLE_URL if use_healthy_circle else asset_url(group_id, "circle.png")
    flatten_key = f"flatten-{flatten_side}.png"

    circle_raw = (
        {"width": 0, "height": 0, "annotations": []}
        if use_healthy_circle
        else annotations_2d_for_image(images_meta.get("circle.png"), source="circle")
    )
    flatten_raw = annotations_2d_for_image(
        images_meta.get(flatten_key), source=f"flatten-{flatten_side}"
    )

    # Only error tires get 2D overlays; healthy/warning stay clean.
    if scan_status == "error":
        circle_anns = circle_raw["annotations"]
        flatten_anns = flatten_raw["annotations"]
    else:
        circle_anns = []
        flatten_anns = []

    return {
        "circle": {
            "url": circle_url,
            "width": circle_raw["width"],
            "height": circle_raw["height"],
            "annotations": circle_anns,
        },
        "flatten": {
            "url": asset_url(group_id, flatten_key),
            "width": flatten_raw["width"],
            "height": flatten_raw["height"],
            "annotations": flatten_anns,
        },
        "frames": [
            {
                "url": asset_url(group_id, name),
                "width": 0,
                "height": 0,
                "annotations": [],
            }
            for name in ("frame-0.png", "frame-120.png", "frame-240.png")
        ],
    }
