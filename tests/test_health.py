"""Service metadata and health endpoint tests."""

import subprocess
import sys

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root(client: AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "Aircraft Tire Assessment API",
        "version": "1.0.0",
        "status": "available",
        "documentation": "/docs",
    }


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_app_import_does_not_require_pandas() -> None:
    script = """
import builtins

real_import = builtins.__import__

def import_without_pandas(name, *args, **kwargs):
    if name == "pandas" or name.startswith("pandas."):
        raise ImportError("pandas intentionally unavailable")
    return real_import(name, *args, **kwargs)

builtins.__import__ = import_without_pandas
import app.main
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/demo", "/demo-assets/demo.css"])
async def test_removed_demo_routes_return_not_found(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 404
