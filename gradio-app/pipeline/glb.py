"""Write colored point clouds to GLB with trimesh (self-contained)."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_pointcloud_glb(
    output_path: Path,
    points: np.ndarray,
    colors: np.ndarray,
    transform: np.ndarray | None = None,
) -> Path:
    """Write an (N,3) point cloud with (N,3) uint8 colors to a .glb file.

    ``transform`` is an optional 4x4 applied to the scene before export (use the
    reconstructor's stored ``world_transform`` so the highlighted cloud matches
    ``model.glb``'s orientation).
    """
    import trimesh

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    colors = np.asarray(colors).reshape(-1, 3)
    if colors.dtype != np.uint8:
        colors = (
            np.clip(colors * 255.0, 0, 255).astype(np.uint8)
            if colors.size and colors.max() <= 1.0
            else colors.astype(np.uint8)
        )

    finite = np.isfinite(points).all(axis=1)
    points, colors = points[finite], colors[finite]

    if points.shape[0] == 0:
        # trimesh can't export an empty scene; emit a single degenerate point so
        # downstream (viewer / download) still gets a valid GLB.
        points = np.zeros((1, 3), dtype=np.float64)
        colors = np.zeros((1, 3), dtype=np.uint8)

    cloud = trimesh.PointCloud(points, colors=colors)
    if transform is not None:
        cloud.apply_transform(np.asarray(transform, dtype=np.float64))
    scene = trimesh.Scene()
    scene.add_geometry(cloud)
    scene.export(file_obj=str(output_path))
    return output_path
