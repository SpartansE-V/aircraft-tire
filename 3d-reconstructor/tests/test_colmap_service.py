from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.domain import PipelinePaths, ReconstructionOptions
from app.job_store import JobStore
from app.services.colmap import ColmapService


class ColmapServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace_root = root / "workspace"
        self.workspace_root.mkdir()
        self.outputs_root = self.workspace_root / "runs"
        self.outputs_root.mkdir()
        self.settings = Settings(
            app_name="test",
            api_prefix="/api/v1",
            colmap_binary="colmap",
            workspace_root=self.workspace_root,
            images_root=self.workspace_root / "images",
            outputs_root=self.outputs_root,
            default_camera_model="SIMPLE_RADIAL",
            default_matcher="exhaustive",
        )
        self.settings.images_root.mkdir()
        self.service = ColmapService(settings=self.settings, store=JobStore())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_build_commands_adds_dense_pipeline(self) -> None:
        options = ReconstructionOptions(
            project_id="scene",
            image_dir="images/scene",
            camera_model="SIMPLE_RADIAL",
            matcher="exhaustive",
            dense=True,
            use_gpu=False,
            max_image_size=1600,
        )
        paths = PipelinePaths(
            run_dir=str(self.outputs_root / "scene"),
            database_path=str(self.outputs_root / "scene" / "database.db"),
            sparse_dir=str(self.outputs_root / "scene" / "sparse"),
            dense_dir=str(self.outputs_root / "scene" / "dense"),
            image_dir=str(self.workspace_root / "images" / "scene"),
        )
        commands = self.service.build_commands(options, paths)

        self.assertEqual(commands[0][1], "feature_extractor")
        self.assertEqual(commands[1][1], "exhaustive_matcher")
        self.assertEqual(commands[3][1], "image_undistorter")
        self.assertIn("--max_image_size", commands[3])
        self.assertEqual(commands[-1][1], "stereo_fusion")

    def test_create_job_rejects_paths_outside_workspace(self) -> None:
        options = ReconstructionOptions(
            project_id="scene",
            image_dir="../outside",
            camera_model="SIMPLE_RADIAL",
            matcher="exhaustive",
            dense=False,
            use_gpu=False,
        )
        with self.assertRaises(ValueError):
            self.service.create_job(options)

    def test_create_job_accepts_existing_workspace_folder(self) -> None:
        images_dir = self.workspace_root / "images" / "scene"
        images_dir.mkdir(parents=True)
        options = ReconstructionOptions(
            project_id="scene",
            image_dir="images/scene",
            camera_model="SIMPLE_RADIAL",
            matcher="sequential",
            dense=False,
            use_gpu=True,
        )

        job = self.service.create_job(options)

        self.assertEqual(job["status"], "queued")
        self.assertTrue(Path(job["paths"]["run_dir"]).exists())
        self.assertEqual(job["options"]["matcher"], "sequential")


    def test_parse_model_analyzer_extracts_metrics(self) -> None:
        sample = "\n".join(
            [
                "I20260711 08:00:03 229 model.cc:441] Cameras: 4",
                "I20260711 08:00:03 229 model.cc:446] Registered images: 4",
                "I20260711 08:00:03 229 model.cc:448] Points: 18",
                "I20260711 08:00:03 229 model.cc:449] Observations: 44",
                "I20260711 08:00:03 229 model.cc:451] Mean track length: 2.444444",
                "I20260711 08:00:03 229 model.cc:453] Mean observations per image: 11.000000",
                "I20260711 08:00:03 229 model.cc:456] Mean reprojection error: 0.435194px",
            ]
        )

        stats = self.service.parse_model_analyzer(sample)

        self.assertEqual(stats["cameras"], 4)
        self.assertEqual(stats["registered_images"], 4)
        self.assertEqual(stats["points3D"], 18)
        self.assertEqual(stats["observations"], 44)
        self.assertAlmostEqual(stats["mean_track_length"], 2.444444)
        self.assertAlmostEqual(stats["mean_reprojection_error_px"], 0.435194)

    def test_assess_quality_tiers(self) -> None:
        self.assertEqual(self.service.assess_quality({"registered_images": 0}), "failed")
        self.assertEqual(
            self.service.assess_quality(
                {"registered_images": 4, "registration_rate": 0.67, "points3D": 18}
            ),
            "poor",
        )
        self.assertEqual(
            self.service.assess_quality(
                {"registered_images": 8, "registration_rate": 0.8, "points3D": 500}
            ),
            "fair",
        )
        self.assertEqual(
            self.service.assess_quality(
                {
                    "registered_images": 20,
                    "registration_rate": 1.0,
                    "points3D": 5000,
                    "mean_reprojection_error_px": 0.6,
                }
            ),
            "good",
        )


if __name__ == "__main__":
    unittest.main()
