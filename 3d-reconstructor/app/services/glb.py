"""Write colored point clouds to GLB with trimesh.

Self-contained: we deliberately do NOT import ``mast3r.demo`` (which pulls in
gradio + matplotlib). This replicates the point-cloud branch of MASt3R's
``_convert_scene_output_to_glb`` including the viewing transform, so our output
matches the reference demo's orientation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# dust3r.viz.OPENGL — maps the reconstruction frame into a GL-friendly view.
OPENGL = np.array(
    [[1.0, 0.0, 0.0, 0.0], [0.0, -1.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
)
# Rotation.from_euler('y', 180deg) as a 4x4 — matches the MASt3R demo.
ROT_Y_180 = np.array(
    [[-1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
)


def viewing_transform(first_cam2world: np.ndarray) -> np.ndarray:
    """The transform MASt3R's demo applies before export: inv(cam0 @ OPENGL @ rotY180).

    Stored alongside the point maps so the defect-highlighted GLB rendered later
    shares the same orientation as the reconstructor's ``model.glb``.
    """
    first_cam2world = np.asarray(first_cam2world, dtype=np.float64)
    return np.linalg.inv(first_cam2world @ OPENGL @ ROT_Y_180)


def write_pointcloud_glb(
    output_path: Path,
    points: np.ndarray,
    colors: np.ndarray,
    transform: np.ndarray | None = None,
) -> Path:
    """Write an (N,3) point cloud with (N,3) uint8 colors to a .glb file.

    ``transform`` is an optional 4x4 applied to the scene before export.
    """
    import trimesh

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    colors = np.asarray(colors).reshape(-1, 3)
    if colors.dtype != np.uint8:
        # accept float [0,1] as well
        colors = np.clip(colors * 255.0, 0, 255).astype(np.uint8) if colors.max() <= 1.0 else colors.astype(np.uint8)

    finite = np.isfinite(points).all(axis=1)
    points = points[finite]
    colors = colors[finite]

    if points.shape[0] == 0:
        # trimesh can't export an empty scene; emit a single degenerate point.
        points = np.zeros((1, 3), dtype=np.float64)
        colors = np.zeros((1, 3), dtype=np.uint8)

    cloud = trimesh.PointCloud(points, colors=colors)
    if transform is not None:
        cloud.apply_transform(np.asarray(transform, dtype=np.float64))
    scene = trimesh.Scene()
    scene.add_geometry(cloud)
    scene.export(file_obj=str(output_path))
    return output_path
