"""Verify dense 2D->3D projection against a synthetic MASt3R pointmaps.npz.

No torch/MASt3R needed: we fabricate a point map with a known layout, run the
projector with a known detection box, and assert the right 3D points are
recolored in the exported GLB.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from pipeline.detector import Detection
from pipeline.projector import project_detections_to_glb

trimesh = pytest.importorskip("trimesh")

DEFECT = (220, 30, 30)


def _write_pointmaps(path: Path, *, size: int = 100, conf: float = 5.0) -> None:
    """One 100x100 image with an identity original->pointmap transform.

    pts[r, c] = (c, r, 0); every pixel confident; uniform grey color.
    """
    cols, rows = np.meshgrid(np.arange(size), np.arange(size))
    pts = np.stack([cols, rows, np.zeros_like(cols)], axis=-1).astype(np.float32)
    col = np.full((size, size, 3), 50, dtype=np.uint8)
    conf_arr = np.full((size, size), conf, dtype=np.float32)
    meta = [{
        "name": "img1.png", "orig_w": size, "orig_h": size, "res_w": size, "res_h": size,
        "crop_left": 0.0, "crop_top": 0.0, "pm_w": size, "pm_h": size,
    }]
    np.savez_compressed(
        path,
        names=np.asarray(["img1.png"]),
        world_transform=np.eye(4, dtype=np.float32),
        min_conf_thr=np.asarray(1.5, dtype=np.float32),
        meta=np.asarray(json.dumps(meta)),
        pts_0=pts, col_0=col, conf_0=conf_arr,
        pose_0=np.eye(4, dtype=np.float32), K_0=np.eye(3, dtype=np.float32),
    )


def _glb_colors(glb_path: Path) -> np.ndarray:
    scene = trimesh.load(str(glb_path))
    geoms = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
    return np.concatenate([np.asarray(g.colors)[:, :3] for g in geoms], axis=0)


def test_projection_flags_box_region(tmp_path: Path) -> None:
    npz = tmp_path / "pointmaps.npz"
    _write_pointmaps(npz)
    # Box covering cols[10,20), rows[30,40) under the identity transform -> 100 pixels.
    dets = {"img1.png": [Detection(x=15, y=35, width=10, height=10, confidence=0.9, class_name="crack")]}
    out = tmp_path / "defects.glb"

    result = project_detections_to_glb(
        pointmaps_path=npz, detections_by_image=dets, output_glb=out, defect_color=DEFECT
    )

    assert result.total_points == 100 * 100
    assert result.defect_points == 100
    assert result.per_class == {"crack": 100}
    assert result.per_image == {"img1.png": 100}
    assert result.matched_images == 1

    colors = _glb_colors(out)
    red = np.all(colors == np.array(DEFECT), axis=1).sum()
    assert red == 100, red


def test_projection_matches_on_basename(tmp_path: Path) -> None:
    npz = tmp_path / "pointmaps.npz"
    _write_pointmaps(npz)
    dets = {"uploads/img1.png": [Detection(x=15, y=35, width=10, height=10, confidence=0.5, class_name="crack")]}
    result = project_detections_to_glb(
        pointmaps_path=npz, detections_by_image=dets, output_glb=tmp_path / "o.glb"
    )
    assert result.defect_points == 100
    assert result.matched_images == 1


def test_projection_without_detections(tmp_path: Path) -> None:
    npz = tmp_path / "pointmaps.npz"
    _write_pointmaps(npz)
    result = project_detections_to_glb(
        pointmaps_path=npz, detections_by_image={}, output_glb=tmp_path / "o.glb"
    )
    assert result.total_points == 10_000
    assert result.defect_points == 0
    assert result.per_class == {}


def test_confidence_mask_drops_points(tmp_path: Path) -> None:
    npz = tmp_path / "pointmaps.npz"
    _write_pointmaps(npz, conf=0.5)  # below default thr 1.5 -> all points dropped
    result = project_detections_to_glb(
        pointmaps_path=npz, detections_by_image={}, output_glb=tmp_path / "o.glb"
    )
    assert result.total_points == 0


def test_box_clamped_to_pointmap(tmp_path: Path) -> None:
    npz = tmp_path / "pointmaps.npz"
    _write_pointmaps(npz)
    # Box partly outside the image -> clamped, no crash.
    dets = {"img1.png": [Detection(x=98, y=98, width=20, height=20, confidence=0.9, class_name="crack")]}
    result = project_detections_to_glb(
        pointmaps_path=npz, detections_by_image=dets, output_glb=tmp_path / "o.glb"
    )
    # cols [88,100) x rows [88,100) = 12*12
    assert result.defect_points == 144
