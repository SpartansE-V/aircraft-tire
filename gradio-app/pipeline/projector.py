"""Project 2D detections onto a MASt3R dense reconstruction.

MASt3R gives, for every input image, a dense per-pixel 3D point (a "point map")
aligned with the source image. So projecting a 2D detection box into 3D is a
direct lookup: map the box from original-image pixels into point-map indices,
then every confident 3D point under the box is flagged as a defect. Denser and
simpler than COLMAP sparse feature tracks.

Input is the reconstructor's ``pointmaps.npz`` (see the reconstructor's
mast3r_reconstructor.py for the exact contract). Output is a colored ``defects.glb``
where flagged points are recolored (default red) and every other point keeps its
reconstructed color — matching the orientation of the reconstructor's model.glb.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .detector import Detection
from .glb import write_pointcloud_glb


@dataclass(slots=True)
class ProjectionResult:
    model_path: Path
    total_points: int
    defect_points: int
    per_class: dict[str, int] = field(default_factory=dict)
    per_image: dict[str, int] = field(default_factory=dict)
    matched_images: int = 0


class ProjectionError(RuntimeError):
    """Raised when the point maps cannot be loaded/projected."""


def _basename(name: str) -> str:
    return Path(name).name


def project_detections_to_glb(
    *,
    pointmaps_path: Path,
    detections_by_image: Mapping[str, Sequence[Detection]],
    output_glb: Path,
    defect_color: tuple[int, int, int] = (220, 30, 30),
    min_conf_thr: float | None = None,
) -> ProjectionResult:
    try:
        data = np.load(pointmaps_path, allow_pickle=False)
    except Exception as exc:  # noqa: BLE001 - surface load failures uniformly
        raise ProjectionError(f"Failed to load point maps at {pointmaps_path}: {exc}") from exc

    meta = json.loads(str(data["meta"]))
    names = [str(n) for n in data["names"].tolist()]
    world_transform = np.asarray(data["world_transform"], dtype=np.float64)
    thr = float(min_conf_thr) if min_conf_thr is not None else float(data["min_conf_thr"])

    detections_by_basename: dict[str, Sequence[Detection]] = {
        _basename(name): dets for name, dets in detections_by_image.items()
    }

    cloud_pts: list[np.ndarray] = []
    cloud_col: list[np.ndarray] = []
    cloud_defect: list[np.ndarray] = []
    cloud_class: list[np.ndarray] = []
    class_labels: list[str] = []
    per_image: dict[str, int] = {}
    matched_images = 0

    for i, entry in enumerate(meta):
        name = str(entry["name"])
        pts = np.asarray(data[f"pts_{i}"], dtype=np.float32)  # (pm_h, pm_w, 3)
        col = np.asarray(data[f"col_{i}"], dtype=np.uint8)  # (pm_h, pm_w, 3)
        conf = np.asarray(data[f"conf_{i}"], dtype=np.float32)  # (pm_h, pm_w)
        pm_h, pm_w = conf.shape

        keep = (conf > thr) & np.isfinite(pts).all(axis=2)  # (pm_h, pm_w) bool

        defect_grid = np.zeros((pm_h, pm_w), dtype=bool)
        class_grid = np.full((pm_h, pm_w), -1, dtype=np.int32)

        detections = detections_by_basename.get(_basename(name)) or []
        if detections:
            matched_images += 1
        sx = entry["res_w"] / entry["orig_w"]
        sy = entry["res_h"] / entry["orig_h"]
        crop_left = float(entry["crop_left"])
        crop_top = float(entry["crop_top"])
        for det in detections:
            c0 = det.x_min * sx - crop_left
            c1 = det.x_max * sx - crop_left
            r0 = det.y_min * sy - crop_top
            r1 = det.y_max * sy - crop_top
            ci0, ci1 = max(0, int(np.floor(min(c0, c1)))), min(pm_w, int(np.ceil(max(c0, c1))))
            ri0, ri1 = max(0, int(np.floor(min(r0, r1)))), min(pm_h, int(np.ceil(max(r0, r1))))
            if ci1 <= ci0 or ri1 <= ri0:
                continue
            defect_grid[ri0:ri1, ci0:ci1] = True
            class_grid[ri0:ri1, ci0:ci1] = _class_index(class_labels, det.class_name)

        pts_k = pts[keep]
        col_k = col[keep]
        defect_k = defect_grid[keep]
        class_k = class_grid[keep]
        cloud_pts.append(pts_k)
        cloud_col.append(col_k)
        cloud_defect.append(defect_k)
        cloud_class.append(class_k)
        per_image[name] = int(defect_k.sum())

    if cloud_pts:
        points = np.concatenate(cloud_pts, axis=0)
        colors = np.concatenate(cloud_col, axis=0).astype(np.uint8)
        defect = np.concatenate(cloud_defect, axis=0)
        classes = np.concatenate(cloud_class, axis=0)
    else:
        points = np.zeros((0, 3), np.float32)
        colors = np.zeros((0, 3), np.uint8)
        defect = np.zeros((0,), bool)
        classes = np.zeros((0,), np.int32)

    colors = colors.copy()
    colors[defect] = np.asarray(defect_color, dtype=np.uint8)

    per_class: dict[str, int] = {}
    for idx, label in enumerate(class_labels):
        count = int(np.count_nonzero(defect & (classes == idx)))
        if count:
            per_class[label] = count

    write_pointcloud_glb(output_glb, points, colors, transform=world_transform)

    return ProjectionResult(
        model_path=Path(output_glb),
        total_points=int(points.shape[0]),
        defect_points=int(defect.sum()),
        per_class=per_class,
        per_image={k: v for k, v in per_image.items() if v},
        matched_images=matched_images,
    )


def _class_index(labels: list[str], name: str) -> int:
    if name not in labels:
        labels.append(name)
    return labels.index(name)
