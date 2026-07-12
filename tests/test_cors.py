"""CORS coverage for the local frontend-to-API development path."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import LOCAL_CORS_ORIGINS, Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_local_vite_origin_can_post_to_assessment_api() -> None:
    application = create_app(
        Settings(CORS_ORIGINS=LOCAL_CORS_ORIGINS, ENRICH_ON_STARTUP=False)
    )
    transport = ASGITransport(app=application)
    headers = {
        "Origin": "http://localhost:5174",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }

    async with AsyncClient(transport=transport, base_url="http://api.test") as client:
        response = await client.options("/api/v1/tire-assessments", headers=headers)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"
