"""Exercise the MASt3R reconstructor client against a mocked HTTP transport."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pipeline.reconstructor_client import ReconstructorClient

BASE = "http://reconstructor:8000"


class FakeService:
    def __init__(self) -> None:
        self.get_calls = 0
        self.create_payloads: list[dict[str, object]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method

        if method == "GET" and path.endswith("/api/v1/health"):
            return httpx.Response(200, json={"status": "ok"})
        if method == "GET" and path.endswith("/api/v1/runtime"):
            return httpx.Response(200, json={"available": True, "resolved_device": "cuda", "torch_version": "2.1.2"})
        if method == "POST" and path.endswith("/uploads/images"):
            return httpx.Response(201, json={"project_uuid": "proj-1", "file_count": 3})
        if method == "POST" and path.endswith("/reconstructions"):
            body = json.loads(request.content.decode())
            assert body["project_id"] == "proj-1"
            self.create_payloads.append(body)
            return httpx.Response(202, json={"job_id": "job-1", "status": "queued"})
        if method == "GET" and path.endswith("/reconstructions/job-1/model.glb"):
            return httpx.Response(200, content=b"GLB-BYTES")
        if method == "GET" and path.endswith("/reconstructions/job-1/pointmaps"):
            return httpx.Response(200, content=b"NPZ-BYTES")
        if method == "GET" and path.endswith("/reconstructions/job-1"):
            self.get_calls += 1
            status = "completed" if self.get_calls >= 2 else "running"
            return httpx.Response(200, json={
                "status": status,
                "logs": ["preprocess", "align"] if status == "completed" else ["preprocess"],
                "quality": {"assessment": "good", "n_images": 3, "points3D": 90000, "mean_confidence": 4.2},
            })
        return httpx.Response(404, json={"detail": f"unmapped {method} {path}"})


def _client(service: FakeService) -> ReconstructorClient:
    return ReconstructorClient(BASE, transport=httpx.MockTransport(service.handler))


def test_health_runtime_upload_create() -> None:
    service = FakeService()
    client = _client(service)
    assert client.health() is True
    assert client.runtime_info()["resolved_device"] == "cuda"

    upload = client.upload_images([])
    assert upload["project_uuid"] == "proj-1"

    job = client.create_job(project_id="proj-1", image_size=512, min_conf_thr=1.5, optim_level="refine+depth")
    assert job["job_id"] == "job-1"
    payload = service.create_payloads[-1]
    assert payload["image_size"] == 512
    assert payload["min_conf_thr"] == 1.5
    assert payload["optim_level"] == "refine+depth"


def test_job_status_progression() -> None:
    service = FakeService()
    client = _client(service)
    assert client.get_job("job-1")["status"] == "running"
    completed = client.get_job("job-1")
    assert completed["status"] == "completed"
    assert completed["quality"]["points3D"] == 90000


def test_downloads(tmp_path: Path) -> None:
    service = FakeService()
    client = _client(service)
    glb = client.download_model_glb("job-1", tmp_path / "m.glb")
    npz = client.download_pointmaps("job-1", tmp_path / "p.npz")
    assert glb.read_bytes() == b"GLB-BYTES"
    assert npz.read_bytes() == b"NPZ-BYTES"


def test_unreachable_service() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert ReconstructorClient(BASE, transport=httpx.MockTransport(boom)).health() is False
