"""Service metadata and health endpoint tests."""

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


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/demo", "/demo-assets/demo.css"])
async def test_removed_demo_routes_return_not_found(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 404
