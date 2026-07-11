from __future__ import annotations

import asyncio
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from app.config import Settings
from app.services.uploads import UploadService


class UploadServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace_root = root / "workspace"
        self.workspace_root.mkdir()
        self.images_root = self.workspace_root / "images"
        self.images_root.mkdir()
        self.outputs_root = self.workspace_root / "runs"
        self.outputs_root.mkdir()
        self.settings = Settings(
            app_name="test",
            api_prefix="/api/v1",
            colmap_binary="colmap",
            workspace_root=self.workspace_root,
            images_root=self.images_root,
            outputs_root=self.outputs_root,
            default_camera_model="SIMPLE_RADIAL",
            default_matcher="exhaustive",
        )
        self.service = UploadService(self.settings)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_images_returns_workspace_relative_directory(self) -> None:
        files = [
            UploadFile(file=BytesIO(b"image-1"), filename="front.jpg"),
            UploadFile(file=BytesIO(b"image-2"), filename="side.png"),
        ]

        payload = asyncio.run(self.service.save_images(files=files))

        self.assertRegex(payload["project_uuid"], r"^[0-9a-f-]{36}$")
        self.assertNotIn("project_name", payload)
        self.assertEqual(payload["image_dir"], f"images/{payload['project_uuid']}")
        self.assertEqual(payload["file_count"], 2)
        self.assertTrue((self.images_root / payload["project_uuid"] / "front.jpg").exists())
        self.assertTrue((self.images_root / payload["project_uuid"] / "side.png").exists())

    def test_save_images_rejects_invalid_extension(self) -> None:
        files = [UploadFile(file=BytesIO(b"not-an-image"), filename="notes.txt")]

        with self.assertRaises(ValueError):
            asyncio.run(self.service.save_images(files=files))


if __name__ == "__main__":
    unittest.main()
