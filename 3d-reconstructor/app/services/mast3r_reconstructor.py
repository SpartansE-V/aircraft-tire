"""MASt3R-based 3D reconstruction service (drop-in replacement for ColmapService).

Runs MASt3R sparse global alignment over a directory of images and produces:

  * ``model.glb``     — colored, confidence-masked point cloud for viewing.
  * ``pointmaps.npz`` — per-image dense data for downstream 2D->3D projection.
  * quality metrics attached to the job.

Heavy deps (torch, mast3r, dust3r, trimesh) are imported lazily inside
``run_job`` so the FastAPI app (and its tests) import without a GPU/torch env.

pointmaps.npz contract (consumed by the gradio-app projector)
-------------------------------------------------------------
Saved with ``numpy.savez_compressed``:

  names            : (N,) unicode   — image basenames, in reconstruction order
  world_transform  : (4,4) float32  — apply before rendering so a highlighted
                                        cloud matches model.glb's orientation
  min_conf_thr     : () float32     — confidence threshold used for model.glb
  meta             : () unicode     — JSON list; per image:
                       {name, orig_w, orig_h, res_w, res_h, crop_left, crop_top,
                        pm_w, pm_h}   (orig pixel -> pointmap index transform)
  pts_{i}          : (pm_h, pm_w, 3) float32  — world-space point per pixel
  col_{i}          : (pm_h, pm_w, 3) uint8    — RGB per pixel
  conf_{i}         : (pm_h, pm_w)    float32  — MASt3R confidence per pixel
  pose_{i}         : (4,4) float32            — camera-to-world
  K_{i}            : (3,3) float32            — intrinsics
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np

from ..config import Settings
from ..domain import JobStatus, PipelinePaths, ReconstructionOptions
from ..job_store import JobStore
from .glb import viewing_transform, write_pointcloud_glb

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


class Mast3rService:
    def __init__(self, settings: Settings, store: JobStore) -> None:
        self.settings = settings
        self.store = store
        self._model = None  # lazily loaded, cached across jobs

    # -- runtime info ------------------------------------------------------
    def get_runtime_info(self) -> dict[str, object]:
        info: dict[str, object] = {
            "engine": "mast3r",
            "model_name": self.settings.mast3r_model_name,
            "configured_device": self.settings.mast3r_device,
            "image_size": self.settings.image_size,
            "workspace_root": str(self.settings.workspace_root),
            "outputs_root": str(self.settings.outputs_root),
        }
        try:
            import torch

            info["torch_version"] = torch.__version__
            info["cuda_available"] = bool(torch.cuda.is_available())
            info["resolved_device"] = self._resolve_device()
            info["available"] = True
        except Exception as exc:  # noqa: BLE001 - torch missing/broken is reportable, not fatal
            info["available"] = False
            info["error"] = f"torch unavailable: {exc}"
        return info

    # -- job lifecycle -----------------------------------------------------
    def create_job(self, options: ReconstructionOptions) -> dict[str, object]:
        paths = self._build_paths(options)
        job_id = uuid.uuid4().hex
        return self.store.create_job(job_id=job_id, options=options, paths=paths)

    def run_job(self, job_id: str) -> None:
        record = self.store.get_job(job_id)
        if record is None:
            raise ValueError(f"Unknown job: {job_id}")
        self.store.set_status(job_id, JobStatus.RUNNING)
        try:
            self._run(job_id, record.options, record.paths)
            self.store.set_status(job_id, JobStatus.COMPLETED)
        except Exception as exc:  # noqa: BLE001 - report failure on the job, don't crash the worker
            self.store.append_log(job_id, f"ERROR: {exc}")
            self.store.set_status(job_id, JobStatus.FAILED, str(exc))

    # -- pipeline ----------------------------------------------------------
    def _run(self, job_id: str, options: ReconstructionOptions, paths: PipelinePaths) -> None:
        def log(message: str) -> None:
            self.store.append_log(job_id, message)

        import torch
        from dust3r.utils.image import load_images
        from mast3r.cloud_opt.sparse_ga import sparse_global_alignment
        from mast3r.image_pairs import make_pairs

        device = options.device or self._resolve_device()
        log(f"Device: {device}")

        image_dir = Path(paths.image_dir)
        filelist = self._list_images(image_dir)
        if not filelist:
            raise RuntimeError(f"No images found in {image_dir}")
        log(f"Found {len(filelist)} image(s). Loading MASt3R model '{self.settings.mast3r_model_name}'...")

        model = self._load_model(device)

        log(f"Preprocessing images at size {options.image_size}...")
        imgs = load_images([str(p) for p in filelist], size=options.image_size, verbose=False)
        if len(imgs) == 1:
            import copy

            imgs = [imgs[0], copy.deepcopy(imgs[0])]
            imgs[1]["idx"] = 1
            filelist = [filelist[0], filelist[0]]

        pairs = make_pairs(imgs, scene_graph=options.scene_graph, prefilter=None, symmetrize=True)
        log(f"Running sparse global alignment ({len(pairs)} pairs, optim='{options.optim_level}')...")

        Path(paths.cache_dir).mkdir(parents=True, exist_ok=True)
        niter2 = 0 if options.optim_level == "coarse" else options.niter2
        scene = sparse_global_alignment(
            [str(p) for p in filelist],
            pairs,
            paths.cache_dir,
            model,
            lr1=options.lr1,
            niter1=options.niter1,
            lr2=options.lr2,
            niter2=niter2,
            device=device,
            opt_depth="depth" in options.optim_level,
            shared_intrinsics=options.shared_intrinsics,
            matching_conf_thr=options.matching_conf_thr,
        )

        log("Extracting dense point maps...")
        rgbimg = scene.imgs  # list of HxWx3 float [0,1]
        focals = _to_numpy(scene.get_focals())
        cams2world = _to_numpy(scene.get_im_poses())  # (N,4,4)
        intrinsics = [_to_numpy(k) for k in scene.intrinsics]
        pts3d, _depths, confs = scene.get_dense_pts3d(clean_depth=True)
        pts3d = [_to_numpy(p) for p in pts3d]
        confs = [_to_numpy(c) for c in confs]

        log("Exporting GLB + point maps...")
        quality = self._export(
            options=options,
            paths=paths,
            filelist=filelist,
            rgbimg=rgbimg,
            pts3d=pts3d,
            confs=confs,
            cams2world=cams2world,
            intrinsics=intrinsics,
        )
        self.store.set_quality(job_id, quality)
        log(
            f"Reconstruction complete: {quality['assessment']} "
            f"({quality['n_images']} images, {quality['points3D']} points, "
            f"mean confidence {quality['mean_confidence']})"
        )

    def _export(
        self,
        *,
        options: ReconstructionOptions,
        paths: PipelinePaths,
        filelist: list[Path],
        rgbimg: list[np.ndarray],
        pts3d: list[np.ndarray],
        confs: list[np.ndarray],
        cams2world: np.ndarray,
        intrinsics: list[np.ndarray],
    ) -> dict[str, object]:
        import PIL.Image

        min_conf = float(options.min_conf_thr)
        world_transform = viewing_transform(cams2world[0]).astype(np.float32)

        npz: dict[str, np.ndarray] = {}
        meta: list[dict[str, object]] = []
        names: list[str] = []
        cloud_pts: list[np.ndarray] = []
        cloud_col: list[np.ndarray] = []
        conf_values: list[np.ndarray] = []

        for i in range(len(rgbimg)):
            pm_h, pm_w = rgbimg[i].shape[:2]
            pm = np.asarray(pts3d[i], dtype=np.float32).reshape(pm_h, pm_w, 3)
            conf = np.asarray(confs[i], dtype=np.float32).reshape(pm_h, pm_w)
            col = np.clip(np.asarray(rgbimg[i]) * 255.0, 0, 255).astype(np.uint8).reshape(pm_h, pm_w, 3)

            # Resize/crop transform (mirrors dust3r.utils.image.load_images, size=512 path)
            orig_w, orig_h = self._original_size(filelist[i], PIL, fallback=(pm_w, pm_h))
            scale = options.image_size / max(orig_w, orig_h)
            res_w, res_h = round(orig_w * scale), round(orig_h * scale)
            cx, cy = res_w // 2, res_h // 2
            crop_left = cx - pm_w / 2.0
            crop_top = cy - pm_h / 2.0

            name = filelist[i].name
            names.append(name)
            meta.append(
                {
                    "name": name,
                    "orig_w": int(orig_w),
                    "orig_h": int(orig_h),
                    "res_w": int(res_w),
                    "res_h": int(res_h),
                    "crop_left": float(crop_left),
                    "crop_top": float(crop_top),
                    "pm_w": int(pm_w),
                    "pm_h": int(pm_h),
                }
            )
            npz[f"pts_{i}"] = pm
            npz[f"col_{i}"] = col
            npz[f"conf_{i}"] = conf
            npz[f"pose_{i}"] = np.asarray(cams2world[i], dtype=np.float32)
            npz[f"K_{i}"] = np.asarray(intrinsics[i], dtype=np.float32)

            mask = (conf > min_conf) & np.isfinite(pm).all(axis=2)
            cloud_pts.append(pm[mask])
            cloud_col.append(col[mask])
            conf_values.append(conf[mask])

        points = np.concatenate(cloud_pts, axis=0) if cloud_pts else np.zeros((0, 3), np.float32)
        colors = np.concatenate(cloud_col, axis=0) if cloud_col else np.zeros((0, 3), np.uint8)

        write_pointcloud_glb(Path(paths.model_glb), points, colors, transform=world_transform)

        npz["names"] = np.asarray(names)
        npz["world_transform"] = world_transform
        npz["min_conf_thr"] = np.asarray(min_conf, dtype=np.float32)
        npz["meta"] = np.asarray(json.dumps(meta))
        np.savez_compressed(paths.pointmaps, **npz)

        all_conf = np.concatenate(conf_values) if conf_values else np.zeros((0,), np.float32)
        mean_conf = float(all_conf.mean()) if all_conf.size else 0.0
        n_points = int(points.shape[0])
        return {
            "assessment": self._assess(n_points, len(rgbimg), mean_conf),
            "n_images": len(rgbimg),
            "points3D": n_points,
            "mean_confidence": round(mean_conf, 3),
            "model_glb": str(paths.model_glb),
            "pointmaps": str(paths.pointmaps),
        }

    # -- helpers -----------------------------------------------------------
    def _load_model(self, device: str):
        if self._model is None:
            from mast3r.model import AsymmetricMASt3R

            self._model = AsymmetricMASt3R.from_pretrained(self.settings.mast3r_model_name).to(device)
            self._model.eval()
        return self._model

    def _resolve_device(self) -> str:
        configured = self.settings.mast3r_device.strip().lower()
        if configured in {"cuda", "cpu"}:
            return configured
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - default to cpu if torch can't be queried
            return "cpu"

    @staticmethod
    def _original_size(path: Path, pil_module, fallback: tuple[int, int]) -> tuple[int, int]:
        try:
            with pil_module.Image.open(path) as img:
                return int(img.size[0]), int(img.size[1])
        except Exception:  # noqa: BLE001 - fall back to pointmap size if the file is unreadable
            return fallback

    @staticmethod
    def _assess(n_points: int, n_images: int, mean_conf: float) -> str:
        if n_points == 0:
            return "failed"
        if n_points >= 50_000 and mean_conf >= 3.0:
            return "good"
        if n_points >= 5_000:
            return "fair"
        return "poor"

    def _list_images(self, image_dir: Path) -> list[Path]:
        if not image_dir.is_dir():
            return []
        return sorted(
            p
            for p in image_dir.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in _IMAGE_EXTENSIONS
        )

    def _build_paths(self, options: ReconstructionOptions) -> PipelinePaths:
        image_dir = self._resolve_image_dir(options.image_dir)
        run_dir = self.settings.outputs_root / f"{options.project_id}-{uuid.uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return PipelinePaths(
            run_dir=str(run_dir),
            image_dir=str(image_dir),
            model_glb=str(run_dir / "model.glb"),
            pointmaps=str(run_dir / "pointmaps.npz"),
            cache_dir=str(run_dir / "cache"),
        )

    def _resolve_image_dir(self, raw_path: str) -> Path:
        workspace_root = self.settings.workspace_root.resolve()
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("Path must stay inside the configured workspace root.") from exc
        if not resolved.is_dir():
            raise ValueError(f"Image directory does not exist: {resolved}")
        return resolved


def _to_numpy(value) -> np.ndarray:
    try:
        import torch

        if isinstance(value, torch.Tensor):
            return value.detach().cpu().numpy()
    except Exception:  # noqa: BLE001 - torch may be absent in some contexts
        pass
    return np.asarray(value)
