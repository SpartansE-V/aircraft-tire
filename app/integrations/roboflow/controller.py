"""Tyre-quality detection orchestration between image inputs and Roboflow inference."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import UploadFile

from app.config import RoboflowSettings
from app.integrations.roboflow.manager import RoboflowManager


class ImageInputError(ValueError):
    """Raised when the caller supplies invalid or missing image input."""


class ImageFetchError(RuntimeError):
    """Raised when a public image URL cannot be retrieved."""


class TyreQualityController:
    """Resolve uploaded or remote images and delegate inference to Roboflow."""

    def __init__(self, settings: RoboflowSettings, manager: RoboflowManager | None = None) -> None:
        self._settings = settings
        self._manager = manager or RoboflowManager(settings)

    async def detect(
        self,
        *,
        image: UploadFile | None = None,
        image_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Run tyre-quality detection on an uploaded file or a public image URL."""

        if image is not None and image_url is not None:
            raise ImageInputError("Provide either an image file or image_url, not both.")
        if image is None and image_url is None:
            raise ImageInputError("Either an image file or image_url is required.")

        if image_url is not None:
            normalized_url = image_url.strip()
            if not normalized_url:
                raise ImageInputError("image_url must not be empty.")
            async with self._temporary_image_source(
                await self._fetch_image_url(normalized_url)
            ) as image_source:
                return self._manager.infer_tyre_quality(image_source)

        if image is None:
            raise ImageInputError("Either an image file or image_url is required.")

        async with self._temporary_image_source(await self._persist_upload(image)) as image_source:
            return self._manager.infer_tyre_quality(image_source)

    @asynccontextmanager
    async def _temporary_image_source(self, image_source: str) -> AsyncIterator[str]:
        try:
            yield image_source
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(image_source)

    async def _fetch_image_url(self, image_url: str) -> str:
        """Download a public image URL and return a temporary local file path."""

        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ImageInputError("image_url must be a valid public http or https URL.")

        timeout = httpx.Timeout(self._settings.image_fetch_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(image_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImageFetchError("Unable to fetch image from the provided URL.") from exc

        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.startswith("image/"):
            raise ImageInputError("image_url must point to an image resource.")

        content = response.content
        if not content:
            raise ImageInputError("Fetched image is empty.")
        if len(content) > self._settings.max_upload_bytes:
            raise ImageInputError(
                f"Fetched image exceeds the {self._settings.max_upload_bytes} byte limit."
            )

        suffix = self._suffix_from_content_type(content_type) or self._suffix_from_url(image_url)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            temp_file.write(content)
            temp_file.flush()
        finally:
            temp_file.close()

        return temp_file.name

    async def _persist_upload(self, image: UploadFile) -> str:
        """Write an uploaded image to a temporary file and return its path."""

        if not image.filename:
            raise ImageInputError("Uploaded image must include a filename.")

        content = await image.read()
        if not content:
            raise ImageInputError("Uploaded image is empty.")
        if len(content) > self._settings.max_upload_bytes:
            raise ImageInputError(
                f"Uploaded image exceeds the {self._settings.max_upload_bytes} byte limit."
            )

        suffix = Path(image.filename).suffix or ".jpg"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            temp_file.write(content)
            temp_file.flush()
        finally:
            temp_file.close()

        return temp_file.name

    @staticmethod
    def _suffix_from_content_type(content_type: str) -> str | None:
        mapping = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/bmp": ".bmp",
        }
        normalized = content_type.split(";", 1)[0].strip().lower()
        return mapping.get(normalized)

    @staticmethod
    def _suffix_from_url(image_url: str) -> str:
        suffix = Path(urlparse(image_url).path).suffix
        return suffix if suffix else ".jpg"
