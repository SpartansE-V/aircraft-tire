from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from ..domain import JobStatus, PipelinePaths, ReconstructionOptions
from ..job_store import JobStore

# Metrics parsed from `colmap model_analyzer` output, keyed by result field name.
MODEL_ANALYZER_METRICS: dict[str, tuple[str, type]] = {
    "cameras": (r"Cameras:\s*(\d+)", int),
    "registered_images": (r"Registered images:\s*(\d+)", int),
    "points3D": (r"Points:\s*(\d+)", int),
    "observations": (r"Observations:\s*(\d+)", int),
    "mean_track_length": (r"Mean track length:\s*([\d.]+)", float),
    "mean_observations_per_image": (r"Mean observations per image:\s*([\d.]+)", float),
    "mean_reprojection_error_px": (r"Mean reprojection error:\s*([\d.]+)", float),
}


class ColmapService:
    def __init__(self, settings: Settings, store: JobStore) -> None:
        self.settings = settings
        self.store = store

    def get_runtime_info(self) -> dict[str, object]:
        executable_path = shutil.which(self.settings.colmap_binary)
        info: dict[str, object] = {
            "configured_binary": self.settings.colmap_binary,
            "resolved_binary": executable_path,
            "workspace_root": str(self.settings.workspace_root),
            "outputs_root": str(self.settings.outputs_root),
            "available": executable_path is not None,
        }
        if executable_path is None:
            return info

        try:
            result = subprocess.run(
                [self.settings.colmap_binary, "-h"],
                capture_output=True,
                text=True,
                check=False,
            )
            first_line = ""
            combined = (result.stdout or result.stderr).splitlines()
            if combined:
                first_line = combined[0]
            info["version_hint"] = first_line
        except OSError as exc:
            info["version_hint"] = f"Unable to inspect binary: {exc}"
        return info

    def create_job(self, options: ReconstructionOptions) -> dict[str, object]:
        paths = self._build_pipeline_paths(options)
        job_id = uuid.uuid4().hex
        return self.store.create_job(job_id=job_id, options=options, paths=paths)

    def run_job(self, job_id: str) -> None:
        record = self.store.get_job(job_id)
        if record is None:
            raise ValueError(f"Unknown job: {job_id}")

        self.store.set_status(job_id, JobStatus.RUNNING)
        try:
            commands = self.build_commands(record.options, record.paths)
            for command in commands:
                self.store.add_command(job_id, command)
                self.store.append_log(job_id, f"$ {' '.join(command)}")
                self._run_command(job_id, command)
            self._record_quality(job_id, record.paths)
            self._export_pointcloud_quietly(job_id, record.paths)
            self.store.set_status(job_id, JobStatus.COMPLETED)
        except Exception as exc:
            self.store.append_log(job_id, f"ERROR: {exc}")
            self.store.set_status(job_id, JobStatus.FAILED, str(exc))

    def _export_pointcloud_quietly(self, job_id: str, paths: PipelinePaths) -> None:
        """Export a viewable .ply after a run. Best-effort; never fails the job."""
        try:
            ply_path = self.export_pointcloud(paths)
        except Exception as exc:  # noqa: BLE001 - export is non-critical
            self.store.append_log(job_id, f"WARNING: point cloud export failed: {exc}")
            return
        if ply_path is not None:
            self.store.append_log(job_id, f"Exported point cloud: {ply_path}")

    def export_pointcloud(self, paths: PipelinePaths) -> Path | None:
        """Convert the largest sparse model to a PLY point cloud and return its path.

        Idempotent: reuses an existing model.ply. Returns None when there is no
        sparse model to export (e.g. the reconstruction registered nothing).
        """
        model_dir = self._largest_sparse_model(paths.sparse_dir)
        if model_dir is None:
            return None

        ply_path = Path(paths.sparse_dir) / "model.ply"
        if not ply_path.exists():
            result = subprocess.run(
                [
                    self.settings.colmap_binary,
                    "model_converter",
                    "--input_path",
                    str(model_dir),
                    "--output_path",
                    str(ply_path),
                    "--output_type",
                    "PLY",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or not ply_path.exists():
                detail = (result.stderr or result.stdout).strip()[:300]
                raise RuntimeError(f"colmap model_converter failed: {detail}")
        return ply_path

    def _record_quality(self, job_id: str, paths: PipelinePaths) -> None:
        """Analyze the reconstruction and attach quality metrics to the job.

        Best-effort: a failure here must never fail an otherwise successful run,
        so any error is logged and swallowed rather than propagated.
        """
        try:
            quality = self.analyze_quality(paths)
        except Exception as exc:  # noqa: BLE001 - analysis is non-critical
            self.store.append_log(job_id, f"WARNING: quality analysis failed: {exc}")
            return
        self.store.set_quality(job_id, quality)
        self.store.append_log(
            job_id,
            "Reconstruction quality: "
            f"{quality.get('assessment')} "
            f"({quality.get('registered_images')}/{quality.get('total_input_images')} images registered, "
            f"{quality.get('points3D')} points)",
        )

    def analyze_quality(self, paths: PipelinePaths) -> dict[str, object]:
        total_images = self._count_input_images(paths.image_dir)
        model_dir = self._largest_sparse_model(paths.sparse_dir)
        if model_dir is None:
            return {
                "assessment": "failed",
                "total_input_images": total_images,
                "registered_images": 0,
                "registration_rate": 0.0,
                "points3D": 0,
            }

        stats = self.parse_model_analyzer(self._run_model_analyzer(model_dir))
        stats["model_path"] = str(model_dir)
        stats["total_input_images"] = total_images
        registered = int(stats.get("registered_images", 0))
        stats["registration_rate"] = round(registered / total_images, 3) if total_images else 0.0
        stats["assessment"] = self.assess_quality(stats)
        return stats

    def _count_input_images(self, image_dir: str) -> int:
        directory = Path(image_dir)
        if not directory.is_dir():
            return 0
        return sum(1 for entry in directory.iterdir() if entry.is_file() and not entry.name.startswith("."))

    def _largest_sparse_model(self, sparse_dir: str) -> Path | None:
        """COLMAP writes one folder per disconnected model (sparse/0, sparse/1, ...).

        Return the model with the largest points3D.bin, i.e. the biggest reconstruction.
        """
        root = Path(sparse_dir)
        if not root.is_dir():
            return None
        models = [child for child in root.iterdir() if child.is_dir() and (child / "cameras.bin").exists()]
        if not models:
            return None
        return max(models, key=lambda model: self._points_file_size(model))

    @staticmethod
    def _points_file_size(model_dir: Path) -> int:
        points_file = model_dir / "points3D.bin"
        return points_file.stat().st_size if points_file.exists() else 0

    def _run_model_analyzer(self, model_dir: Path) -> str:
        result = subprocess.run(
            [self.settings.colmap_binary, "model_analyzer", "--path", str(model_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        return f"{result.stdout}\n{result.stderr}"

    @staticmethod
    def parse_model_analyzer(text: str) -> dict[str, object]:
        stats: dict[str, object] = {}
        for key, (pattern, cast) in MODEL_ANALYZER_METRICS.items():
            match = re.search(pattern, text)
            if match:
                stats[key] = cast(match.group(1))
        return stats

    @staticmethod
    def assess_quality(stats: dict[str, object]) -> str:
        """Turn raw metrics into a coarse label: failed / poor / fair / good."""
        registered = int(stats.get("registered_images", 0))
        if registered == 0:
            return "failed"
        rate = float(stats.get("registration_rate", 0.0))
        points = int(stats.get("points3D", 0))
        reprojection_error = float(stats.get("mean_reprojection_error_px", 0.0))
        if rate >= 0.9 and points >= 100 and 0.0 < reprojection_error <= 1.0:
            return "good"
        if rate >= 0.6 and points >= 50:
            return "fair"
        return "poor"

    def build_commands(
        self,
        options: ReconstructionOptions,
        paths: PipelinePaths,
    ) -> list[list[str]]:
        binary = self.settings.colmap_binary
        commands = [
            [
                binary,
                "feature_extractor",
                "--database_path",
                paths.database_path,
                "--image_path",
                paths.image_dir,
                "--ImageReader.camera_model",
                options.camera_model,
                "--FeatureExtraction.use_gpu",
                "1" if options.use_gpu else "0",
            ],
            [
                binary,
                f"{options.matcher}_matcher",
                "--database_path",
                paths.database_path,
                "--FeatureMatching.use_gpu",
                "1" if options.use_gpu else "0",
            ],
            [
                binary,
                "mapper",
                "--database_path",
                paths.database_path,
                "--image_path",
                paths.image_dir,
                "--output_path",
                paths.sparse_dir,
            ],
        ]

        if paths.image_list_path:
            commands[0].extend(["--image_list_path", paths.image_list_path])
            commands[2].extend(["--image_list_path", paths.image_list_path])

        if options.dense and paths.dense_dir:
            sparse_model_dir = str(Path(paths.sparse_dir) / "0")
            undistorter_command = [
                binary,
                "image_undistorter",
                "--image_path",
                paths.image_dir,
                "--input_path",
                sparse_model_dir,
                "--output_path",
                paths.dense_dir,
                "--output_type",
                "COLMAP",
            ]
            if options.max_image_size:
                undistorter_command.extend(["--max_image_size", str(options.max_image_size)])

            commands.extend(
                [
                    undistorter_command,
                    [
                        binary,
                        "patch_match_stereo",
                        "--workspace_path",
                        paths.dense_dir,
                        "--workspace_format",
                        "COLMAP",
                        "--PatchMatchStereo.geom_consistency",
                        "true",
                    ],
                    [
                        binary,
                        "stereo_fusion",
                        "--workspace_path",
                        paths.dense_dir,
                        "--workspace_format",
                        "COLMAP",
                        "--input_type",
                        "geometric",
                        "--output_path",
                        str(Path(paths.dense_dir) / "fused.ply"),
                    ],
                ]
            )

        return commands

    def _run_command(self, job_id: str, command: list[str]) -> None:
        if shutil.which(self.settings.colmap_binary) is None:
            raise RuntimeError(
                f"COLMAP binary '{self.settings.colmap_binary}' was not found. Install COLMAP or set COLMAP_BINARY."
            )

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdout is not None:
            for line in process.stdout:
                cleaned = line.rstrip()
                if cleaned:
                    self.store.append_log(job_id, cleaned)

        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"Command failed with exit code {return_code}: {' '.join(command)}")

    def _build_pipeline_paths(self, options: ReconstructionOptions) -> PipelinePaths:
        image_dir = self._resolve_workspace_path(options.image_dir, must_exist=True, expect_dir=True)
        image_list_path = None
        if options.image_list_path:
            image_list_path = str(
                self._resolve_workspace_path(options.image_list_path, must_exist=True, expect_dir=False)
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_dir = self.settings.outputs_root / f"{options.project_id}-{timestamp}"
        sparse_dir = run_dir / "sparse"
        dense_dir = run_dir / "dense" if options.dense else None

        sparse_dir.mkdir(parents=True, exist_ok=True)
        if dense_dir:
            dense_dir.mkdir(parents=True, exist_ok=True)

        return PipelinePaths(
            run_dir=str(run_dir),
            database_path=str(run_dir / "database.db"),
            sparse_dir=str(sparse_dir),
            dense_dir=str(dense_dir) if dense_dir else None,
            image_dir=str(image_dir),
            image_list_path=image_list_path,
        )

    def _resolve_workspace_path(self, raw_path: str, *, must_exist: bool, expect_dir: bool) -> Path:
        workspace_root = self.settings.workspace_root.resolve()
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("Path must stay inside the configured COLMAP workspace root.") from exc

        if must_exist and not resolved.exists():
            raise ValueError(f"Path does not exist: {resolved}")
        if expect_dir and must_exist and not resolved.is_dir():
            raise ValueError(f"Expected a directory: {resolved}")
        if not expect_dir and must_exist and not resolved.is_file():
            raise ValueError(f"Expected a file: {resolved}")
        return resolved
