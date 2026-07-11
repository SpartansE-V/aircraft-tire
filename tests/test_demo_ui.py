"""Local demonstration UI serving tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_demo_page_is_available(client: AsyncClient) -> None:
    response = await client.get("/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Complete tire assessment" in response.text
    assert "POST /api/tire-assessments" in response.text
    assert "/api/v1/wear-severity" not in response.text
    assert "/api/v2/" not in response.text
    assert "Decision support only" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/demo-assets/demo.css", "text/css"),
        ("/demo-assets/demo.js", "text/javascript"),
        ("/demo-assets/favicon.svg", "image/svg+xml"),
    ],
)
async def test_demo_assets_are_available(
    client: AsyncClient,
    path: str,
    content_type: str,
) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
