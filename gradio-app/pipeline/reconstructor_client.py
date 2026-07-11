"""HTTP client for the MASt3R 3d-reconstructor service.

Upload images, start a reconstruction job, poll it, then download the resulting
GLB and dense point maps (pointmaps.npz) used to project detections into 3D.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx


class ReconstructorError(RuntimeError):
    """Raised when the reconstructor service is unreachable or returns an error."""


class ReconstructorClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_prefix: str = "/api/v1",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api = f"{self._base}{api_prefix}"
        self._timeout = httpx.Timeout(timeout)
        self._transport = transport  # injected in tests

    def _client(self, timeout: httpx.Timeout | None = None) -> httpx.Client:
        return httpx.Client(timeout=timeout or self._timeout, transport=self._transport)

    # -- lifecycle ---------------------------------------------------------
    def health(self) -> bool:
        try:
            with self._client(httpx.Timeout(5.0)) as client:
                return client.get(f"{self._api}/health").status_code == 200
        except httpx.HTTPError:
            return False

    def runtime_info(self) -> dict[str, Any]:
        try:
            with self._client(httpx.Timeout(10.0)) as client:
                response = client.get(f"{self._api}/runtime")
            self._raise_for_status(response, "runtime info")
            return response.json()
        except httpx.HTTPError as exc:
            raise ReconstructorError(f"Failed to query runtime info: {exc}") from exc

    # -- pipeline steps ----------------------------------------------------
    def upload_images(self, image_paths: Sequence[Path]) -> dict[str, Any]:
        handles: list[Any] = []
        files: list[tuple[str, tuple[str, Any, str]]] = []
        try:
            for path in image_paths:
                handle = Path(path).open("rb")
                handles.append(handle)
                files.append(("files", (Path(path).name, handle, "application/octet-stream")))
            with self._client() as client:
                response = client.post(
                    f"{self._api}/uploads/images", files=files, data={"overwrite": "true"}
                )
            self._raise_for_status(response, "upload images")
            return response.json()
        except httpx.HTTPError as exc:
            raise ReconstructorError(f"Failed to upload images: {exc}") from exc
        finally:
            for handle in handles:
                handle.close()

    def create_job(
        self,
        *,
        project_id: str,
        image_size: int | None = None,
        min_conf_thr: float | None = None,
        optim_level: str | None = None,
        scene_graph: str | None = None,
        shared_intrinsics: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"project_id": project_id, "shared_intrinsics": shared_intrinsics}
        if image_size is not None:
            payload["image_size"] = int(image_size)
        if min_conf_thr is not None:
            payload["min_conf_thr"] = float(min_conf_thr)
        if optim_level:
            payload["optim_level"] = optim_level
        if scene_graph:
            payload["scene_graph"] = scene_graph
        try:
            with self._client() as client:
                response = client.post(f"{self._api}/reconstructions", json=payload)
            self._raise_for_status(response, "create reconstruction")
            return response.json()
        except httpx.HTTPError as exc:
            raise ReconstructorError(f"Failed to start reconstruction: {exc}") from exc

    def get_job(self, job_id: str) -> dict[str, Any]:
        try:
            with self._client() as client:
                response = client.get(f"{self._api}/reconstructions/{job_id}")
            self._raise_for_status(response, "get job")
            return response.json()
        except httpx.HTTPError as exc:
            raise ReconstructorError(f"Failed to query job {job_id}: {exc}") from exc

    def download_model_glb(self, job_id: str, destination: Path) -> Path:
        return self._download(f"{self._api}/reconstructions/{job_id}/model.glb", destination, "model.glb")

    def download_pointmaps(self, job_id: str, destination: Path) -> Path:
        return self._download(f"{self._api}/reconstructions/{job_id}/pointmaps", destination, "pointmaps")

    # -- helpers -----------------------------------------------------------
    def _download(self, url: str, destination: Path, what: str) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._client() as client:
                with client.stream("GET", url) as response:
                    if response.status_code >= 400:
                        response.read()
                        self._raise_for_status(response, f"download {what}")
                    with destination.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
        except httpx.HTTPError as exc:
            raise ReconstructorError(f"Failed to download {what}: {exc}") from exc
        return destination

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail", ""))
            except Exception:  # noqa: BLE001 - body may not be JSON
                detail = response.text[:200]
            raise ReconstructorError(f"{action} failed ({response.status_code}): {detail}")
